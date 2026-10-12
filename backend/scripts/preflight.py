"""Run before every demo: green/red checklist. Usage: npm run preflight"""
import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg

from app.config import db_name, get_settings

ROOT = Path(__file__).resolve().parents[2]
results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    results.append((ok, name, detail))
    print(f"  {'[ OK ]' if ok else '[FAIL]'} {name}" + (f"  - {detail}" if detail else ""))


def db_checks(s) -> None:
    try:
        conn = psycopg.connect(s.database_url, connect_timeout=5)
    except Exception as e:  # noqa: BLE001
        check(False, "database connection", str(e).splitlines()[0])
        return
    with conn:
        check(True, "database connection", db_name(s.database_url))
        exts = {r[0] for r in conn.execute("SELECT extname FROM pg_extension")}
        check({"vector", "pg_trgm"} <= exts, "extensions vector + pg_trgm", ", ".join(sorted(exts)))
        idx = {r[0] for r in conn.execute("SELECT indexname FROM pg_indexes WHERE schemaname='public'")}
        check({"ix_chunks_embedding_hnsw", "ix_chunks_tsv", "uq_one_effective_per_code"} <= idx,
              "indexes (HNSW, GIN, one-effective-version)")
        trg = {r[0] for r in conn.execute("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")}
        check({"audit_log_append_only", "inv_tx_append_only"} <= trg, "append-only triggers installed")
        docs = conn.execute("SELECT count(*) FROM documents WHERE status='effective'").fetchone()[0]
        chunks = conn.execute("SELECT count(*) FROM chunks WHERE status='effective' AND embedding IS NOT NULL").fetchone()[0]
        lots = conn.execute("SELECT count(*) FROM reagent_lots").fetchone()[0]
        users = conn.execute("SELECT count(*) FROM users").fetchone()[0]
        cache = conn.execute("SELECT count(*) FROM answer_cache").fetchone()[0]
        check(docs > 0 and chunks > 0, "effective documents + embedded chunks", f"{docs} docs, {chunks} chunks")
        check(lots > 0, "inventory lots", str(lots))
        check(users >= 4, "users (4 roles)", str(users))
        check(cache > 0, "answer cache warm", f"{cache} entries")
        dims = conn.execute("SELECT vector_dims(embedding) FROM chunks WHERE embedding IS NOT NULL LIMIT 1").fetchone()
        check(bool(dims) and dims[0] == s.embed_dim, "stored embedding dimension", f"{dims[0] if dims else '-'} vs EMBED_DIM {s.embed_dim}")


async def ai_checks(s) -> None:
    check(not (s.demo_mode and s.llm_mock), "MOCK flag off in DEMO_MODE", f"DEMO_MODE={int(s.demo_mode)} LLM_MOCK={int(s.llm_mock)}")
    if s.llm_mock:
        check(False if s.demo_mode else True, "AI provider", "LLM_MOCK=1 (development only - red MOCK AI ribbon is shown)")
        return
    if not s.gemini_api_key:
        check(False, "GEMINI_API_KEY set", "missing - add it to backend/.env")
        return
    check(True, "GEMINI_API_KEY set")
    try:
        from google import genai
        client = genai.Client(api_key=s.gemini_api_key)
        names = {m.name.removeprefix("models/") for m in client.models.list()}
        check(True, "Gemini reachable", f"{len(names)} models visible")
        for label, m in (("fast", s.gemini_model_fast), ("fallback", s.gemini_model_fallback),
                         ("reasoning", s.gemini_model_reasoning), ("embedding", s.gemini_embed_model)):
            check(bool(m) and m in names, f"model {label}", m or "NOT SET (run npm run models:check)")
        from app.services import llm
        vec = await llm.embed_one("preflight", "RETRIEVAL_QUERY")
        check(len(vec) == s.embed_dim, "embedding dimension from API", str(len(vec)))
    except Exception as e:  # noqa: BLE001
        check(False, "Gemini reachable", str(e).splitlines()[0][:120])


def main() -> int:
    s = get_settings()
    print("Smart Lab Assistant preflight\n")
    print("Configuration")
    check(s.jwt_secret not in ("", "dev-secret", "change-me-to-a-long-random-string") and len(s.jwt_secret) >= 24,
          "JWT_SECRET is set and strong")
    check((ROOT / "frontend" / "dist" / "index.html").exists(), "frontend production build", "run `npm run build` if red")
    print("\nDatabase")
    db_checks(s)
    print("\nAI")
    asyncio.run(ai_checks(s))
    print("\nRBAC")
    p = subprocess.run([sys.executable, "-m", "pytest", "tests/test_rbac.py", "-q", "-p", "no:cacheprovider"],
                       cwd=ROOT / "backend", capture_output=True, text=True)
    check(p.returncode == 0, "RBAC route-coverage + role matrix", (p.stdout.strip().splitlines() or [""])[-1])
    bad = [r for r in results if not r[0]]
    print(f"\n{'ALL GREEN' if not bad else f'{len(bad)} CHECK(S) FAILED'} ({len(results) - len(bad)}/{len(results)})")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
