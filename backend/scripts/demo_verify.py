"""Rehearsal safety net: run every demo question through the REAL pipeline (cache bypassed) and report
whether the answer cited the expected document/page. Usage: npm run demo:verify"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime, timezone

from sqlalchemy import select, text

from app.db import session_maker
from app.models.tables import User
from app.services import rag

QS = Path(__file__).resolve().parents[1] / "seed" / "demo-questions.json"


async def main() -> int:
    questions = json.loads(QS.read_text(encoding="utf-8"))
    async with session_maker()() as s:
        user = (await s.execute(select(User).where(User.role == "scientist"))).scalars().first()
    t0 = datetime.now(timezone.utc)
    bad = 0
    for q in questions:
        if q["kind"] == "troubleshoot_narration":
            continue
        cites, no_match = [], False
        async for ev in rag.answer_stream(user, q["question"], [], None, use_cache=False):
            if ev["type"] == "citations":
                cites = ev["citations"]
            elif ev["type"] == "no_match":
                no_match = True
            elif ev["type"] == "error":
                print(f"ERROR  {q['question'][:60]}: {ev['message']}")
                bad += 1
        if q["kind"] == "not_covered":
            ok = no_match
            detail = "no_match (consent flow will trigger)" if ok else f"UNEXPECTEDLY ANSWERED: {[c['doc_code'] for c in cites]}"
        else:
            hit = [c for c in cites if c["doc_code"] == q["expected_doc_code"]]
            page_ok = (not q.get("expected_page")) or any(c["page"] == q["expected_page"] for c in hit)
            ok = bool(hit) and page_ok
            detail = ("cited " + ", ".join(f"{c['doc_code']} p{c['page']}" for c in cites)) if cites else "no citations"
            if no_match:
                detail = "NO MATCH"
            if hit and not page_ok:
                detail += f"  (expected p{q['expected_page']})"
        bad += 0 if ok else 1
        print(f"{'OK  ' if ok else 'FAIL'}  {q['question'][:62]:62}  {detail}")
    print(f"\n{len(questions) - 1 - bad} ok, {bad} need attention")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
