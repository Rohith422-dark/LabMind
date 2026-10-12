"""Troubleshooting through the HTTP layer with the REAL pH SOP and its hand-reviewed steps from the manifest."""
import json
from pathlib import Path

import pytest

from tests.conftest import auth
from tests.test_pipeline import DOCS, PH, publish, upload

SEED = Path(__file__).resolve().parents[1] / "seed"
pytestmark = pytest.mark.skipif(not PH.exists(), reason="seed PDFs not present")


async def stream(client, token, path, body):
    out = []
    async with client.stream("POST", path, headers=auth(token), json=body) as r:
        assert r.status_code == 200, await r.aread()
        async for line in r.aiter_lines():
            if line.strip():
                out.append(json.loads(line))
    return out


async def test_comparison_questions_and_diagnosis(client, tokens):
    sen, sci = tokens["senior_analyst"], tokens["scientist"]
    manifest = json.loads((SEED / "manifest.json").read_text(encoding="utf-8"))["documents"]
    d = next(x for x in manifest if x["doc_code"] == "SOP-QC-PH-001")
    job = await upload(client, sen, DOCS / d["file"])
    job["preview"]["steps"] = d["steps"]
    r = await publish(client, sen, job, "TEST-TS-PH")
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]
    q = next(x for x in json.loads((SEED / "demo-questions.json").read_text(encoding="utf-8"))
             if x["kind"] == "troubleshoot_narration")

    ev = await stream(client, sci, "/api/troubleshoot/start",
                      {"document_id": doc_id, "symptom": q["symptom"], "narration": q["question"]})
    stages = [e["stage"] for e in ev if e["type"] == "stage"]
    assert stages[0] == "Parsing your procedure" and any(s.startswith("Aligning to TEST-TS-PH v1") for s in stages)
    rows = next(e for e in ev if e["type"] == "comparison")["rows"]
    by = {r["step_no"]: r for r in rows if r["step_no"]}
    assert by[4]["status"] == "deviation" and by[4]["findings"][0]["actual_text"] == "pH 6.00"   # real parameter deviation
    assert {no for no, r in by.items() if r["status"] == "missing"} >= {2, 5}                    # real omission
    assert all(by[no]["is_critical"] for no in (2, 4, 5))
    questions = next(e for e in ev if e["type"] == "questions")["questions"]
    assert 1 <= len(questions) <= 3 and all(x["key"].startswith(("missing", "confirm")) for x in questions)
    sid = next(e for e in ev if e["type"] == "session")["session_id"]

    # answering a clarifying question updates the comparison and is not flagged out-of-order
    ev2 = await stream(client, sci, f"/api/troubleshoot/{sid}/message",
                       {"text": "I did prepare the three reference buffers pH 4.00, pH 7.00 and pH 10.00 in the 50 mL conical tubes."})
    rows2 = {r["step_no"]: r for r in next(e for e in ev2 if e["type"] == "comparison")["rows"] if r["step_no"]}
    assert rows2[2]["status"] == "followed" and "out_of_order" not in rows2[2]["flags"]

    dg = await client.post(f"/api/troubleshoot/{sid}/diagnose", headers=auth(sci))
    assert dg.status_code == 200, dg.text
    body = dg.json()
    assert body["document"]["doc_code"] == "TEST-TS-PH" and body["diagnosis"]["causes"]
    assert body["diagnosis"]["deviation_advice"]  # critical deviation -> record per deviation process

    # sessions are private to their owner
    assert (await client.get(f"/api/troubleshoot/{sid}", headers=auth(tokens["lab_analyst"]))).status_code == 404
    assert (await client.get(f"/api/troubleshoot/{sid}", headers=auth(sci))).status_code == 200
