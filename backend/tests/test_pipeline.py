"""End-to-end through the real HTTP layer with REAL seed PDFs (LLM_MOCK, so no quota is used)."""
import asyncio
import json
from pathlib import Path

import pytest

from app.config import get_settings
from tests.conftest import auth

DOCS = Path(__file__).resolve().parents[1] / "seed" / "docs"
PH = DOCS / "ph-meter-sop-usc.pdf"
pytestmark = pytest.mark.skipif(not PH.exists(), reason="seed PDFs not present")


@pytest.fixture(autouse=True)
def _lenient_threshold():
    s = get_settings()
    old = s.vector_min_score
    s.vector_min_score = 0.12  # mock embeddings are lexical; real threshold is calibrated with `npm run calibrate`
    yield
    s.vector_min_score = old


async def upload(client, token, path: Path):
    r = await client.post("/api/documents/extract", headers=auth(token),
                          files={"file": (path.name, path.read_bytes(), "application/pdf")})
    assert r.status_code == 202, r.text
    jid = r.json()["job_id"]
    for _ in range(100):
        j = (await client.get(f"/api/documents/jobs/{jid}", headers=auth(token))).json()
        if j["status"] in ("ready", "failed"):
            return j
        await asyncio.sleep(0.1)
    raise AssertionError("job did not finish")


async def publish(client, token, job, code, note=None, gap_id=None):
    m = job["preview"]["metadata"]
    body = {"job_id": job["id"], "doc_code": code, "title": m["title"] or "pH meter", "doc_type": "SOP",
            "department": "QC", "equipment": "pH meter", "change_note": note, "steps": job["preview"]["steps"],
            "gap_id": gap_id}
    return await client.post("/api/documents/publish", headers=auth(token), json=body)


async def ask(client, token, q, history=None):
    events = []
    async with client.stream("POST", "/api/chat/stream", headers=auth(token),
                             json={"question": q, "history": history or []}) as r:
        assert r.status_code == 200
        async for line in r.aiter_lines():
            if line.strip():
                events.append(json.loads(line))
    return events


