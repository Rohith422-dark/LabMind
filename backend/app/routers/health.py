from fastapi import APIRouter
from sqlalchemy import text

from app.config import get_settings
from app.db import session_maker

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    s = get_settings()
    out: dict = {"status": "ok", "demo_mode": s.demo_mode, "demo_cards": s.demo_mode or s.demo_cards, "llm_mock": s.llm_mock,
                 "ai_configured": bool(s.gemini_api_key) or s.llm_mock}
    try:
        async with session_maker()() as session:
            rows = (await session.execute(text("SELECT extname FROM pg_extension"))).scalars().all()
        out["db"] = "up"
        out["extensions"] = sorted(rows)
    except Exception:
        out["db"] = "down"
        out["status"] = "degraded"
    return out
