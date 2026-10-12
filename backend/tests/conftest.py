"""Test harness. Runs ONLY against TEST_DATABASE_URL; aborts if it equals the demo DB.

Synthetic users/records created here live in the test database only (never the demo DB).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import dotenv_values  # noqa: E402

_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_test_url = os.environ.get("TEST_DATABASE_URL") or _env.get("TEST_DATABASE_URL") \
    or "postgresql://sla:sla@localhost:5432/sla_test"
_demo_url = os.environ.get("DATABASE_URL") or _env.get("DATABASE_URL") or "postgresql://sla:sla@localhost:5432/sla"

from app.config import db_name  # noqa: E402

if db_name(_test_url) == db_name(_demo_url):
    raise SystemExit("REFUSING TO RUN: TEST_DATABASE_URL points at the demo database.")

os.environ["DATABASE_URL"] = _test_url
os.environ["DEMO_MODE"] = "0"
os.environ["LLM_MOCK"] = "1"
os.environ.setdefault("JWT_SECRET", "test-secret")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from argon2 import PasswordHasher  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.db import session_maker  # noqa: E402
from app.deps import make_token  # noqa: E402
from app.main import app  # noqa: E402
from app.models.tables import User  # noqa: E402
from app.permissions import ROLES  # noqa: E402
from scripts.db_init import init  # noqa: E402

ROLE_USERNAMES = {r: f"t_{r}" for r in ROLES}


@pytest.fixture(scope="session", autouse=True)
def _schema():
    init(_test_url)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _users(_schema):
    ph = PasswordHasher()
    async with session_maker()() as s:
        for role, uname in ROLE_USERNAMES.items():
            exists = (await s.execute(text("SELECT 1 FROM users WHERE username=:u"), {"u": uname})).first()
            if not exists:
                s.add(User(username=uname, password_hash=ph.hash("test-password-1"),
                           full_name=f"Test {role}", role=role, department="QA"))
        await s.commit()


@pytest_asyncio.fixture(scope="session")
async def tokens(_users) -> dict[str, str]:
    out = {}
    async with session_maker()() as s:
        for role, uname in ROLE_USERNAMES.items():
            u = (await s.execute(text("SELECT id FROM users WHERE username=:u"), {"u": uname})).scalar_one()
            user = await s.get(User, u)
            out[role] = make_token(user)
    return out


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
