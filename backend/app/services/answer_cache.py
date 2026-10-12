"""Answer cache: key = hash(normalised question). Each row remembers which effective document
versions it was built from; a lookup is a hit only if those versions are still effective."""
import hashlib
import re

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import AnswerCache, Document


def normalize(q: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", q.lower())).strip()


def key_for(q: str) -> str:
    return hashlib.sha256(normalize(q).encode()).hexdigest()


def _versions_hash(pairs: set[tuple[str, int]]) -> str:
    return hashlib.sha256("|".join(f"{c}:{v}" for c, v in sorted(pairs)).encode()).hexdigest()


async def _current_versions(session: AsyncSession, codes: set[str]) -> dict[str, int]:
    if not codes:
        return {}
    rows = (await session.execute(
        select(Document.doc_code, Document.version).where(Document.status == "effective", Document.doc_code.in_(codes))
    )).all()
    return {c: v for c, v in rows}


async def get(session: AsyncSession, question: str) -> dict | None:
    row = await session.get(AnswerCache, key_for(question))
    if row is None:
        return None
    codes = {s["doc_code"] for s in row.sources}
    cur = await _current_versions(session, codes)
    if set(cur) != codes or _versions_hash({(c, cur[c]) for c in codes}) != row.doc_versions_hash:
        return None
    return {"answer": row.answer, "sources": row.sources}


async def put(session: AsyncSession, question: str, answer: str, sources: list[dict]) -> None:
    codes = {s["doc_code"] for s in sources}
    pairs = {(s["doc_code"], s["version"]) for s in sources}
    if not codes:
        return
    stmt = insert(AnswerCache).values(key=key_for(question), answer=answer, sources=sources,
                                      doc_versions_hash=_versions_hash(pairs))
    stmt = stmt.on_conflict_do_update(index_elements=["key"], set_=dict(
        answer=stmt.excluded.answer, sources=stmt.excluded.sources,
        doc_versions_hash=stmt.excluded.doc_versions_hash, created_at=text("now()")))
    await session.execute(stmt)


async def invalidate_doc(session: AsyncSession, doc_code: str) -> None:
    await session.execute(delete(AnswerCache).where(AnswerCache.sources.contains([{"doc_code": doc_code}])))
