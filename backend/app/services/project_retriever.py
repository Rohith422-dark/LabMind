"""Hybrid (pgvector + full-text, fused with RRF) retrieval over ONE project's chunks.

The project filter is part of the SQL WHERE clause of both arms, not a post-filter: chunks of other projects are never
read into Python, let alone passed to a model. `project_id` has no default on purpose - there is no code path that
retrieves without naming the project the caller was authorised for.
"""
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.retriever import ARM_LIMIT, RRF_K, or_query, to_vec

COLS = "id, project_id, source_type, source_id, source_version, label, page, section, text"


async def retrieve(session: AsyncSession, project_id: uuid.UUID, query_vec: list[float] | None, question: str,
                   k: int = 8) -> list[dict]:
    """Up to k chunk dicts with 'cosine' (None-safe), 'rrf', 'rank' and 'kw_hit'."""
    params: dict = {"pid": project_id, "lim": ARM_LIMIT}
    vec_rows, kw_rows = [], []
    if query_vec is not None:
        await session.execute(text("SELECT set_config('hnsw.iterative_scan', 'relaxed_order', true), "
                                   "set_config('hnsw.ef_search', '200', true)"))
        vec_rows = (await session.execute(text(
            f"SELECT {COLS}, 1 - (embedding <=> CAST(:v AS vector)) AS cosine FROM project_chunks "
            f"WHERE project_id = :pid AND embedding IS NOT NULL "
            f"ORDER BY embedding <=> CAST(:v AS vector) LIMIT :lim"), {**params, "v": to_vec(query_vec)})).mappings().all()
    tsq = or_query(question)
    if tsq:
        cos = "1 - (embedding <=> CAST(:v AS vector))" if query_vec is not None else "NULL::float"
        kw_params = {**params, "tsq": tsq}
        if query_vec is not None:
            kw_params["v"] = to_vec(query_vec)
        kw_rows = (await session.execute(text(
            f"SELECT {COLS}, {cos} AS cosine FROM project_chunks "
            f"WHERE project_id = :pid AND tsv @@ to_tsquery('english', :tsq) "
            f"ORDER BY ts_rank_cd(tsv, to_tsquery('english', :tsq)) DESC LIMIT :lim"), kw_params)).mappings().all()

    fused: dict = {}
    for arm_name, arm in (("vec", vec_rows), ("kw", kw_rows)):
        for rank, r in enumerate(arm, start=1):
            e = fused.setdefault(r["id"], {**dict(r), "rrf": 0.0, "kw_hit": False})
            e["rrf"] += 1.0 / (RRF_K + rank)
            if arm_name == "kw":
                e["kw_hit"] = True
    ranked = sorted(fused.values(), key=lambda e: e["rrf"], reverse=True)[:k]
    for i, e in enumerate(ranked, start=1):
        e["rank"] = i
        e["cosine"] = float(e["cosine"]) if e["cosine"] is not None else 0.0
        assert e["project_id"] == project_id, "cross-project row reached the retriever output"
    return ranked
