"""12.2 Experimental records and project documents."""
import asyncio

import psycopg
import pytest

from tests.conftest import _test_url, auth
from tests.util import (
    ROLE_USERNAMES, add_member, make_csv, make_docx, make_pdf, mk_experiment, mk_project, upload, upload_text, uid,  # noqa: F401
)


def chunks_of(source_id: str) -> int:
    with psycopg.connect(_test_url) as c:
        return c.execute("SELECT count(*) FROM project_chunks WHERE source_id = %s", (source_id,)).fetchone()[0]


async def test_experiment_create_retrieve_and_history(client, tokens):
    sci = tokens["scientist"]
    p = await mk_project(client, sci)
    pid = p["id"]
    base = f"/api/projects/{pid}/experiments"
    e = await mk_experiment(
        client, sci, pid, "EXP-001", title="Buffer prep", objective="Check pH drift", performed_at="2026-03-01T10:00:00Z",
        reagents=[{"name": "Tris", "lot_no": "L1", "quantity": 12.1, "unit": "g"}], equipment=[{"name": "pH meter", "id": "PH-2"}],
        parameters=[{"name": "pH", "value": 7.4, "unit": ""}, {"name": "Temperature", "value": 25, "unit": "C"},
                    {"name": "Colour", "text_value": "clear"}],
        conditions={"stirring": "400 rpm"}, custom_fields={"cell_line": "HEK293"}, tags=["buffer"], outcome="success",
        observations="Solution clear.", results="pH stable.")
    assert e["version"] == 1 and e["created_by_name"] and e["parameters"][0]["value"] == 7.4
    got = (await client.get(f"{base}/{e['id']}", headers=auth(sci))).json()
    assert got["custom_fields"] == {"cell_line": "HEK293"} and got["equipment"][0]["name"] == "pH meter"

    # validation
    assert (await client.post(base, headers=auth(sci), json={"identifier": "EXP-001", "title": "dup"})).status_code == 409
    assert (await client.post(base, headers=auth(sci), json={"identifier": "bad/../id\n", "title": "x"})).status_code == 422
    assert (await client.post(base, headers=auth(sci), json={"identifier": "X", "title": "x", "parameters": [{"name": "pH"}]})).status_code == 422
    assert (await client.post(base, headers=auth(sci), json={"identifier": "X", "title": "x", "outcome": "great"})).status_code == 422

    # edits need the version you saw, and never overwrite history
    stale = await client.patch(f"{base}/{e['id']}", headers=auth(sci), json={"title": "x"})
    assert stale.status_code == 422                                   # expected_version is mandatory
    r = await client.patch(f"{base}/{e['id']}", headers=auth(sci),
                           json={"expected_version": 1, "results": "pH drifted to 7.9", "change_note": "re-measured",
                                 "parameters": [{"name": "pH", "value": 7.9}, {"name": "Temperature", "value": 25, "unit": "C"}]})
    assert r.status_code == 200 and r.json()["version"] == 2
    again = await client.patch(f"{base}/{e['id']}", headers=auth(sci), json={"expected_version": 1, "results": "lost update?"})
    assert again.status_code == 409 and "changed" in again.json()["detail"]
    # a no-op edit does not create a version
    assert (await client.patch(f"{base}/{e['id']}", headers=auth(sci), json={"expected_version": 2, "results": "pH drifted to 7.9"})).json()["version"] == 2

    versions = (await client.get(f"{base}/{e['id']}/versions", headers=auth(sci))).json()
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[0]["change_note"] == "re-measured" and set(versions[0]["changed_fields"]) == {"results", "parameters"}
    assert versions[0]["changed_by_name"]
    v1 = (await client.get(f"{base}/{e['id']}/versions/1", headers=auth(sci))).json()["snapshot"]
    assert v1["results"] == "pH stable." and v1["parameters"][0]["value"] == 7.4      # the original survived

    # the database itself refuses to rewrite or delete history
    with psycopg.connect(_test_url, autocommit=True) as c:
        for sql in ("UPDATE experiment_versions SET change_note = 'tampered'", "DELETE FROM experiment_versions"):
            with pytest.raises(psycopg.errors.RaiseException):
                c.execute(sql)

    # compare against another run
    e2 = await mk_experiment(client, sci, pid, "EXP-002", parameters=[{"name": "pH", "value": 7.0}, {"name": "Temperature", "value": 30, "unit": "K"}],
                             reagents=[{"name": "Tris"}, {"name": "NaCl"}])
    cmp_ = (await client.get(f"{base}/{e['id']}/compare?with={e2['id']}", headers=auth(sci))).json()
    rows = {r["parameter"]: r for r in cmp_["parameters"]}
    assert rows["pH"]["a"] == 7.9 and rows["pH"]["b"] == 7.0 and round(rows["pH"]["delta"], 2) == -0.9
    assert "units differ" in rows["Temperature"]["note"] and cmp_["reagents"]["only_b"] == ["NaCl"]

    # links stay inside the project
    ok = await client.patch(f"{base}/{e2['id']}", headers=auth(sci), json={"expected_version": 1, "links": [{"experiment_id": e["id"], "relation": "previous"}]})
    assert ok.status_code == 200
    assert (await client.patch(f"{base}/{e2['id']}", headers=auth(sci),
                               json={"expected_version": 2, "links": [{"experiment_id": e2["id"], "relation": "next"}]})).status_code == 422


