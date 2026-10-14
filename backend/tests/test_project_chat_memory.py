"""12.4 Persistent conversations and memory: survive sessions, stay isolated, respect permission changes."""
import uuid

import psycopg
import pytest

from app.config import get_settings
from app.db import session_maker
from app.deps import make_token
from app.models.tables import User
from app.services import project_memory
from tests.conftest import _test_url, auth
from tests.util import ROLE_USERNAMES, add_member, ask, ev, mk_experiment, mk_project, text_of, upload_text, uid  # noqa: F401


@pytest.fixture(autouse=True)
def lenient_gate():
    s = get_settings()
    old = s.vector_min_score
    s.vector_min_score = 0.2
    yield
    s.vector_min_score = old


async def fresh_token(user_id: str) -> str:
    """A brand-new token for the same user = a new login session / another device."""
    async with session_maker()() as s:
        return make_token(await s.get(User, uuid.UUID(user_id)))


async def test_conversations_persist_reopen_rename_delete(client, tokens, uid):
    sci, ana = tokens["scientist"], tokens["lab_analyst"]
    p = await mk_project(client, sci, name="Persistence project")
    pid = p["id"]
    await upload_text(client, sci, pid, "Culture protocol", "Incubation temperature is 37 C. Incubate the culture for 24 hours.")

    e1 = await ask(client, sci, pid, "What is the incubation temperature for the culture?")
    cid = ev(e1, "meta")["conversation_id"]
    e2 = await ask(client, sci, pid, "How long should the culture incubate?", cid)
    assert ev(e2, "meta")["conversation_id"] == cid

    # "after logout/login on another device": a new token sees the same history
    token2 = await fresh_token(uid["scientist"])
    lst = (await client.get("/api/chat/conversations", headers=auth(token2))).json()
    mine = next(c for c in lst if c["id"] == cid)
    assert mine["project_id"] == pid and mine["project_name"] == "Persistence project" and mine["turns"] == 2
    assert mine["title"].startswith("What is the incubation temperature")
    rows = (await client.get(f"/api/chat/conversations/{cid}", headers=auth(token2))).json()
    assert [r["question"][:12] for r in rows] == ["What is the ", "How long sho"]
    assert rows[0]["sources"] and rows[0]["sources"][0]["label"] == "Culture protocol" and rows[0]["answer"]
    assert (await client.get(f"/api/chat/conversations?project_id={pid}", headers=auth(token2))).json()[0]["id"] == cid
    assert all(c["id"] != cid for c in (await client.get("/api/chat/conversations?scope=global", headers=auth(token2))).json())

    # private to its owner, even for a collaborator on the same project
    await add_member(client, sci, pid, ROLE_USERNAMES["lab_analyst"], "editor")
    assert (await client.get(f"/api/chat/conversations/{cid}", headers=auth(ana))).status_code == 404
    assert all(c["id"] != cid for c in (await client.get("/api/chat/conversations", headers=auth(ana))).json())
    assert (await client.patch(f"/api/chat/conversations/{cid}", headers=auth(ana), json={"title": "mine now"})).status_code == 404
    assert (await client.delete(f"/api/chat/conversations/{cid}", headers=auth(ana))).status_code == 404
    hijack = await ask(client, ana, pid, "hello there colleague", cid)
    assert ev(hijack, "error")["message"] == "Conversation not found"

    # rename, then delete (messages go with it)
    r = await client.patch(f"/api/chat/conversations/{cid}", headers=auth(sci), json={"title": "Incubation questions"})
    assert r.status_code == 200 and r.json()["title"] == "Incubation questions" and r.json()["turns"] == 2
    assert (await client.patch(f"/api/chat/conversations/{cid}", headers=auth(sci), json={"title": "  "})).status_code in (422, 200)
    assert (await client.delete(f"/api/chat/conversations/{cid}", headers=auth(sci))).status_code == 204
    assert (await client.get(f"/api/chat/conversations/{cid}", headers=auth(sci))).status_code == 404
    with psycopg.connect(_test_url) as c:
        assert c.execute("SELECT count(*) FROM chat_history WHERE conversation_id=%s", (cid,)).fetchone()[0] == 0


