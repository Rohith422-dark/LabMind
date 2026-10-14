"""AI assistant mode (general answers, personalisation, project-permission step), role dashboards, audit visibility, SOP deletion."""
import json
import uuid

import psycopg
import pytest

from app.config import get_settings
from app.services import llm, project_retriever
from tests.conftest import _test_url, auth
from tests.test_pipeline import PH, publish, upload
from tests.util import ROLE_USERNAMES, add_member, mk_experiment, mk_project, upload_text, uid  # noqa: F401


@pytest.fixture(autouse=True)
def _clean_user_memory():
    """Preferences saved by these tests must not leak into other modules (which expect a user with no saved memory)."""
    yield
    with psycopg.connect(_test_url, autocommit=True) as c:
        c.execute("DELETE FROM memories")


@pytest.fixture(autouse=True)
def lenient_gate():
    s = get_settings()
    old = s.vector_min_score
    s.vector_min_score = 0.2
    yield
    s.vector_min_score = old


async def chat(client, token, question, conversation_id=None, **extra):
    body = {"question": question, "mode": "assistant", **({"conversation_id": conversation_id} if conversation_id else {}), **extra}
    async with client.stream("POST", "/api/chat/stream", headers=auth(token), json=body) as r:
        assert r.status_code == 200
        raw = (await r.aread()).decode()
    return [json.loads(x) for x in raw.splitlines() if x.strip()]


def kinds(events):
    return [e["type"] for e in events]


async def test_dashboards_are_role_specific_and_real(client, tokens):
    expect = {"scientist": "Welcome back", "lab_analyst": "Lab overview", "senior_analyst": "Knowledge base overview", "admin": "Administration overview"}
    labels = {}
    for role, head in expect.items():
        r = await client.get("/api/dashboard/overview", headers=auth(tokens[role]))
        assert r.status_code == 200, (role, r.text)
        d = r.json()
        assert d["headline"].startswith(head) and len(d["stats"]) >= 6 and len(d["charts"]) == 3 and len(d["blocks"]) >= 3
        labels[role] = {s["label"] for s in d["stats"]}
    assert "Requests waiting" in labels["lab_analyst"] and "Reagents tracked" in labels["lab_analyst"]
    assert "Open knowledge gaps" in labels["senior_analyst"] and "Users" in labels["admin"] and "My projects" in labels["scientist"]
    assert labels["lab_analyst"].isdisjoint({"My projects"})
    assert (await client.get("/api/dashboard/overview")).status_code == 401


async def test_audit_log_is_admin_only(client, tokens):
    assert (await client.get("/api/audit", headers=auth(tokens["senior_analyst"]))).status_code == 403
    assert (await client.get("/api/audit/verify", headers=auth(tokens["senior_analyst"]))).status_code == 403
    assert (await client.get("/api/audit", headers=auth(tokens["admin"]))).status_code == 200


async def test_general_questions_use_model_knowledge_remember_and_personalise(client, tokens, monkeypatch):
    sci = tokens["scientist"]
    prompts: list[str] = []
    real = llm.stream

    async def spy(prompt, **kw):
        prompts.append(prompt)
        async for p in real(prompt, **kw):
            yield p
    monkeypatch.setattr(llm, "stream", spy)

    # a personal preference, stored server-side and private
    ev = await chat(client, sci, "Remember that I prefer answers as short bullet points")
    assert "Saved to your personal preferences" in "".join(e.get("text", "") for e in ev)
    assert [m["content"] for m in (await client.get("/api/memory", headers=auth(sci))).json()] == ["I prefer answers as short bullet points"]

    # a general question: answered from the model (no consent step, no 'knowledge gap', labelled general)
    ev = await chat(client, sci, "What is the boiling point of water at sea level?")
    assert "general" in kinds(ev) and "no_match" not in kinds(ev) and "need_project" not in kinds(ev)
    cid = next(e for e in ev if e["type"] == "meta")["conversation_id"]
    assert "short bullet points" in prompts[-1]                                  # personalised
    with psycopg.connect(_test_url) as c:
        assert c.execute("SELECT count(*) FROM knowledge_gaps WHERE question ILIKE '%boiling point of water%'").fetchone()[0] == 0

    # follow-up in the same conversation sees the previous turn (conversation memory)
    await chat(client, sci, "And what about at altitude?", cid)
    assert "boiling point of water" in prompts[-1]

    # a NEW conversation still knows the user's topics from other chats
    await chat(client, sci, "Explain buffers briefly")
    assert "boiling point of water" in prompts[-1] or "What is the boiling point" in prompts[-1]

    rows = (await client.get(f"/api/chat/conversations/{cid}", headers=auth(sci))).json()
    assert [r["meta"].get("general") for r in rows] == [True, True] and rows[0]["sources"] == []
    # other users never see this preference or topic
    assert (await client.get("/api/memory", headers=auth(tokens["senior_analyst"]))).json() == []


