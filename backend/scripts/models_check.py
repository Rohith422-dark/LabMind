"""List Gemini models available to our key and print recommended .env values.

Run this FIRST, before writing/depending on any AI code:  npm run models:check
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google import genai

from app.config import get_settings


def main() -> int:
    s = get_settings()
    if not s.gemini_api_key:
        print("GEMINI_API_KEY is empty. Get a free key at https://aistudio.google.com/apikey and put it in backend/.env")
        return 1
    client = genai.Client(api_key=s.gemini_api_key)
    gen, emb = [], []
    for m in client.models.list():
        name = m.name.removeprefix("models/")
        actions = set(m.supported_actions or [])
        if "embedContent" in actions or "embedText" in actions:
            emb.append(name)
        if "generateContent" in actions:
            gen.append(name)

    def flash(n: str) -> bool:
        return "flash" in n and not any(x in n for x in ("image", "tts", "live", "audio", "native", "thinking-exp", "preview-0"))

    flashes = sorted(n for n in gen if flash(n))
    lite = [n for n in flashes if "lite" in n]
    plain = [n for n in flashes if "lite" not in n]
    print("Generate-capable Flash-class models:")
    for n in flashes:
        print("  ", n)
    print("Embedding models:")
    for n in sorted(emb):
        print("  ", n)

    def newest(names: list[str]) -> str:
        return sorted(names)[-1] if names else ""

    fast = newest(lite) or newest(plain)
    reasoning = newest(plain) or fast
    fallback = next((n for n in sorted(plain, reverse=True) if n != reasoning), fast)
    embed = "gemini-embedding-001" if "gemini-embedding-001" in emb else newest(emb)
    print("\nRecommended backend/.env values (free tier: Pro models are not free):")
    print(f"GEMINI_MODEL_FAST={fast}")
    print(f"GEMINI_MODEL_FALLBACK={fallback}")
    print(f"GEMINI_MODEL_REASONING={reasoning}")
    print(f"GEMINI_EMBED_MODEL={embed}")
    print("EMBED_DIM=768   # gemini-embedding-001 with output_dimensionality=768, L2-normalised")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