async def test_conversation_memory_follow_ups_and_summaries(client, tokens):
    sci = tokens["scientist"]
    pid = (await mk_project(client, sci))["id"]
    await upload_text(client, sci, pid, "Culture protocol", "Incubation temperature is 37 C. Incubate the culture for 24 hours.")
    first = await ask(client, sci, pid, "What is the incubation temperature for the culture?")
    cid = ev(first, "meta")["conversation_id"]
    # a short, pronoun-only follow-up is resolved from the stored conversation, with no history sent by the client
    follow = await ask(client, sci, pid, "and how long is it?", cid)
    assert ev(follow, "citations")["citations"] and ev(follow, "need_external") is None
    # the very same words without the stored conversation carry no subject, so nothing can be retrieved
    cold = await ask(client, sci, pid, "and how long is it?")
    assert ev(cold, "need_external") is not None

    mem = (await client.get(f"/api/chat/conversations/{cid}/memory", headers=auth(sci))).json()
    assert mem["summary"] is None and "not a verified record" in mem["note"]
    for i in range(project_memory.SUMMARISE_AFTER):               # grow past the summarisation threshold
        await ask(client, sci, pid, f"Remind me of the incubation temperature, attempt {i}", cid)
    mem = (await client.get(f"/api/chat/conversations/{cid}/memory", headers=auth(sci))).json()
    assert mem["summary"] and mem["summarised_turns"] >= 1 and mem["summary_stale"] is False

    # the prompt for the next turn = bounded recent turns + the (unverified) summary, never the whole history
    async with session_maker()() as s:
        conv = await s.get(__import__("app.models.tables", fromlist=["Conversation"]).Conversation, uuid.UUID(cid))
        summary, turns = await project_memory.conversation_context(s, conv)
    assert summary and len(turns) == 2 * project_memory.RECENT_TURNS
    block = project_memory.prompt_block(summary, [])
    assert "UNVERIFIED" in block and "never evidence" in block

    # the user can wipe the summary
    assert (await client.delete(f"/api/chat/conversations/{cid}/memory", headers=auth(sci))).status_code == 204
    assert (await client.get(f"/api/chat/conversations/{cid}/memory", headers=auth(sci))).json()["summary"] is None


async def test_remember_command_and_user_preferences_are_private(client, tokens):
    sci, ana = tokens["scientist"], tokens["lab_analyst"]
    pid = (await mk_project(client, sci))["id"]
    await add_member(client, sci, pid, ROLE_USERNAMES["lab_analyst"], "viewer")

    e = await ask(client, sci, pid, "Remember that I prefer concise bullet-point answers")
    assert "personal preferences" in text_of(e)
    prefs = (await client.get("/api/memory", headers=auth(sci))).json()
    assert [m["content"] for m in prefs] == ["I prefer concise bullet-point answers"] and prefs[0]["scope"] == "user" and prefs[0]["verified"] is False
    assert (await client.get("/api/memory", headers=auth(ana))).json() == []              # other users never see it
    assert (await client.patch(f"/api/memory/{prefs[0]['id']}", headers=auth(ana), json={"content": "x y"})).status_code == 404
    assert (await client.delete(f"/api/memory/{prefs[0]['id']}", headers=auth(ana))).status_code == 404
    edited = await client.patch(f"/api/memory/{prefs[0]['id']}", headers=auth(sci), json={"content": "I prefer tables"})
    assert edited.status_code == 200 and edited.json()["content"] == "I prefer tables"

    # a project note goes to project memory (editor+); a viewer is told no
    e = await ask(client, sci, pid, "Remember that strain S1 is the control strain")
    assert "project note" in text_of(e) and "not experimental evidence" in text_of(e)
    notes = (await client.get(f"/api/projects/{pid}/memory", headers=auth(ana))).json()
    assert [m["content"] for m in notes] == ["strain S1 is the control strain"] and notes[0]["origin"] == "user"
    v = await ask(client, ana, pid, "Remember that S2 is the treated strain")
    assert "Viewers cannot add project memory" in text_of(v)
    assert len((await client.get(f"/api/projects/{pid}/memory", headers=auth(sci))).json()) == 1

    # prefs are used in the prompt, project notes only when relevant, both are non-evidence
    async with session_maker()() as s:
        uid_sci = (await s.execute(__import__("sqlalchemy").text("SELECT id FROM users WHERE username='t_scientist'"))).scalar_one()
        mems = await project_memory.relevant_memories(s, uid_sci, uuid.UUID(pid), "Which strain is the control?")
    assert {m.kind for m in mems} == {"preference", "note"}
    block = project_memory.prompt_block(None, mems)
    assert "NOT evidence" in block and "never cite" in block

    assert (await client.delete(f"/api/memory/{prefs[0]['id']}", headers=auth(sci))).status_code == 204
    assert (await client.get("/api/memory", headers=auth(sci))).json() == []