async def test_project_questions_ask_permission_first(client, tokens, monkeypatch, uid):
    sci, ana = tokens["scientist"], tokens["lab_analyst"]
    p = await mk_project(client, sci, name="Tablet stability")
    other = await mk_project(client, tokens["senior_analyst"], name="Not mine")
    await upload_text(client, sci, p["id"], "Stability protocol", "Storage temperature is 25 C and humidity is 60 percent for the stability study.")
    await mk_experiment(client, sci, p["id"], "STAB-7", observations="Tablet hardness measured at 9.2 kp after four weeks.")

    calls = []
    real = project_retriever.retrieve

    async def spy(*a, **k):
        calls.append(a)
        return await real(*a, **k)
    monkeypatch.setattr(project_retriever, "retrieve", spy)

    # keyword, project name and experiment id each trigger the permission step - and nothing is read yet
    for q in ("What did my experiment show about tablet hardness?", "Summarise Tablet stability", "How is STAB-7 doing?"):
        ev = await chat(client, sci, q)
        need = next(e for e in ev if e["type"] == "need_project")
        assert [x["name"] for x in need["projects"]] == ["Tablet stability"] and "general" not in kinds(ev)
    assert calls == []

    # permission granted for ONE project -> grounded answer with citations, inside the same conversation
    ev0 = await chat(client, sci, "What is the storage temperature in my project?")
    cid = next(e for e in ev0 if e["type"] == "meta")["conversation_id"]
    async with client.stream("POST", "/api/chat/assistant/project-answer", headers=auth(sci),
                             json={"question": "What is the storage temperature in my project?", "project_id": p["id"], "conversation_id": cid}) as r:
        assert r.status_code == 200
        ev = [json.loads(x) for x in (await r.aread()).decode().splitlines() if x.strip()]
    cites = next(e for e in ev if e["type"] == "citations")["citations"]
    assert cites and cites[0]["label"] == "Stability protocol" and calls and all(str(c[1]) == p["id"] for c in calls)
    assert "25" in "".join(e.get("text", "") for e in ev if e["type"] == "token")
    rows = (await client.get(f"/api/chat/conversations/{cid}", headers=auth(sci))).json()
    assert rows[-1]["project_id"] == p["id"] and rows[-1]["meta"]["kind"] == "project"

    # cannot name a project the user is not in, nor reuse someone else's conversation
    for body, code in (({"question": "storage temperature", "project_id": other["id"]}, 404),
                       ({"question": "storage temperature", "project_id": p["id"], "conversation_id": str(uuid.uuid4())}, 200)):
        async with client.stream("POST", "/api/chat/assistant/project-answer", headers=auth(sci), json=body) as r:
            raw = (await r.aread()).decode()
            assert r.status_code == code
    assert '"Conversation not found"' in raw
    async with client.stream("POST", "/api/chat/assistant/project-answer", headers=auth(ana),
                             json={"question": "storage temperature", "project_id": p["id"]}) as r:
        assert r.status_code == 404                                              # a user outside the project

    # declining: the question is answered in general terms and the project is never searched
    before = len(calls)
    ev = await chat(client, sci, "What is the storage temperature in my project?", project_check=False)
    assert "general" in kinds(ev) and len(calls) == before

    # no projects at all -> no permission step, plain general answer
    ev = await chat(client, ana, "Tell me about my experiments")
    assert "general" in kinds(ev) and "need_project" not in kinds(ev)