async def test_search_filter_sort_paginate(client, tokens):
    sci = tokens["scientist"]
    pid = (await mk_project(client, sci))["id"]
    base = f"/api/projects/{pid}/experiments"
    for i in range(7):
        await mk_experiment(client, sci, pid, f"S-{i:02d}", title=f"Titration {i}" if i % 2 else f"Chromatography {i}",
                            performed_at=f"2026-02-{i + 1:02d}T09:00:00Z", outcome="failure" if i == 3 else "success",
                            tags=["wet"] if i < 3 else ["dry"], parameters=[{"name": "Flow", "value": float(i), "unit": "mL/min"}],
                            observations="precipitate formed" if i == 5 else None)
    page = (await client.get(f"{base}?limit=3&offset=0&sort=identifier&order=asc", headers=auth(sci))).json()
    assert page["total"] == 7 and [x["identifier"] for x in page["items"]] == ["S-00", "S-01", "S-02"]
    page2 = (await client.get(f"{base}?limit=3&offset=3&sort=identifier&order=asc", headers=auth(sci))).json()
    assert [x["identifier"] for x in page2["items"]] == ["S-03", "S-04", "S-05"]
    assert (await client.get(f"{base}?outcome=failure", headers=auth(sci))).json()["total"] == 1
    assert (await client.get(f"{base}?tag=wet", headers=auth(sci))).json()["total"] == 3
    assert (await client.get(f"{base}?q=precipitate", headers=auth(sci))).json()["items"][0]["identifier"] == "S-05"
    assert (await client.get(f"{base}?q=titration", headers=auth(sci))).json()["total"] == 3
    assert (await client.get(f"{base}?parameter=flow", headers=auth(sci))).json()["total"] == 7
    assert (await client.get(f"{base}?date_from=2026-02-05T00:00:00Z&date_to=2026-02-06T23:59:00Z", headers=auth(sci))).json()["total"] == 2
    newest = (await client.get(f"{base}?sort=performed_at&order=desc&limit=1", headers=auth(sci))).json()["items"][0]
    assert newest["identifier"] == "S-06"
    assert (await client.get(f"{base}?limit=1000", headers=auth(sci))).status_code == 422
    cat = (await client.get(f"{base}/parameters", headers=auth(sci))).json()
    assert cat == [{"name": "Flow", "unit": "mL/min", "n": 7}]


async def test_analysis_flags_unusual_values_and_never_claims_a_cause(client, tokens):
    sci = tokens["scientist"]
    pid = (await mk_project(client, sci))["id"]
    for i, t in enumerate([36.5, 37.0, 37.2, 36.8]):
        await mk_experiment(client, sci, pid, f"OK-{i}", outcome="success", parameters=[{"name": "Temperature", "value": t, "unit": "C"},
                                                                                         {"name": "pH", "value": 7.2, "unit": ""}],
                            reagents=[{"name": "Buffer A"}])
    bad = await mk_experiment(client, sci, pid, "BAD-1", outcome="failure", reagents=[{"name": "Buffer A"}],
                              parameters=[{"name": "Temperature", "value": 45, "unit": "C"}])
    a = (await client.get(f"/api/projects/{pid}/experiments/{bad['id']}/analysis", headers=auth(sci))).json()
    temp = next(p for p in a["parameters"] if p["parameter"] == "temperature")
    assert temp["history_count"] == 4 and any("outside the range" in f for f in temp["flags"])
    assert a["missing_parameters"] == ["ph"]                       # recorded in the comparable runs, absent here -> ask the user
    assert any("temperature" in h and "correlation" in h for h in a["hypotheses"])
    assert "Correlation" in a["caution"] and a["similar_experiments"][0]["similarity"] > 0
    assert all("cause" not in o.lower() for o in a["observed"])


