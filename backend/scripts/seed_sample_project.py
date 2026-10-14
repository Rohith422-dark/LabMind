"""Create the sample project "pH Metry Method Validation" (pH-metry experiments + the pH metry SOP as project documentation).

Idempotent: does nothing if the owner already has a project with that name. Goes through the real API in-process, so validation,
version history and embedding/indexing behave exactly as for a user.

Usage: python scripts/seed_sample_project.py [--owner scientist] [--editor senior]
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db import session_maker
from app.deps import make_token
from app.main import app
from app.models.tables import User

NAME = "pH Metry Method Validation"
SOP = Path(__file__).resolve().parents[1] / "seed" / "sample" / "ph-metry-sop.md"
BUF4, BUF7, BUF10 = "pH 4.01 buffer", "pH 7.00 buffer", "pH 10.01 buffer"
METER = [{"name": "Benchtop pH meter", "id": "PH-02"}, {"name": "Combined glass electrode", "id": "EL-114"}]


def calib(ident, title, day, outcome, slope, offset, response, buffers, observations, results, conclusions=None, tags=None, note=None):
    return {
        "identifier": ident, "title": title, "performed_at": f"2026-09-{day:02d}T09:30:00Z", "outcome": outcome,
        "objective": "Calibrate the pH meter and check the electrode against the SOP acceptance criteria (slope 95-105 %, offset within 30 mV, response under 30 s).",
        "reagents": [{"name": n, "lot_no": lot, "quantity": 50, "unit": "mL"} for n, lot in buffers], "equipment": METER,
        "parameters": [{"name": "Electrode slope", "value": slope, "unit": "%"}, {"name": "Offset at pH 7.00", "value": offset, "unit": "mV"},
                       {"name": "Response time", "value": response, "unit": "s"}, {"name": "Temperature", "value": 25.0, "unit": "C"}],
        "conditions": {"calibration": "three-point", "stirring": "gentle"}, "observations": observations, "results": results,
        "conclusions": conclusions, "tags": tags or ["calibration"], "_note": note,
    }


EXPERIMENTS = [
    calib("PH-001", "Three-point calibration, fresh electrode", 2, "success", 99.1, -4, 14, [(BUF4, "B4-2601"), (BUF7, "B7-2601"), (BUF10, "B10-2601")],
          "Stable reading reached quickly in every buffer. Electrode glass clear, no bubbles.", "Slope 99.1 percent, offset minus 4 mV, response 14 s. All criteria met.", "Meter is suitable for sample measurements."),
    calib("PH-002", "Daily calibration after overnight storage in 3 M KCl", 3, "success", 98.4, -6, 17, [(BUF4, "B4-2601"), (BUF7, "B7-2601"), (BUF10, "B10-2601")],
          "Electrode stored in 3 M KCl overnight. Readings stable within 20 s.", "Slope 98.4 percent, offset minus 6 mV, response 17 s. All criteria met."),
    calib("PH-003", "Calibration with aged electrode", 14, "failure", 91.2, -28, 45, [(BUF4, "B4-2601"), (BUF7, "B7-2601"), (BUF10, "B10-2601")],
          "Readings drifted slowly in every buffer and took about 45 s to stabilise. Junction looked slightly cloudy.",
          "Slope 91.2 percent is below the 95 percent limit; response time 45 s exceeds 30 s. Calibration failed.",
          "Electrode needs cleaning in 0.1 M HCl and re-testing; replace it if the slope stays below 95 percent.", ["calibration", "deviation"]),
    calib("PH-004", "Re-calibration after cleaning the electrode in 0.1 M HCl", 15, "success", 97.6, -9, 21, [(BUF4, "B4-2601"), (BUF7, "B7-2601"), (BUF10, "B10-2601")],
          "Electrode soaked in 0.1 M HCl for 15 minutes and rinsed. Readings stable again.", "Slope 97.6 percent, offset minus 9 mV, response 21 s. Criteria met after cleaning.",
          "Cleaning restored the electrode; monitor the slope over the next days.", ["calibration", "corrective-action"]),
    calib("PH-005", "Calibration with an expired pH 10.01 buffer", 21, "inconclusive", 93.5, -12, 26, [(BUF4, "B4-2601"), (BUF7, "B7-2601"), (BUF10, "B10-2504")],
          "The pH 10.01 buffer bottle was past its expiry date when it was used. Slope low only at the alkaline point.",
          "Slope 93.5 percent is below the limit, but the pH 10.01 buffer lot B10-2504 had expired.", "Result not valid; repeat the calibration with an in-date buffer.", ["calibration", "deviation"]),
    {
        "identifier": "PH-006", "title": "pH of 0.05 M phosphate buffer", "performed_at": "2026-09-04T11:00:00Z", "outcome": "success",
        "objective": "Measure the pH of freshly prepared 0.05 M phosphate buffer after a passing calibration.",
        "reagents": [{"name": "Sodium dihydrogen phosphate", "lot_no": "P1-77", "quantity": 3.45, "unit": "g"}, {"name": "Disodium hydrogen phosphate", "lot_no": "P2-31", "quantity": 7.1, "unit": "g"}],
        "equipment": METER, "parameters": [{"name": "pH", "value": 7.02, "unit": ""}, {"name": "Temperature", "value": 25.0, "unit": "C"}, {"name": "Check of pH 7.00 buffer after series", "value": 7.01, "unit": ""}],
        "conditions": {"buffer concentration": "0.05 M", "stirring": "gentle"}, "observations": "Three replicate readings agreed within 0.01 pH units.",
        "results": "Mean pH 7.02 at 25 C. End-of-series check of the pH 7.00 buffer read 7.01, within the 0.05 limit.", "conclusions": "Buffer pH is within the expected range.", "tags": ["measurement", "buffer"],
        "_links": [("PH-001", "previous")],
    },
    {
        "identifier": "PH-007", "title": "Titration of 0.1 M acetic acid with 0.1 M NaOH", "performed_at": "2026-09-08T10:00:00Z", "outcome": "success",
        "objective": "Determine the equivalence point and estimate the pKa of acetic acid by potentiometric titration.",
        "reagents": [{"name": "Acetic acid", "lot_no": "AA-552", "quantity": 25, "unit": "mL"}, {"name": "Sodium hydroxide", "lot_no": "NH-118", "quantity": 25, "unit": "mL"}],
        "equipment": METER + [{"name": "Burette", "id": "BU-3"}],
        "parameters": [{"name": "Equivalence point volume", "value": 25.1, "unit": "mL"}, {"name": "pH at equivalence point", "value": 8.72, "unit": ""},
                       {"name": "pH at half-equivalence", "value": 4.76, "unit": ""}, {"name": "Temperature", "value": 25.0, "unit": "C"}],
        "conditions": {"titrant": "0.1 M NaOH", "stirring": "400 rpm"}, "observations": "Sharp pH jump between 24 and 26 mL of titrant.",
        "results": "Equivalence at 25.1 mL, pH 8.72. pH at half-equivalence 4.76, which equals the pKa of acetic acid.", "conclusions": "Measured pKa 4.76 agrees with the literature value.", "tags": ["titration"],
        "_links": [("PH-002", "previous")],
    },
    {
        "identifier": "PH-008", "title": "Temperature dependence of Tris buffer pH", "performed_at": "2026-09-10T14:00:00Z", "outcome": "success",
        "objective": "Show how the pH of 0.05 M Tris buffer changes with temperature.",
        "reagents": [{"name": "Tris base", "lot_no": "TR-901", "quantity": 6.05, "unit": "g"}, {"name": "Hydrochloric acid", "lot_no": "HC-212", "quantity": 4, "unit": "mL"}],
        "equipment": METER + [{"name": "Water bath", "id": "WB-1"}],
        "parameters": [{"name": "pH at 20 C", "value": 8.15, "unit": ""}, {"name": "pH at 25 C", "value": 8.00, "unit": ""}, {"name": "pH at 37 C", "value": 7.64, "unit": ""}],
        "conditions": {"buffer": "0.05 M Tris-HCl", "temperature compensation": "off"}, "observations": "Each reading taken after 5 minutes of thermal equilibration.",
        "results": "pH fell from 8.15 at 20 C to 7.64 at 37 C, about 0.03 pH units per degree Celsius.", "conclusions": "Always report the pH of Tris buffers together with the temperature.", "tags": ["measurement", "temperature"],
    },
]


async def main(owner: str, editor: str) -> None:
    async with session_maker()() as s:
        users = {u.username: u for u in (await s.execute(select(User))).scalars()}
    if owner not in users:
        raise SystemExit(f"user '{owner}' not found")
    hdr = {"Authorization": "Bearer " + make_token(users[owner])}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://seed", headers=hdr) as c:
        existing = (await c.get("/api/projects")).json()
        if any(p["name"] == NAME for p in existing):
            print(f"'{NAME}' already exists - nothing to do")
            return
        r = await c.post("/api/projects", json={
            "name": NAME, "domain": "analytical chemistry", "tags": ["pH", "calibration", "validation"],
            "description": "Sample project: validation of the benchtop pH meter and electrode, with calibration runs, buffer measurements and a titration.",
            "objectives": "Show that the pH meter meets the SOP acceptance criteria (slope 95-105 %, offset within 30 mV, response under 30 s) and document corrective actions."})
        r.raise_for_status()
        pid = r.json()["id"]
        if editor in users and editor != owner:
            (await c.post(f"/api/projects/{pid}/members", json={"username": editor, "role": "editor"})).raise_for_status()
        d = await c.post(f"/api/projects/{pid}/documents", files={"file": ("ph-metry-sop.md", SOP.read_bytes())},
                         data={"title": "pH metry SOP", "category": "SOP"})
        d.raise_for_status()
        doc_id = d.json()["id"]
        ids: dict[str, str] = {}
        for e in EXPERIMENTS:
            body = {k: v for k, v in e.items() if not k.startswith("_")}
            body["procedure_refs"] = [{"document_id": doc_id, "text": "pH metry SOP"}]
            body["attachments"] = [doc_id]
            body["links"] = [{"experiment_id": ids[t], "relation": rel} for t, rel in e.get("_links", []) if t in ids]
            body.setdefault("conclusions", None)
            x = await c.post(f"/api/projects/{pid}/experiments", json=body)
            if x.status_code != 201:
                raise SystemExit(f"{e['identifier']} failed: {x.status_code} {x.text}")
            ids[e["identifier"]] = x.json()["id"]
        # chain the calibration history with previous/next links (PH-002 follows PH-001, ...)
        order = ["PH-001", "PH-002", "PH-003", "PH-004", "PH-005"]
        for a, b in zip(order, order[1:]):
            cur = (await c.get(f"/api/projects/{pid}/experiments/{ids[b]}")).json()
            (await c.patch(f"/api/projects/{pid}/experiments/{ids[b]}", json={
                "expected_version": cur["version"], "change_note": "linked to the previous calibration",
                "links": cur["links"] + [{"experiment_id": ids[a], "relation": "previous"}]})).raise_for_status()
    print(f"created '{NAME}' ({pid}): {len(EXPERIMENTS)} experiments + 'pH metry SOP' document; owner={owner}, editor={editor}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", default="scientist")
    ap.add_argument("--editor", default="senior")
    a = ap.parse_args()
    asyncio.run(main(a.owner, a.editor))
