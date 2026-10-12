"""Strip identifying / internal details before a question leaves the building."""
import re

_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email]"),
    (re.compile(r"https?://\S+"), "[link]"),
    (re.compile(r"\b(lot|batch|sample|specimen|patient|subject)\s*(no\.?|number|id|#)?\s*[:#]?\s*[A-Z0-9][A-Z0-9-]{2,}\b", re.I), r"\1 [id]"),
    (re.compile(r"\b[A-Z]{1,5}-?\d{4,}[A-Z0-9-]*\b"), "[id]"),
    (re.compile(r"\b(?:\+?\d[\d\s().-]{8,}\d)\b"), "[number]"),
    (re.compile(r"\b(?:Dr|Mr|Mrs|Ms|Prof)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?"), "[person]"),
]


def sanitize(text: str) -> str:
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return re.sub(r"\s+", " ", text).strip()
