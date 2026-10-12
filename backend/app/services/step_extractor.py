import re
from typing import Literal

from pydantic import BaseModel

from app.prompts.metadata_prompt import METADATA_PROMPT
from app.prompts.step_extraction_prompt import STEP_PROMPT
from app.services import llm, units
from app.services.parser import ParsedDoc

DocType = Literal["SOP", "protocol", "troubleshooting_guide", "manual"]
ParamName = Literal["temperature", "time", "volume", "cycles", "speed", "concentration", "ph", "mass",
                    "flow_rate", "reagent", "other"]


class DocMeta(BaseModel):
    doc_code: str = ""
    title: str = ""
    doc_type: DocType = "SOP"
    department: str = ""
    equipment: str = ""
    revision: str = ""


class Param(BaseModel):
    name: ParamName
    value: str
    unit: str | None = None


class StepOut(BaseModel):
    step_no: int
    action: str
    parameters: list[Param] = []
    is_critical: bool = False
    source_page: int | None = None


class StepsOut(BaseModel):
    steps: list[StepOut] = []


def params_to_dict(params: list[Param]) -> dict:
    return {p.name: {"value": p.value, "unit": p.unit} for p in params}


def _slug(filename: str) -> str:
    base = re.sub(r"\.[A-Za-z0-9]+$", "", filename)
    return re.sub(r"[^A-Za-z0-9]+", "-", base).strip("-").upper()[:40] or "DOC"


def heuristic_meta(doc: ParsedDoc, filename: str) -> DocMeta:
    title = next((b.text for p in doc.pages[:2] for b in p.blocks if b.heading and len(b.text) > 6), "")
    text = doc.full_text.lower()
    dtype: DocType = "troubleshooting_guide" if "troubleshoot" in text[:3000] or "troubleshoot" in filename.lower() \
        else ("manual" if "manual" in filename.lower() else "SOP")
    code = re.search(r"\b([A-Z]{2,5}-[A-Z0-9]{2,6}-\d{2,4})\b", doc.full_text[:3000])
    return DocMeta(doc_code=code.group(1) if code else _slug(filename), title=title or _slug(filename),
                   doc_type=dtype)


async def extract_metadata(doc: ParsedDoc, filename: str) -> DocMeta:
    fallback = heuristic_meta(doc, filename)
    sample = "\n\n".join(p.text for p in doc.pages[:2])[:6000]
    try:
        m = await llm.generate_structured(f"Filename: {filename}\n\n{sample}", DocMeta, system=METADATA_PROMPT,
                                          mock=fallback)
    except llm.LLMError:
        return fallback
    return DocMeta(doc_code=m.doc_code or fallback.doc_code, title=m.title or fallback.title,
                   doc_type=m.doc_type, department=m.department, equipment=m.equipment, revision=m.revision)


_STEP_RE = re.compile(r"^\s*(?:step\s*)?(\d{1,2})[.)]\s+(.{8,})$", re.I)
_NAMES = {"temperature": "temperature", "time": "time", "volume": "volume", "speed": "speed", "mass": "mass",
          "concentration": "concentration", "flow": "flow_rate", "percent": "other", "cycles": "cycles"}


def _params_from_text(t: str) -> list[Param]:
    out = []
    for q in units.parse(t):
        if q.kind == "ph":
            out.append(Param(name="ph", value=f"{q.value:g}", unit="pH"))
            continue
        raw = re.match(r"(-?\d+(?:[.,]\d+)?)\s*(.*)", q.raw)
        if raw:
            out.append(Param(name=_NAMES.get(q.kind, "other"), value=raw.group(1).replace(",", "."),
                             unit=raw.group(2) or None))
    return out


def heuristic_steps(doc: ParsedDoc) -> list[StepOut]:
    steps: list[StepOut] = []
    for p in doc.pages:
        for b in p.blocks:
            for line in re.split(r"(?<=[.])\s+(?=\d{1,2}[.)]\s)", b.text):
                m = _STEP_RE.match(line)
                if m:
                    action = m.group(2).strip()
                    critical = bool(re.search(r"\b(critical|must|never|warning|do not)\b", action, re.I))
                    steps.append(StepOut(step_no=len(steps) + 1, action=action[:300],
                                         parameters=_params_from_text(action), is_critical=critical,
                                         source_page=p.page))
    return steps


async def extract_steps(doc: ParsedDoc) -> tuple[list[StepOut], str | None]:
    """Returns (steps, warning). Never raises."""
    text = "\n\n".join(f"[page {p.page}]\n{p.text}" if p.page else p.text for p in doc.pages)[:30000]
    fb = heuristic_steps(doc)
    try:
        r = await llm.generate_structured(text, StepsOut, system=STEP_PROMPT, tier="reasoning",
                                          mock=StepsOut(steps=fb))
        steps = r.steps
    except llm.LLMError:
        steps = fb
    for i, s in enumerate(steps, start=1):
        s.step_no = i
    if not steps:
        return [], "No discrete steps detected - the document will still be searchable."
    return steps, None
