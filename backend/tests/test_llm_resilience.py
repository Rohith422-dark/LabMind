"""Free-tier 429s must never surface raw: retry/backoff, then the model chain, then a friendly typed error."""
import pytest

from app.config import get_settings
from app.services import llm


class Boom(Exception):
    def __init__(self, code):
        super().__init__(f"http {code}")
        self.code = code


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    s = get_settings()
    from aiolimiter import AsyncLimiter
    monkeypatch.setattr(llm, "_limiter", AsyncLimiter(10_000, 1))  # the real 10/min bucket is covered by design, not by waiting
    monkeypatch.setattr(llm, "RETRY_INITIAL", 0.001)
    monkeypatch.setattr(s, "gemini_model_fast", "model-a")
    monkeypatch.setattr(s, "gemini_model_fallback", "model-b")
    monkeypatch.setattr(s, "gemini_model_reasoning", "model-c")


async def test_retry_then_success_same_model():
    calls = []

    async def fn(model):
        calls.append(model)
        if len(calls) < 3:
            raise Boom(429)
        return "ok"
    assert await llm._call(fn, "fast") == "ok"
    assert calls == ["model-a"] * 3


async def test_falls_through_model_chain_on_persistent_429():
    seen = []

    async def fn(model):
        seen.append(model)
        if model == "model-a":
            raise Boom(429)
        return model
    assert await llm._call(fn, "fast") == "model-b"
    assert seen[:3] == ["model-a"] * 3 and seen[-1] == "model-b"


async def test_all_models_exhausted_is_friendly_busy_error():
    async def fn(model):
        raise Boom(503)
    with pytest.raises(llm.LLMError) as e:
        await llm._call(fn, "fast")
    assert e.value.busy and "busy" in str(e.value).lower() and "Traceback" not in str(e.value)


async def test_non_retryable_error_does_not_leak():
    async def fn(model):
        raise ValueError("secret internal detail")
    with pytest.raises(llm.LLMError) as e:
        await llm._call(fn, "fast")
    assert "secret" not in str(e.value) and not e.value.busy


async def test_simulated_429_env_flag_recovers(monkeypatch):
    monkeypatch.setenv("SIMULATE_429", "2")
    monkeypatch.setattr(llm, "_sim429_left", None)

    async def fn(model):
        return "recovered"
    assert await llm._call(fn, "fast") == "recovered"


def test_mock_embedding_is_unit_length_and_deterministic():
    a, b = llm.mock_embedding("pH meter calibration"), llm.mock_embedding("pH meter calibration")
    assert a == b and abs(sum(x * x for x in a) - 1) < 1e-6 and len(a) == get_settings().embed_dim
