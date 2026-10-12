"""Hybrid retrieval in SQL, always pre-filtered to status = 'effective':
pgvector cosine arm + Postgres full-text arm, fused with Reciprocal Rank Fusion (k=60)."""
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

RRF_K = 60
ARM_LIMIT = 20
STOP = set("the a an and or of to in on at for with by is are was were be do does did how what when where which who "
           "why can could should would i we you my our your me it this that these those from into about as if then "
           "than there their have has had not no".split())

COLS = "id, document_id, doc_code, title, version, page, section, text, ocr"


def to_vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in v) + "]"


def or_query(q: str) -> str | None:
    words = [w for w in re.findall(r"[a-z0-9]+", q.lower()) if len(w) > 2 and w not in STOP]
    return " | ".join(dict.fromkeys(words)) if words else None


async def retrieve(session: AsyncSession, query_vec: list[float], question: str, k: int = 6,
                   doc_types: tuple[str, ...] | None = None, equipment: str | None = None) -> list[dict]:
    """Returns up to k chunk dicts with 'cosine' (raw), 'rrf' and 'rank' fields."""
    # corpus is small: make the filtered HNSW scan return enough rows, never drop the filter
    await session.execute(text("SELECT set_config('hnsw.iterative_scan', 'relaxed_order', true), "
                               "set_config('hnsw.ef_search', '200', true)"))
    extra = ""
    params: dict = {"v": to_vec(query_vec), "lim": ARM_LIMIT}
    if doc_types:
        extra += " AND document_id IN (SELECT id FROM documents WHERE doc_type = ANY(:types))"
        params["types"] = list(doc_types)
    if equipment:
        extra += " AND document_id IN (SELECT id FROM documents WHERE equipment ILIKE :eq)"
        params["eq"] = f"%{equipment}%"

    vec_rows = (await session.execute(text(
        f"SELECT {COLS}, 1 - (embedding <=> CAST(:v AS vector)) AS cosine FROM chunks "
        f"WHERE status = 'effective' AND embedding IS NOT NULL{extra} "
        f"ORDER BY embedding <=> CAST(:v AS vector) LIMIT :lim"), params)).mappings().all()

    kw_rows = []
    tsq = or_query(question)
    if tsq:
        kw_rows = (await session.execute(text(
            f"SELECT {COLS}, 1 - (embedding <=> CAST(:v AS vector)) AS cosine FROM chunks "
            f"WHERE status = 'effective' AND tsv @@ to_tsquery('english', :tsq){extra} "
            f"ORDER BY ts_rank_cd(tsv, to_tsquery('english', :tsq)) DESC LIMIT :lim"),
            {**params, "tsq": tsq})).mappings().all()

    fused: dict = {}
    for arm in (vec_rows, kw_rows):
        for rank, r in enumerate(arm, start=1):
            e = fused.setdefault(r["id"], {**dict(r), "rrf": 0.0})
            e["rrf"] += 1.0 / (RRF_K + rank)
    ranked = sorted(fused.values(), key=lambda e: e["rrf"], reverse=True)[:k]
    for i, e in enumerate(ranked, start=1):
        e["rank"] = i
        e["cosine"] = float(e["cosine"]) if e["cosine"] is not None else 0.0
    return ranked
