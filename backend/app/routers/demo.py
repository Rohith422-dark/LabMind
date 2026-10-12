"""Serves the team-authored demo questions (seed/demo-questions.json) to the guide panel. Nothing hardcoded."""
import json
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from app.deps import require
from app.models.tables import User

router = APIRouter(prefix="/demo", tags=["demo"])
QS = Path(__file__).resolve().parents[2] / "seed" / "demo-questions.json"


class DemoQuestion(BaseModel):
    role: str
    question: str
    kind: str
    expected_doc_code: str | None = None
    expected_page: int | None = None
    symptom: str | None = None


@router.get("/questions", response_model=list[DemoQuestion])
async def questions(user: User = require("self.view")):
    if not QS.exists():
        return []
    return json.loads(QS.read_text(encoding="utf-8"))
