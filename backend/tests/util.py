"""Shared helpers for the project / request test modules."""
import io
import json
import uuid

import pytest_asyncio
from sqlalchemy import text

from app.db import session_maker
from tests.conftest import ROLE_USERNAMES, auth


@pytest_asyncio.fixture(scope="session")
async def uid(_users) -> dict[str, str]:
    """role -> user id (as str)."""
    async with session_maker()() as s:
        return {role: str((await s.execute(text("SELECT id FROM users WHERE username=:u"), {"u": u})).scalar_one())
                for role, u in ROLE_USERNAMES.items()}


async def mk_project(client, token: str, name: str | None = None, password: str | None = None, **extra) -> dict:
    body = {"name": name or f"Project {uuid.uuid4().hex[:6]}", "description": "test", "objectives": "test objectives",
            "domain": "chemistry", "tags": ["t1"], **extra}
    if password:
        body["password"] = password
    r = await client.post("/api/projects", headers=auth(token), json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def add_member(client, owner_token: str, pid: str, username: str, role: str):
    r = await client.post(f"/api/projects/{pid}/members", headers=auth(owner_token), json={"username": username, "role": role})
    assert r.status_code == 201, r.text
    return r.json()


async def upload(client, token: str, pid: str, filename: str, data: bytes, **form):
    return await client.post(f"/api/projects/{pid}/documents", headers=auth(token), files={"file": (filename, data)}, data=form)


async def upload_text(client, token: str, pid: str, title: str, body: str):
    r = await upload(client, token, pid, f"{title.replace(' ', '_')}.txt", body.encode(), title=title)
    assert r.status_code == 201, r.text
    return r.json()


async def mk_experiment(client, token: str, pid: str, identifier: str, **kw) -> dict:
    body = {"identifier": identifier, "title": kw.pop("title", f"Run {identifier}"), **kw}
    r = await client.post(f"/api/projects/{pid}/experiments", headers=auth(token), json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def ask(client, token: str, pid: str, question: str, conversation_id: str | None = None) -> list[dict]:
    body = {"question": question, **({"conversation_id": conversation_id} if conversation_id else {})}
    async with client.stream("POST", f"/api/projects/{pid}/chat/stream", headers=auth(token), json=body) as r:
        assert r.status_code == 200, await r.aread()
        raw = (await r.aread()).decode()
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def text_of(events: list[dict]) -> str:
    return "".join(e["text"] for e in events if e["type"] == "token")


def ev(events: list[dict], kind: str) -> dict | None:
    return next((e for e in events if e["type"] == kind), None)


def make_pdf(pages: list[str]) -> bytes:
    import pymupdf
    doc = pymupdf.open()
    for t in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 550, 780), t, fontsize=11)
    out = doc.tobytes()
    doc.close()
    return out


def make_docx(paragraphs: list[str]) -> bytes:
    import docx
    d = docx.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def make_csv(rows: list[list[str]]) -> bytes:
    return ("\n".join(",".join(r) for r in rows)).encode()