async def test_void_keeps_history_but_leaves_search_and_index(client, tokens):
    sci = tokens["scientist"]
    pid = (await mk_project(client, sci))["id"]
    e = await mk_experiment(client, sci, pid, "V-1", observations="unique marker zirconium")
    assert chunks_of(e["id"]) >= 1
    assert (await client.delete(f"/api/projects/{pid}/experiments/{e['id']}?reason=x", headers=auth(sci))).status_code == 422
    r = await client.delete(f"/api/projects/{pid}/experiments/{e['id']}?reason=entered%20in%20error", headers=auth(sci))
    assert r.status_code == 200 and r.json()["voided_at"]
    assert chunks_of(e["id"]) == 0
    assert (await client.get(f"/api/projects/{pid}/experiments", headers=auth(sci))).json()["total"] == 0
    assert (await client.get(f"/api/projects/{pid}/experiments?include_voided=true", headers=auth(sci))).json()["total"] == 1
    versions = (await client.get(f"/api/projects/{pid}/experiments/{e['id']}/versions", headers=auth(sci))).json()
    assert [v["version"] for v in versions] == [2, 1] and "voided" in versions[0]["change_note"]
    assert (await client.patch(f"/api/projects/{pid}/experiments/{e['id']}", headers=auth(sci),
                               json={"expected_version": 2, "title": "revive"})).status_code == 409


async def test_concurrent_edits_cannot_silently_overwrite(client, tokens):
    sci = tokens["scientist"]
    pid = (await mk_project(client, sci))["id"]
    e = await mk_experiment(client, sci, pid, "C-1")
    res = await asyncio.gather(*[client.patch(f"/api/projects/{pid}/experiments/{e['id']}", headers=auth(sci),
                                              json={"expected_version": 1, "results": f"writer {i}"}) for i in range(6)])
    codes = sorted(r.status_code for r in res)
    assert codes == [200] + [409] * 5, codes
    final = (await client.get(f"/api/projects/{pid}/experiments/{e['id']}", headers=auth(sci))).json()
    assert final["version"] == 2


# ------------------------------------------------------------------ documents
async def test_upload_formats_and_extracted_content(client, tokens):
    sci = tokens["scientist"]
    pid = (await mk_project(client, sci))["id"]
    base = f"/api/projects/{pid}/documents"

    txt = await upload_text(client, sci, pid, "Plain note", "1. Preparation\n\nMix the buffer for ten minutes.\n\n2. Storage\n\nStore at 4 C.")
    assert txt["file_type"] == "txt" and txt["chunks"] >= 1 and txt["uploaded_by_name"]
    content = (await client.get(f"{base}/{txt['id']}/content", headers=auth(sci))).json()
    assert "Mix the buffer" in content["pages"][0]["text"] and content["pages"][0]["page"] is None

    pdf = await upload(client, sci, pid, "report.pdf", make_pdf(["Page one talks about calibration of the balance.",
                                                              "Page two describes the incubation temperature of 37 C."]))
    assert pdf.status_code == 201, pdf.text
    pj = pdf.json()
    assert pj["file_type"] == "pdf" and pj["page_count"] == 2
    pages = (await client.get(f"{base}/{pj['id']}/content", headers=auth(sci))).json()["pages"]
    assert [p["page"] for p in pages] == [1, 2] and "incubation" in pages[1]["text"]
    with psycopg.connect(_test_url) as c:       # page numbers are preserved on the retrieval chunks too
        rows = c.execute("SELECT page FROM project_chunks WHERE source_id=%s ORDER BY page", (pj["id"],)).fetchall()
    assert [r[0] for r in rows] == [1, 2]

    dx = await upload(client, sci, pid, "sop.docx", make_docx(["Scope", "This SOP covers centrifuge operation at 4000 rpm."]))
    assert dx.status_code == 201 and dx.json()["file_type"] == "docx"
    cs = await upload(client, sci, pid, "data.csv", make_csv([["sample", "od600"], ["A", "0.42"], ["B", "0.77"]]))
    assert cs.status_code == 201
    csv_text = (await client.get(f"{base}/{cs.json()['id']}/content", headers=auth(sci))).json()["pages"][0]["text"]
    assert "sample: A" in csv_text and "od600: 0.77" in csv_text

    # list + search by extracted text + filters + pagination
    assert (await client.get(f"{base}?q=centrifuge", headers=auth(sci))).json()["total"] == 1
    assert (await client.get(f"{base}?file_type=pdf", headers=auth(sci))).json()["total"] == 1
    assert (await client.get(f"{base}?limit=2", headers=auth(sci))).json()["total"] == 4
    # download returns the original bytes
    dl = await client.get(f"{base}/{txt['id']}/file", headers=auth(sci))
    assert dl.status_code == 200 and b"Mix the buffer" in dl.content and dl.headers["x-content-type-options"] == "nosniff"


