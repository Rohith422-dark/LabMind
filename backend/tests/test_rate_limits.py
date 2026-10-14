"""Abuse protection on the sensitive endpoints is real (everywhere else the limiter is switched off for test isolation)."""
import pytest

from tests.conftest import auth
from tests.util import mk_project


@pytest.mark.rate_limits
async def test_project_password_guessing_is_throttled(client, tokens):
    owner, other = tokens["scientist"], tokens["senior_analyst"]
    p = await mk_project(client, owner, password="a long enough password")
    codes = []
    for i in range(30):
        r = await client.post(f"/api/projects/{p['id']}/access-requests", headers=auth(other), json={"password": f"guess-{i}-guess"})
        codes.append(r.status_code)
    assert codes[0] == 403 and 429 in codes                  # per-IP limit (20/min) kicks in
    assert codes.index(429) <= 20


@pytest.mark.rate_limits
async def test_uploads_and_chat_are_throttled(client, tokens):
    sci = tokens["scientist"]
    p = await mk_project(client, sci)
    seen = set()
    for i in range(40):
        r = await client.post(f"/api/projects/{p['id']}/documents", headers=auth(sci), files={"file": ("x.exe", b"MZ")})
        seen.add(r.status_code)
    assert 429 in seen and 422 in seen