async def test_strict_mode_is_unchanged(client, tokens):
    """The default (strict) mode keeps the approved-documents-only behaviour for existing clients."""
    async with client.stream("POST", "/api/chat/stream", headers=auth(tokens["scientist"]),
                             json={"question": "Zebra quantum chromodynamics xylophone forecast"}) as r:
        evs = [json.loads(x) for x in (await r.aread()).decode().splitlines() if x.strip()]
    assert "no_match" in kinds(evs) and "general" not in kinds(evs)


@pytest.mark.skipif(not PH.exists(), reason="seed PDFs not present")
async def test_senior_can_update_and_delete_documents(client, tokens):
    sen, sci = tokens["senior_analyst"], tokens["scientist"]
    code = "TEST-DEL-001"
    job = await upload(client, sen, PH)
    assert (await publish(client, sen, job, code)).status_code == 200
    job2 = await upload(client, sen, PH)
    v2 = await publish(client, sen, job2, code, note="updated wording")
    assert v2.status_code == 200 and v2.json()["version"] == 2
    vers = (await client.get(f"/api/documents/{code}/versions", headers=auth(sci))).json()
    assert [(v["version"], v["status"]) for v in vers] == [(2, "effective"), (1, "superseded")]     # current + previous stay readable

    assert (await client.delete(f"/api/documents/code/{code}", headers=auth(sci))).status_code == 403
    assert (await client.delete(f"/api/documents/code/{code}", headers=auth(tokens["lab_analyst"]))).status_code == 403
    with psycopg.connect(_test_url) as c:
        logged = c.execute("SELECT count(*) FROM audit_log WHERE action='document_deleted' AND target=%s", (code,)).fetchone()[0]
    assert (await client.delete(f"/api/documents/code/{code}", headers=auth(sen))).status_code == 204
    assert (await client.get(f"/api/documents/{code}/versions", headers=auth(sci))).status_code == 404
    with psycopg.connect(_test_url) as c:
        assert c.execute("SELECT count(*) FROM chunks WHERE doc_code=%s", (code,)).fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM audit_log WHERE action='document_deleted' AND target=%s", (code,)).fetchone()[0] == logged + 1
    assert (await client.delete(f"/api/documents/code/{code}", headers=auth(sen))).status_code == 404


async def test_assistant_answers_reagent_questions_from_the_live_register(client, tokens, monkeypatch):
    from datetime import date, timedelta
    ana, sci = tokens["lab_analyst"], tokens["scientist"]
    name = f"Zirconium solvent {uuid.uuid4().hex[:5]}"
    r = await client.post("/api/inventory/lots", headers=auth(ana), json={
        "reagent_name": name, "unit": "L", "lot_no": "ZR-1", "capacity": 10, "quantity_available": 4, "location": "Cabinet F7",
        "expiry_date": (date.today() + timedelta(days=12)).isoformat()})
    assert r.status_code == 201
    with psycopg.connect(_test_url, autocommit=True) as c:
        c.execute("UPDATE reagents SET hazard_classes = ARRAY['Flammable'], storage_conditions = 'Flammables cabinet', supplier='Acme' WHERE name = %s", (name,))
    prompts: list[str] = []
    real = llm.stream

    async def spy(prompt, **kw):
        prompts.append(prompt)
        async for p in real(prompt, **kw):
            yield p
    monkeypatch.setattr(llm, "stream", spy)

    for q in (f"Do we have {name} in stock?", "Which reagents expire soon?", f"What hazards does {name} have and where is it stored?"):
        ev = await chat(client, sci, q)
        assert "register" in kinds(ev) and "no_match" not in kinds(ev)
        ctx = prompts[-1]
        assert name in ctx and "Cabinet F7" in ctx and "ZR-1" in ctx
    assert "Flammable" in prompts[-1] and "Flammables cabinet" in prompts[-1] and "Acme" in prompts[-1]
    inv = next(e for e in ev if e["type"] == "inventory")
    assert inv["lots"][0]["lot_no"] == "ZR-1" and inv["lots"][0]["quantity_available"] == 4
    cid = next(e for e in ev if e["type"] == "meta")["conversation_id"]
    rows = (await client.get(f"/api/chat/conversations/{cid}", headers=auth(sci))).json()
    assert rows[0]["meta"].get("register") is True
    # a procedure that merely mentions a reagent does not go to the register
    ev = await chat(client, sci, "How do I run the methanol gradient?")
    assert "register" not in kinds(ev)
