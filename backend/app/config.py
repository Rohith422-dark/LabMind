from functools import lru_cache
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://sla:sla@localhost:5432/sla"
    test_database_url: str = "postgresql://sla:sla@localhost:5432/sla_test"
    jwt_secret: str = "dev-secret"
    gemini_api_key: str = ""
    gemini_model_fast: str = ""
    gemini_model_fallback: str = ""
    gemini_model_reasoning: str = ""
    gemini_embed_model: str = "gemini-embedding-001"
    embed_dim: int = 768
    vector_min_score: float = 0.55
    llm_rpm: int = 10
    enable_search_grounding: bool = True
    demo_mode: bool = False
    demo_cards: bool = False  # password-less one-click login cards; OFF by default, always on when DEMO_MODE=1
    llm_mock: bool = False
    user_passwords: str = ""
    port: int = 8010
    storage_dir: str = "storage"            # uploaded project documents live here (outside the database, outside the web root)
    project_max_upload_mb: int = 10
    project_min_score: float | None = None  # cosine gate for project retrieval; falls back to VECTOR_MIN_SCORE
    cors_origins: str = ""                  # extra comma-separated allowed origins

    @property
    def async_url(self) -> str:
        return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    @property
    def sync_url(self) -> str:
        return self.database_url

    @property
    def project_score_gate(self) -> float:
        return self.project_min_score if self.project_min_score is not None else self.vector_min_score

    def password_for(self, username: str) -> str | None:
        for pair in self.user_passwords.split(","):
            if ":" in pair:
                u, p = pair.split(":", 1)
                if u.strip() == username:
                    return p.strip()
        return None


def db_name(url: str) -> str:
    return urlparse(url).path.lstrip("/")


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.demo_mode and s.llm_mock:
        raise RuntimeError("LLM_MOCK=1 is not allowed when DEMO_MODE=1")
    return s
