import re

INVENTORY = re.compile(
    r"\b(in stock|stock|available|availability|expir\w*|lots?|inventory|do we have|how much .{0,40}(left|remain\w*)|"
    r"running low|reorder|shelf life)\b", re.I)
CALC = re.compile(r"\b(calculate|calculation|dilut\w+|molarity|molar|how many (ml|µl|ul|grams?)|convert)\b", re.I)
PRONOUN = re.compile(r"\b(it|that|this|they|them|those|these|its|the same|there)\b", re.I)


def classify(question: str) -> str:
    """Rules first. Ambiguous -> SOP RAG."""
    if CALC.search(question):
        return "calculator"
    if INVENTORY.search(question):
        return "inventory"
    return "sop"


def standalone(question: str, history: list[dict]) -> str:
    """Cheap follow-up rewrite: prepend the previous user question when the new one is short/pronoun-ish."""
    prev = next((h["content"] for h in reversed(history) if h.get("role") == "user"), None)
    if prev and (len(question.split()) < 6 or PRONOUN.search(question)):
        return f"{prev} {question}"
    return question