async def test_project_memory_persists_and_stays_in_its_project(client, tokens):
    sci, sen = tokens["scientist"], tokens["senior_analyst"]
    pa, pb = (await mk_project(client, sci))["id"], (await mk_project(client, sen))["id"]
    exp = await mk_experiment(client, sci, pa, "M-1", results="yield 80 percent")
    r = await client.post(f"/api/projects/{pa}/memory", headers=auth(sci),
                          json={"content": "Yield in M-1 was 80 percent", "kind": "finding", "origin": "ai_suggested",
                                "source_refs": [{"type": "experiment", "id": exp["id"], "version": 1}]})
    assert r.status_code == 201 and r.json()["origin"] == "ai_suggested" and r.json()["verified"] is False and r.json()["stale"] is False
    # refs must point into the same project
    other = await mk_experiment(client, sen, pb, "Z-1")
    bad = await client.post(f"/api/projects/{pa}/memory", headers=auth(sci),
                            json={"content": "sneaky link", "source_refs": [{"type": "experiment", "id": other["id"]}]})
    assert bad.status_code == 422
    # persistence + isolation
    assert (await client.get(f"/api/projects/{pb}/memory", headers=auth(sen))).json() == []
    assert (await client.get(f"/api/projects/{pa}/memory", headers=auth(sen))).status_code == 404
    mid = r.json()["id"]
    assert (await client.delete(f"/api/projects/{pb}/memory/{mid}", headers=auth(sen))).status_code == 404       # id swap across projects
    assert (await client.patch(f"/api/projects/{pb}/memory/{mid}", headers=auth(sen), json={"content": "overwritten"})).status_code == 404
    async with session_maker()() as s:
        mems = await project_memory.relevant_memories(s, uuid.uuid4(), uuid.UUID(pb), "yield in M-1")
    assert mems == []                                       # B's retrieval cannot see A's memory

    # source changes -> memory goes stale and stops being fed to the model until a human confirms it
    await client.patch(f"/api/projects/{pa}/experiments/{exp['id']}", headers=auth(sci), json={"expected_version": 1, "results": "yield 55 percent"})
    m = (await client.get(f"/api/projects/{pa}/memory", headers=auth(sci))).json()[0]
    assert m["stale"] is True
    async with session_maker()() as s:
        uid_sci = (await s.execute(__import__("sqlalchemy").text("SELECT id FROM users WHERE username='t_scientist'"))).scalar_one()
        assert await project_memory.relevant_memories(s, uid_sci, uuid.UUID(pa), "yield in M-1") == []
    assert (await client.post(f"/api/projects/{pa}/memory/{mid}/confirm", headers=auth(sci))).json()["stale"] is False
    async with session_maker()() as s:
        assert len(await project_memory.relevant_memories(s, uid_sci, uuid.UUID(pa), "yield in M-1")) == 1


async def test_permission_changes_apply_to_chats_and_memory(client, tokens, uid):
    owner, ana = tokens["scientist"], tokens["lab_analyst"]
    pid = (await mk_project(client, owner))["id"]
    await upload_text(client, owner, pid, "Culture protocol", "Incubation temperature is 37 C. Incubate the culture for 24 hours.")
    await add_member(client, owner, pid, ROLE_USERNAMES["lab_analyst"], "editor")

    cid = ev(await ask(client, ana, pid, "What is the incubation temperature for the culture?"), "meta")["conversation_id"]
    for i in range(project_memory.SUMMARISE_AFTER):
        await ask(client, ana, pid, f"incubation temperature again {i}", cid)
    assert (await client.get(f"/api/chat/conversations/{cid}/memory", headers=auth(ana))).json()["summary"]
    assert (await client.post(f"/api/projects/{pid}/memory", headers=auth(ana), json={"content": "analyst note about culture"})).status_code == 201

    # revoke: chat list, chat history, summary, project memory and new questions are all closed immediately
    assert (await client.delete(f"/api/projects/{pid}/members/{uid['lab_analyst']}", headers=auth(owner))).status_code == 204
    assert all(c["id"] != cid for c in (await client.get("/api/chat/conversations", headers=auth(ana))).json())
    assert (await client.get(f"/api/chat/conversations/{cid}", headers=auth(ana))).status_code == 404
    assert (await client.get(f"/api/chat/conversations/{cid}/memory", headers=auth(ana))).status_code == 404
    assert (await client.get(f"/api/projects/{pid}/memory", headers=auth(ana))).status_code == 404
    async with client.stream("POST", f"/api/projects/{pid}/chat/stream", headers=auth(ana),
                             json={"question": "culture protocol", "conversation_id": cid}) as r:
        assert r.status_code == 404
    with psycopg.connect(_test_url) as c:       # derived summary was wiped, not just hidden
        assert c.execute("SELECT summary FROM conversations WHERE id=%s", (cid,)).fetchone()[0] is None

    # the owner's own conversation was untouched; re-granting access brings the history back
    assert (await client.get("/api/chat/conversations", headers=auth(owner))).status_code == 200
    await add_member(client, owner, pid, ROLE_USERNAMES["lab_analyst"], "viewer")
    assert (await client.get(f"/api/chat/conversations/{cid}", headers=auth(ana))).status_code == 200
    # downgrade to viewer: can still read/ask, can no longer write memory
    assert (await client.post(f"/api/projects/{pid}/memory", headers=auth(ana), json={"content": "viewer note here"})).status_code == 403

    # deleting a document makes chat summaries for the project stale (they may restate it)
    with psycopg.connect(_test_url, autocommit=True) as c:
        c.execute("UPDATE conversations SET summary='old summary', summary_stale=false WHERE id=%s", (cid,))
    doc = (await client.get(f"/api/projects/{pid}/documents", headers=auth(owner))).json()["items"][0]
    await client.delete(f"/api/projects/{pid}/documents/{doc['id']}", headers=auth(owner))
    with psycopg.connect(_test_url) as c:
        assert c.execute("SELECT summary_stale FROM conversations WHERE id=%s", (cid,)).fetchone()[0] is True