async def test_full_flow(client, tokens):
    sen, sci, adm = tokens["senior_analyst"], tokens["scientist"], tokens["admin"]

    # scientist cannot upload
    r = await client.post("/api/documents/extract", headers=auth(sci),
                          files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")})
    assert r.status_code == 403

    # garbage is rejected cleanly, never a 500
    r = await client.post("/api/documents/extract", headers=auth(sen), files={"file": ("x.pdf", b"not a pdf", "application/pdf")})
    assert r.status_code == 422

    job = await upload(client, sen, PH)
    assert job["status"] == "ready", job
    assert job["preview"]["chunk_count"] > 0 and job["preview"]["metadata"]["title"]

    # a new code publishes as v1
    code = "TEST-PH-001"
    r = await publish(client, sen, job, code)
    assert r.status_code == 200, r.text
    d1 = r.json()
    assert d1["version"] == 1 and d1["status"] == "effective"
    # double click is idempotent
    r2 = await publish(client, sen, job, code)
    assert r2.status_code == 200 and r2.json()["id"] == d1["id"]

    # chat: streamed, cited from the effective version
    ev = await ask(client, sci, "How do I recalibrate the pH meter with reference buffers?")
    types = [e["type"] for e in ev]
    assert types[0] == "meta" and "token" in types and "citations" in types and types[-1] == "done", types
    cit = next(e for e in ev if e["type"] == "citations")["citations"]
    assert cit and cit[0]["doc_code"] == code and cit[0]["version"] == 1 and cit[0]["page"]

    # citation click-through: highlights from the source PDF
    h = await client.get(f"/api/documents/{cit[0]['document_id']}/highlights", headers=auth(sci),
                         params={"chunk_id": cit[0]["chunk_id"]})
    assert h.status_code == 200 and h.json()["rects"], h.text
    f = await client.get(f"/api/documents/{cit[0]['document_id']}/file", headers=auth(sci))
    assert f.status_code == 200 and f.content[:5] == b"%PDF-"

    # same question again is served from cache and still cites
    ev2 = await ask(client, sci, "How do I recalibrate the pH meter with reference buffers?")
    assert any(e["type"] == "citations" and e["citations"] for e in ev2)

    # versioning: change note required, previous version superseded and never retrievable
    job2 = await upload(client, sen, PH)
    r = await publish(client, sen, job2, code)
    assert r.status_code == 422 and "change note" in r.text.lower()
    r = await publish(client, sen, job2, code, note="Re-issued for test")
    assert r.status_code == 200 and r.json()["version"] == 2
    vers = (await client.get(f"/api/documents/{code}/versions", headers=auth(sci))).json()
    assert [(v["version"], v["status"]) for v in vers] == [(2, "effective"), (1, "superseded")]
    ev3 = await ask(client, sci, "How do I recalibrate the pH meter with reference buffers?")
    cit3 = next(e for e in ev3 if e["type"] == "citations")["citations"]
    assert {c["version"] for c in cit3} == {2}

    # not covered -> no_match + gap (and no LLM answer)
    ev4 = await ask(client, sci, "Zebra quantum chromodynamics xylophone pricing forecast")
    nm = next(e for e in ev4 if e["type"] == "no_match")
    gap_id = nm["gap_id"]
    again = await ask(client, sci, "Zebra quantum chromodynamics xylophone pricing forecast")
    gaps = (await client.get("/api/gaps", headers=auth(sen))).json()
    assert [g["similar_count"] for g in gaps if g["id"] == gap_id] == [2]
    assert any(e["type"] == "no_match" for e in again)

    # consent fallback: uses the STORED question; never stored in the knowledge base
    ext = await client.post("/api/chat/external", headers=auth(sci), json={"gap_id": gap_id})
    assert ext.status_code == 200 and ext.json()["answer"]
    rq = await client.patch(f"/api/gaps/{gap_id}/request-sop", headers=auth(sci))
    assert rq.status_code == 200 and rq.json()["status"] == "sop_requested"
    assert (await client.get("/api/gaps", headers=auth(sci))).status_code == 403

    # publishing linked to the gap resolves it and notifies the requester
    job3 = await upload(client, sen, DOCS / "balance-sop-usc.pdf")
    r = await publish(client, sen, job3, "TEST-BAL-001", gap_id=gap_id)
    assert r.status_code == 200
    gaps = (await client.get("/api/gaps", headers=auth(sen))).json()
    assert [g["status"] for g in gaps if g["id"] == gap_id] == ["resolved"]
    notes = (await client.get("/api/notifications", headers=auth(sci))).json()
    assert any("TEST-BAL-001" in n["message"] for n in notes)

    # retire: reason required; retired docs are no longer retrievable
    doc_id = r.json()["id"]
    assert (await client.post(f"/api/documents/{doc_id}/retire", headers=auth(sen), json={"reason": ""})).status_code == 422
    assert (await client.post(f"/api/documents/{doc_id}/retire", headers=auth(sen), json={"reason": "obsolete"})).status_code == 200

    # audit trail has the chain, the denial and the external use; integrity verifies
    rows = (await client.get("/api/audit?limit=1000", headers=auth(adm))).json()
    actions = {a["action"] for a in rows}
    assert {"document_published", "external_ai_used", "access_denied", "chat_question", "document_retired"} <= actions
    v = (await client.get("/api/audit/verify", headers=auth(adm))).json()
    assert v["ok"] is True, v


async def test_unseen_real_pdfs_never_crash(client, tokens):
    """A judge may upload any real PDF: every seed document must parse to a usable preview."""
    sen = tokens["senior_analyst"]
    for p in sorted(DOCS.glob("*.pdf")):
        job = await upload(client, sen, p)
        assert job["status"] == "ready", (p.name, job.get("error"))
        assert job["preview"]["chunk_count"] > 0