async def test_unsafe_or_broken_uploads_are_rejected_cleanly(client, tokens):
    sci = tokens["scientist"]
    pid = (await mk_project(client, sci))["id"]
    cases = {
        "exe": ("tool.exe", b"MZ\x90\x00 not a document"),
        "no extension": ("README", b"hello hello hello"),
        "pdf extension, text content": ("fake.pdf", b"this is not a pdf at all"),
        "docx extension, text content": ("fake.docx", b"plain text pretending to be word"),
        "empty": ("empty.txt", b""),
        "whitespace only": ("blank.txt", b"   \n\n  "),
        "binary as txt": ("bin.txt", b"\x00\x01\x02\x03" * 100),
        "truncated pdf": ("cut.pdf", b"%PDF-1.7\n1 0 obj\n<<"),
        "zip not docx": ("x.docx", b"PK\x03\x04" + b"\x00" * 50),
        "csv header only": ("h.csv", b"a,b,c"),
    }
    for label, (name, data) in cases.items():
        r = await upload(client, sci, pid, name, data)
        assert r.status_code == 422, (label, r.status_code, r.text)
        assert "Traceback" not in r.text and r.json()["detail"]
    big = await upload(client, sci, pid, "big.txt", b"a" * (11 * 1024 * 1024))
    assert big.status_code == 413
    # hostile filename never reaches the filesystem
    ok = await upload(client, sci, pid, "../../etc/passwd.txt", b"harmless text content for the test file")
    assert ok.status_code == 201 and "/" not in ok.json()["filename"] and ".." not in ok.json()["filename"].replace("passwd.txt", "")
    with psycopg.connect(_test_url) as c:
        key = c.execute("SELECT storage_key FROM project_documents WHERE id=%s", (ok.json()["id"],)).fetchone()[0]
    assert len(key) == 32 and key.isalnum()
    # same bytes twice -> conflict, not a second copy
    assert (await upload(client, sci, pid, "again.txt", b"harmless text content for the test file")).status_code == 409
    # a scanned/odd PDF with partially empty pages still uploads, with a warning
    mixed = await upload(client, sci, pid, "mixed.pdf", make_pdf(["Readable first page about reagents and storage conditions.", ""]))
    assert mixed.status_code == 201 and any("No extractable text" in w for w in mixed.json()["warnings"])


async def test_replaced_and_deleted_documents_leave_the_retrieval_index(client, tokens, uid):
    sci, ana = tokens["scientist"], tokens["lab_analyst"]
    pid = (await mk_project(client, sci))["id"]
    await add_member(client, sci, pid, ROLE_USERNAMES["lab_analyst"], "editor")
    base = f"/api/projects/{pid}/documents"
    v1 = await upload_text(client, sci, pid, "Method", "Incubate the culture at 30 degrees overnight for the pilot run.")
    old_chunks = chunks_of(v1["id"])
    assert old_chunks >= 1

    # an editor who is not the uploader or owner cannot replace/delete it
    assert (await client.post(f"{base}/{v1['id']}/replace", headers=auth(ana), files={"file": ("m2.txt", b"x y z content here!!")})).status_code == 403
    assert (await client.delete(f"{base}/{v1['id']}", headers=auth(ana))).status_code == 403

    r = await client.post(f"{base}/{v1['id']}/replace", headers=auth(sci),
                          files={"file": ("method2.txt", b"Incubate the culture at 37 degrees for twenty four hours in the final protocol.")})
    assert r.status_code == 201 and r.json()["version"] == 2 and r.json()["lineage_id"] == v1["lineage_id"]
    v2 = r.json()
    assert chunks_of(v1["id"]) == 0 and chunks_of(v2["id"]) >= 1          # old version is gone from the index at once
    assert (await client.get(f"{base}/{v1['id']}", headers=auth(sci))).json()["status"] == "superseded"
    assert [d["version"] for d in (await client.get(f"{base}/{v2['id']}/versions", headers=auth(sci))).json()] == [2, 1]
    listed = (await client.get(base, headers=auth(sci))).json()["items"]
    assert [d["id"] for d in listed] == [v2["id"]]

    assert (await client.delete(f"{base}/{v2['id']}", headers=auth(sci))).status_code == 204
    assert chunks_of(v2["id"]) == 0 and chunks_of(v1["id"]) == 0
    assert (await client.get(f"{base}/{v2['id']}", headers=auth(sci))).status_code == 404
    assert (await client.get(f"{base}/{v2['id']}/content", headers=auth(sci))).status_code == 404
    assert (await client.get(f"{base}/{v2['id']}/file", headers=auth(sci))).status_code == 404
    assert (await client.get(f"{base}/{v1['id']}/file", headers=auth(sci))).status_code == 404       # whole lineage deleted
    assert (await client.get(base, headers=auth(sci))).json()["total"] == 0
