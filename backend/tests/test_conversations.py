"""Persistent assistant memory: conversations survive reloads, feed follow-ups server-side, and are private."""
import uuid

import pytest

from app.services import rag
from tests.conftest import auth
from tests.test_pipeline import PH, _lenient_threshold, ask, publish, upload  # noqa: F401

pytestmark = pytest.mark.skipif(not PH.exists(), reason="seed PDFs not present")


@pytest.fixture(autouse=True)
def _isolate():
    """This test publishes its own document; remove it afterwards so other tests' retrieval is unaffected."""
    yield
    import psycopg
    from tests.conftest import _test_url
    with psycopg.connect(_test_url, autocommit=True) as c:
        c.execute("TRUNCATE chunks, sop_steps, document_files, documents, answer_cache, knowledge_gaps, chat_history, "
                  "ingest_jobs, notifications CASCADE")


async def test_conversations_persist_and_remember(client, tokens):
    sen, sci, ana = tokens["senior_analyst"], tokens["scientist"], tokens["lab_analyst"]
    job = await upload(client, sen, PH)
    assert (await publish(client, sen, job, "TEST-CONV-PH")).status_code == 200

    # first turn starts a conversation and tells the client its id
    ev = await ask(client, sci, "How do I recalibrate the pH meter with reference buffers?")
    cid = next(e for e in ev if e["type"] == "meta")["conversation_id"]
    assert uuid.UUID(cid)

    # second turn continues it WITHOUT the client sending any history
    async with client.stream("POST", "/api/chat/stream", headers=auth(sci),
                             json={"question": "and what is the acceptable reading?", "history": [], "conversation_id": cid}) as r:
        assert r.status_code == 200
        await r.aread()

    # memory is read from the database, oldest first
    me = (await client.get("/api/auth/me", headers=auth(sci))).json()["user"]
    mem = await rag.load_history(uuid.UUID(me["id"]), uuid.UUID(cid))
    assert [m["role"] for m in mem[:2]] == ["user", "assistant"] and "recalibrate" in mem[0]["content"]

    # recent chats list: one conversation, titled by its first question, both turns counted
    lst = (await client.get("/api/chat/conversations", headers=auth(sci))).json()
    mine = next(c for c in lst if c["id"] == cid)
    assert mine["title"].startswith("How do I recalibrate") and mine["turns"] == 2

    # reloading restores answers, citations and order
    rows = (await client.get(f"/api/chat/conversations/{cid}", headers=auth(sci))).json()
    assert [r["question"] for r in rows][0].startswith("How do I recalibrate") and len(rows) == 2
    assert rows[0]["answer"] and rows[0]["sources"] and rows[0]["sources"][0]["doc_code"] == "TEST-CONV-PH"

    # private to the owner
    assert (await client.get(f"/api/chat/conversations/{cid}", headers=auth(ana))).status_code == 404
    assert all(c["id"] != cid for c in (await client.get("/api/chat/conversations", headers=auth(ana))).json())

    # no-match + consent fallback stay in the same saved conversation
    ev = await ask(client, sci, "Zebra quantum chromodynamics xylophone pricing forecast")
    nm = next(e for e in ev if e["type"] == "no_match")
    cid2 = next(e for e in ev if e["type"] == "meta")["conversation_id"]
    ext = await client.post("/api/chat/external", headers=auth(sci), json={"gap_id": nm["gap_id"], "conversation_id": cid2})
    assert ext.status_code == 200
    rows2 = (await client.get(f"/api/chat/conversations/{cid2}", headers=auth(sci))).json()
    assert [r["source_type"] for r in rows2] == ["internal", "external"] and rows2[0]["meta"]["gap_id"] == nm["gap_id"]
