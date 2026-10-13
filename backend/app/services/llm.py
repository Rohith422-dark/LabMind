"""The ONLY module that talks to Gemini.

Provides: token-bucket rate limit, retry with backoff+jitter on 429/5xx, a model chain
(quotas are per model), schema-validated structured output, streaming, Google Search
grounding, embeddings, and a development-only mock (LLM_MOCK=1, refused in DEMO_MODE).
"""
import asyncio
import hashlib
import logging
import math
import os
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from aiolimiter import AsyncLimiter
from pydantic import BaseModel
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from app.config import get_settings

log = logging.getLogger("sla.llm")
T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Typed error surfaced to the UI as a friendly message (never a stack trace)."""

    def __init__(self, message: str, busy: bool = False):
        super().__init__(message)
        self.busy = busy


class LLMNotConfigured(LLMError):
    pass


@dataclass
class WebSource:
    title: str
    uri: str


@dataclass
class Grounded:
    text: str
    sources: list[WebSource] = field(default_factory=list)
    grounded: bool = False


_limiter: AsyncLimiter | None = None
_client = None
_sim429_left: int | None = None
RETRY_INITIAL = 1.0  # seconds; tests shrink this


def _get_limiter() -> AsyncLimiter:
    global _limiter
    if _limiter is None:
        _limiter = AsyncLimiter(max(1, get_settings().llm_rpm), 60)
    return _limiter


def limiter_headroom() -> float:
    lim = _get_limiter()
    return max(0.0, lim.max_rate - getattr(lim, "_level", 0.0))


def _client_or_raise():
    global _client
    s = get_settings()
    if not s.gemini_api_key:
        raise LLMNotConfigured("AI is not configured. Add GEMINI_API_KEY to backend/.env.")
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=s.gemini_api_key)
    return _client


def chain(tier: str = "fast") -> list[str]:
    s = get_settings()
    first = s.gemini_model_reasoning if tier == "reasoning" else s.gemini_model_fast
    models = [m for m in dict.fromkeys([first, s.gemini_model_fast, s.gemini_model_fallback]) if m]
    if not models:
        raise LLMNotConfigured("No Gemini models configured. Run `npm run models:check` and fill backend/.env.")
    return models


def _status(exc: BaseException) -> int | None:
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return code if isinstance(code, int) else None


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, (asyncio.TimeoutError, ConnectionError)):
        return True
    st = _status(exc)
    return st in (429, 500, 502, 503, 504)


def _maybe_simulate_429() -> None:
    """SIMULATE_429=n makes the first n real calls fail with a 429 (acceptance test 11)."""
    global _sim429_left
    if _sim429_left is None:
        _sim429_left = int(os.environ.get("SIMULATE_429", "0") or 0)
    if _sim429_left > 0:
        _sim429_left -= 1

        class _Sim(Exception):
            code = 429
        raise _Sim("simulated 429")


def _thinking(model: str, tier: str):
    from google.genai import types
    high = tier == "reasoning"
    try:
        if "gemini-3" in model:
            # "high" measured ~2.5x slower on the free tier; "medium" keeps the extra reasoning at demo-friendly latency
            return types.ThinkingConfig(thinking_level="medium" if high else "low")
        return types.ThinkingConfig(thinking_budget=2048 if high else 0)
    except Exception:  # SDK without that field: leave default
        return None


def _config(model: str, tier: str, system: str | None, schema: type[BaseModel] | None,
            grounding: bool, tools: list | None, temperature: float | None):
    from google.genai import types
    kw: dict[str, Any] = {}
    if system:
        kw["system_instruction"] = system
    if temperature is not None:
        kw["temperature"] = temperature
    if schema is not None:
        kw["response_mime_type"] = "application/json"
        kw["response_schema"] = schema
    if grounding:
        kw["tools"] = [types.Tool(google_search=types.GoogleSearch())]
    elif tools:
        kw["tools"] = tools
    th = _thinking(model, tier)
    if th is not None:
        kw["thinking_config"] = th
    return types.GenerateContentConfig(**kw)


async def _call(fn: Callable[[str], Any], tier: str, timeout: float = 60.0) -> Any:
    """Run fn(model) through limiter + retry, walking the model chain on exhaustion."""
    last: BaseException | None = None
    for model in chain(tier):
        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception(_retryable), stop=stop_after_attempt(3),
                wait=wait_exponential_jitter(initial=RETRY_INITIAL, max=8), reraise=True,
            ):
                with attempt:
                    async with _get_limiter():
                        _maybe_simulate_429()
                        return await asyncio.wait_for(fn(model), timeout)
        except BaseException as e:  # noqa: BLE001
            last = e
            if _retryable(e):
                log.warning("model %s exhausted (%s); trying next in chain", model, e)
                continue
            if isinstance(e, LLMError):
                raise
            log.error("gemini call failed: %s", e)
            raise LLMError("The AI request failed. Please try again.") from e
    raise LLMError("The AI is busy — please retry in a moment.", busy=True) from last


# ------------------------------------------------------------------ mock helpers
def mock_enabled() -> bool:
    return get_settings().llm_mock


_WORD = re.compile(r"[a-z0-9]+")


def mock_embedding(text: str, dim: int | None = None) -> list[float]:
    """Deterministic hashed bag-of-words vector (DEV ONLY): lexical overlap ~ cosine."""
    dim = dim or get_settings().embed_dim
    v = [0.0] * dim
    for w in _WORD.findall(text.lower()):
        if len(w) < 3:
            continue
        h = int.from_bytes(hashlib.md5(w.encode()).digest()[:8], "big")
        v[h % dim] += 1.0
    return _l2(v)


def _l2(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


# ------------------------------------------------------------------ public API
async def generate(prompt: str | list, *, system: str | None = None, tier: str = "fast",
                   mock: str | Callable[[], str] | None = None, temperature: float | None = None) -> str:
    if mock_enabled():
        return mock() if callable(mock) else (mock or "")
    client = _client_or_raise()

    async def run(model: str):
        r = await client.aio.models.generate_content(
            model=model, contents=prompt, config=_config(model, tier, system, None, False, None, temperature))
        return r.text or ""
    return await _call(run, tier)


async def generate_structured(prompt: str | list, schema: type[T], *, system: str | None = None,
                              tier: str = "fast", mock: T | Callable[[], T] | None = None) -> T:
    """Schema-validated output; one retry on validation failure."""
    if mock_enabled():
        if mock is None:
            raise LLMError("No mock provided for structured call")
        return mock() if callable(mock) else mock
    client = _client_or_raise()

    async def run(model: str):
        return await client.aio.models.generate_content(
            model=model, contents=prompt, config=_config(model, tier, system, schema, False, None, 0.1))

    last: Exception | None = None
    for _ in range(2):
        r = await _call(run, tier)
        try:
            parsed = r.parsed if isinstance(r.parsed, schema) else schema.model_validate_json(r.text or "")
            return parsed
        except Exception as e:  # noqa: BLE001
            last = e
    raise LLMError("The AI returned an unreadable result.") from last


async def stream(prompt: str | list, *, system: str | None = None, tier: str = "fast",
                 mock: str | Callable[[], str] | None = None) -> AsyncIterator[str]:
    """Yield text chunks. Retries/chain apply to opening the stream only."""
    if mock_enabled():
        text = mock() if callable(mock) else (mock or "")
        for piece in re.findall(r"\S+\s*", text):
            await asyncio.sleep(0.015)
            yield piece
        return
    client = _client_or_raise()

    async def open_stream(model: str):
        it = await client.aio.models.generate_content_stream(
            model=model, contents=prompt, config=_config(model, tier, system, None, False, None, None))
        first = None
        async for chunk in it:  # force the first chunk so failures surface inside retry
            first = chunk
            break
        return it, first

    it, first = await _call(open_stream, tier)
    if first is not None and first.text:
        yield first.text
    async for chunk in it:
        if chunk.text:
            yield chunk.text


async def generate_grounded(prompt: str, *, system: str | None = None, tier: str = "fast",
                            mock: str | None = None) -> Grounded:
    """Gemini with Google Search grounding; falls back to ungrounded if grounding fails."""
    if mock_enabled():
        return Grounded(text=mock or "", sources=[], grounded=False)
    client = _client_or_raise()
    use_grounding = get_settings().enable_search_grounding

    async def run_g(model: str):
        return await client.aio.models.generate_content(
            model=model, contents=prompt, config=_config(model, tier, system, None, True, None, None))

    if use_grounding:
        try:
            r = await _call(run_g, tier)
            sources: list[WebSource] = []
            try:
                gm = r.candidates[0].grounding_metadata
                seen = set()
                for c in (gm.grounding_chunks or []):
                    if c.web and c.web.uri and c.web.uri not in seen:
                        seen.add(c.web.uri)
                        sources.append(WebSource(title=c.web.title or c.web.uri, uri=c.web.uri))
            except Exception:  # noqa: BLE001
                pass
            return Grounded(text=r.text or "", sources=sources, grounded=bool(sources))
        except LLMError as e:
            log.warning("grounded call failed (%s); falling back to ungrounded", e)
    text = await generate(prompt, system=system, tier=tier)
    return Grounded(text=text, sources=[], grounded=False)


async def embed(texts: list[str], task: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    """Batch embeddings, L2-normalised to EMBED_DIM."""
    s = get_settings()
    if mock_enabled():
        return [mock_embedding(t, s.embed_dim) for t in texts]
    if not s.gemini_embed_model:
        raise LLMNotConfigured("GEMINI_EMBED_MODEL is not set.")
    client = _client_or_raise()
    from google.genai import types
    out: list[list[float]] = []
    for i in range(0, len(texts), 50):
        batch = texts[i:i + 50]

        async def run(_model: str, batch=batch):
            r = await client.aio.models.embed_content(
                model=s.gemini_embed_model, contents=batch,
                config=types.EmbedContentConfig(task_type=task, output_dimensionality=s.embed_dim))
            return [_l2(list(e.values)) for e in r.embeddings]
        out.extend(await _call(run, "fast"))
    return out


async def embed_one(text: str, task: str = "RETRIEVAL_QUERY") -> list[float]:
    return (await embed([text], task))[0]


async def ocr_image(png: bytes) -> str:
    """Transcribe a scanned page (multimodal). Returns '' under mock."""
    if mock_enabled():
        return ""
    client = _client_or_raise()
    from google.genai import types
    parts = [types.Part.from_bytes(data=png, mime_type="image/png"),
             "Transcribe all text on this page exactly, preserving headings and numbered steps. Output plain text only."]

    async def run(model: str):
        r = await client.aio.models.generate_content(model=model, contents=parts,
                                                     config=_config(model, "fast", None, None, False, None, 0.0))
        return r.text or ""
    return await _call(run, "fast", timeout=90.0)


async def extract_from_image(png: bytes, prompt: str, schema: type[T], mock: T | None = None) -> T:
    """Schema-validated multimodal extraction (e.g. reagent label photo)."""
    if mock_enabled():
        if mock is None:
            raise LLMError("No mock provided for image call")
        return mock
    client = _client_or_raise()
    from google.genai import types
    parts = [types.Part.from_bytes(data=png, mime_type="image/png"), prompt]

    async def run(model: str):
        return await client.aio.models.generate_content(
            model=model, contents=parts, config=_config(model, "fast", None, schema, False, None, 0.0))
    r = await _call(run, "fast", timeout=90.0)
    try:
        return r.parsed if isinstance(r.parsed, schema) else schema.model_validate_json(r.text or "")
    except Exception as e:  # noqa: BLE001
        raise LLMError("The AI returned an unreadable result.") from e
