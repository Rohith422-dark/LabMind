"""Tune VECTOR_MIN_SCORE: print the best-chunk cosine for every answerable / not_covered demo question
and suggest a threshold between the two groups. Usage: npm run calibrate"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.db import session_maker
from app.services import llm, retriever

QS = Path(__file__).resolve().parents[1] / "seed" / "demo-questions.json"


async def main() -> None:
    qs = [q for q in json.loads(QS.read_text(encoding="utf-8")) if q["kind"] in ("answerable", "not_covered")]
    scores: dict[str, list[float]] = {"answerable": [], "not_covered": []}
    for q in qs:
        vec = await llm.embed_one(q["question"], "RETRIEVAL_QUERY")
        async with session_maker()() as s:
            chunks = await retriever.retrieve(s, vec, q["question"], k=6)
        best = max((c["cosine"] for c in chunks), default=0.0)
        scores[q["kind"]].append(best)
        print(f"{q['kind']:12} {best:6.3f}  {q['question'][:70]}")
    lo, hi = min(scores["answerable"]), max(scores["not_covered"], default=0.0)
    print(f"\nlowest answerable = {lo:.3f}   highest not_covered = {hi:.3f}   current = {get_settings().vector_min_score}")
    if lo > hi:
        print(f"Separable. Suggested: VECTOR_MIN_SCORE={(lo + hi) / 2:.2f}")
    else:
        print("NOT cleanly separable: gate 1 alone cannot split these; gate 2 (the LLM ANSWERABLE line) must do the work. "
              f"Suggested conservative VECTOR_MIN_SCORE={max(hi - 0.02, 0):.2f}")


if __name__ == "__main__":
    asyncio.run(main())
