"""12.5 Reagent inventory and the lab-assistant request workflow."""
import asyncio
import uuid
from datetime import date, timedelta

import psycopg
import pytest

from tests.conftest import _test_url, auth
from tests.util import mk_project, uid  # noqa: F401

FUTURE = (date.today() + timedelta(days=365)).isoformat()
PAST = (date.today() - timedelta(days=3)).isoformat()


async def mk_lot(client, ana, name=None, qty=50, expiry=FUTURE, unit="g", capacity=100, lot_no=None, reorder=None):
    name = name or f"Reagent {uuid.uuid4().hex[:6]}"
    r = await client.post("/api/inventory/lots", headers=auth(ana), json={
        "reagent_name": name, "unit": unit, "lot_no": lot_no or f"L-{uuid.uuid4().hex[:5]}", "capacity": capacity,
        "quantity_available": qty, "expiry_date": expiry, "location": "Shelf A"})
    assert r.status_code == 201, r.text
    lot = r.json()
    if reorder is not None:
        with psycopg.connect(_test_url, autocommit=True) as c:
            c.execute("UPDATE reagents SET reorder_level=%s WHERE id=%s", (reorder, lot["reagent_id"]))
    return lot


async def submit(client, token, reagent_id=None, **kw):
    body = {"quantity": 5, "reason": "needed for assay", **kw}
    if reagent_id:
        body["reagent_id"] = reagent_id
    return await client.post("/api/requests", headers=auth(token), json=body)


async def move(client, token, rid, to, comment=None, **kw):
    return await client.post(f"/api/requests/{rid}/transition", headers=auth(token), json={"to_status": to, "comment": comment, **kw})


def db(sql, *args):
    with psycopg.connect(_test_url) as c:
        return c.execute(sql, args).fetchall()


def summary(rows, reagent_id):
    return next(r for r in rows if r["reagent_id"] == reagent_id)


# ------------------------------------------------------------------ submitting
async def test_any_authenticated_user_can_submit_in_every_situation(client, tokens):
    ana = tokens["lab_analyst"]
    ok_lot = await mk_lot(client, ana, qty=50)
    expired = await mk_lot(client, ana, qty=50, expiry=PAST)
    empty = await mk_lot(client, ana, qty=0)
    for role in ("scientist", "senior_analyst", "lab_analyst"):
        t = tokens[role]
        # in stock / expired / out of stock / more than available / not in the register at all
        for lot, qty in ((ok_lot, 5), (expired, 5), (empty, 5), (ok_lot, 500)):
            r = await submit(client, t, lot["reagent_id"], quantity=qty)
            assert r.status_code == 201, (role, r.text)
            body = r.json()
            assert body["status"] == "submitted" and body["urgency"] == "normal" and body["unit"] == "g" and body["in_register"] is True
        new = await submit(client, t, reagent_name="Brand-new buffer", unit="mL", quantity=250, details="not stocked yet", urgency="high",
                           experiment_ref="EXP-77")
        assert new.status_code == 201 and new.json()["in_register"] is False and new.json()["reagent_name"] == "Brand-new buffer"
    # the register shows the reagent is expired / out of stock, and the user could still ask
    rows = (await client.get("/api/inventory/reagents/summary", headers=auth(tokens["scientist"]))).json()
    assert summary(rows, expired["reagent_id"])["status"] in ("expired", "awaiting_restock")
    assert summary(rows, empty["reagent_id"])["status"] in ("out_of_stock", "awaiting_restock")
    # admins have no lab role
    assert (await submit(client, tokens["admin"], ok_lot["reagent_id"])).status_code == 403


async def test_request_validation(client, tokens):
    sci, ana = tokens["scientist"], tokens["lab_analyst"]
    lot = await mk_lot(client, ana)
    rid = lot["reagent_id"]
    bad = [
        dict(reagent_id=rid, quantity=-1), dict(reagent_id=rid, quantity=0), dict(reagent_id=rid, quantity=1e12),
        dict(reagent_id=rid, reason=""), dict(reagent_id=rid, reason="ab"), dict(reagent_id=rid, unit="parsecs"),
        dict(reagent_id=rid, unit="mL"),                                                  # volume for a mass reagent
        dict(reagent_id=rid, urgency="asap"), dict(reagent_id=str(uuid.uuid4())),
        dict(reagent_name="Missing unit reagent"), dict(reagent_name="  ", unit="g"), {},
        dict(reagent_id=rid, project_id=str(uuid.uuid4())),                               # project the user does not belong to
    ]
    for body in bad:
        base = {"quantity": 2, "reason": "valid reason"}
        base.update(body)
        if "reason" in body and body["reason"] is None:
            base.pop("reason")
        r = await client.post("/api/requests", headers=auth(sci), json=base)
        assert r.status_code in (404, 422), (body, r.status_code, r.text)
    # a project reference works for members only
    p = await mk_project(client, sci)
    ok = await submit(client, sci, rid, project_id=p["id"], quantity=1)
    assert ok.status_code == 201 and ok.json()["project_name"] == p["name"]
    other = await submit(client, tokens["senior_analyst"], rid, project_id=p["id"])
    assert other.status_code == 422
    # compatible units are accepted and normalised
    assert (await submit(client, sci, rid, quantity=500, unit="mg")).json()["unit"] == "mg"
    assert (await submit(client, sci, rid, quantity=1, purpose="legacy field name")).status_code == 201


async def test_users_only_see_and_touch_their_own_requests(client, tokens):
    sci, sen, ana = tokens["scientist"], tokens["senior_analyst"], tokens["lab_analyst"]
    lot = await mk_lot(client, ana)
    mine = (await submit(client, sci, lot["reagent_id"])).json()
    theirs = (await submit(client, sen, lot["reagent_id"])).json()
    ids = [r["id"] for r in (await client.get("/api/requests/mine", headers=auth(sci))).json()]
    assert mine["id"] in ids and theirs["id"] not in ids
    assert (await client.get(f"/api/requests/{theirs['id']}", headers=auth(sci))).status_code == 404
    assert (await client.get(f"/api/requests/{mine['id']}", headers=auth(sci))).status_code == 200
    # direct API calls against someone else's request: nothing works
    for method, path, body in (("POST", f"/api/requests/{theirs['id']}/respond", {"comment": "hi"}),
                               ("POST", f"/api/requests/{theirs['id']}/transition", {"to_status": "approved"}),
                               ("POST", f"/api/requests/{theirs['id']}/fulfil", {"note": "done", "lot_id": lot["lot_id"]}),
                               ("POST", f"/api/requests/{theirs['id']}/issue", {"lot_id": lot["lot_id"]}),
                               ("POST", f"/api/requests/{theirs['id']}/reject", {"reason": "mine now"}),
                               ("POST", f"/api/requests/{theirs['id']}/comment", {"comment": "x"})):
        r = await client.request(method, path, headers=auth(sci), json=body)
        assert r.status_code in (403, 404), (path, r.status_code)
    # even on their own request a requester cannot approve it
    assert (await move(client, sci, mine["id"], "approved")).status_code == 403
    assert (await client.post(f"/api/requests/{mine['id']}/fulfil", headers=auth(sci), json={"note": "mine", "lot_id": lot["lot_id"]})).status_code == 403
    assert (await client.get("/api/requests", headers=auth(sci))).status_code == 403          # manage list is for lab assistants
    assert (await client.get(f"/api/requests/{theirs['id']}", headers=auth(ana))).status_code == 200
    assert db("SELECT status FROM reagent_requests WHERE id=%s", theirs["id"])[0][0] == "submitted"


# ------------------------------------------------------------------ lifecycle
async def test_lifecycle_history_notifications_and_approval_is_not_fulfilment(client, tokens, uid):
    sci, ana = tokens["scientist"], tokens["lab_analyst"]
    lot = await mk_lot(client, ana, qty=20)
    req = (await submit(client, sci, lot["reagent_id"], quantity=5)).json()
    rid = req["id"]
    assert any("New reagent request" in n["message"] for n in (await client.get("/api/notifications", headers=auth(ana))).json())

    assert (await move(client, ana, rid, "under_review")).status_code == 200
    # comments are mandatory where the requester needs an explanation
    assert (await move(client, ana, rid, "needs_clarification")).status_code == 422
    assert (await move(client, ana, rid, "needs_clarification", "Which assay and what concentration?")).status_code == 200
    assert (await client.post(f"/api/requests/{rid}/respond", headers=auth(ana), json={"comment": "x"})).status_code == 404  # not the requester
    assert (await client.post(f"/api/requests/{rid}/respond", headers=auth(sci), json={"comment": "ELISA, 10 mM"})).json()["status"] == "under_review"
    assert (await client.post(f"/api/requests/{rid}/respond", headers=auth(sci), json={"comment": "again"})).status_code == 409

    # APPROVAL: status changes, stock does not
    before = db("SELECT quantity_available, reserved_quantity FROM reagent_lots WHERE id=%s", lot["lot_id"])[0]
    appr = await move(client, ana, rid, "approved", "OK for the ELISA")
    assert appr.status_code == 200 and appr.json()["status"] == "approved"
    assert db("SELECT quantity_available, reserved_quantity FROM reagent_lots WHERE id=%s", lot["lot_id"])[0] == before
    assert db("SELECT count(*) FROM inventory_transactions WHERE lot_id=%s AND type='issued'", lot["lot_id"])[0][0] == 0
    notes = [n["message"] for n in (await client.get("/api/notifications", headers=auth(sci))).json()]
    assert any("approved" in m and "does NOT mean" in m for m in notes)
    # approved is not fulfilled; fulfilling is its own step
    assert (await client.get(f"/api/requests/{rid}", headers=auth(sci))).json()["status"] == "approved"

    # illegal transitions are refused by the server
    assert (await move(client, ana, rid, "submitted")).status_code == 409
    assert (await move(client, ana, rid, "under_review")).status_code == 409
    assert (await move(client, ana, rid, "fulfilled")).status_code == 422                 # only via /fulfil
    assert (await move(client, ana, rid, "teleported")).status_code == 422
    assert (await client.post(f"/api/requests/{rid}/fulfil", headers=auth(ana), json={"note": "nope"})).status_code == 422   # needs a lot

    ful = await client.post(f"/api/requests/{rid}/fulfil", headers=auth(ana),
                            json={"note": "Handed over at the bench", "lot_id": lot["lot_id"], "issue_from_lot": True})
    assert ful.status_code == 200 and ful.json()["status"] == "fulfilled" and ful.json()["fulfilled_at"]
    assert float(db("SELECT quantity_available FROM reagent_lots WHERE id=%s", lot["lot_id"])[0][0]) == 15
    assert db("SELECT count(*) FROM inventory_transactions WHERE lot_id=%s AND type='issued'", lot["lot_id"])[0][0] == 1
    assert (await move(client, ana, rid, "rejected", "too late")).status_code == 409        # terminal
    assert (await client.post(f"/api/requests/{rid}/fulfil", headers=auth(ana), json={"note": "twice", "lot_id": lot["lot_id"], "issue_from_lot": True})).status_code == 409
    assert float(db("SELECT quantity_available FROM reagent_lots WHERE id=%s", lot["lot_id"])[0][0]) == 15      # not issued twice

    # complete, ordered history with actor, timestamp, comment
    detail = (await client.get(f"/api/requests/{rid}", headers=auth(sci))).json()
    steps = [(e["from_status"], e["to_status"]) for e in detail["events"] if e["kind"] == "status"]
    assert steps == [(None, "submitted"), ("submitted", "under_review"), ("under_review", "needs_clarification"),
                     ("needs_clarification", "under_review"), ("under_review", "approved"), ("approved", "fulfilled")]
    assert all(e["actor_name"] and e["created_at"] for e in detail["events"])
    assert any(e["kind"] == "comment" and e["comment"] == "ELISA, 10 mM" and e["actor_role"] == "scientist" for e in detail["events"])
    status_events = [e for e in detail["events"] if e["kind"] == "status"]
    assert status_events[4]["comment"] == "OK for the ELISA" and status_events[4]["actor_role"] == "lab_analyst"
    assert detail["allowed_next"] == []
    # every state change reached the requester; audit trail has the decisions
    kinds = {n["kind"] for n in (await client.get("/api/notifications", headers=auth(sci))).json()}
    assert {"request_under_review", "request_needs_clarification", "request_approved", "request_fulfilled"} <= kinds
    audit_actions = {r[0] for r in db("SELECT action FROM audit_log WHERE details->>'from' IS NOT NULL OR target=%s", rid)}
    assert {"request_approved", "request_fulfilled", "request_needs_clarification"} <= audit_actions
    # the timeline itself is tamper-proof
    with psycopg.connect(_test_url, autocommit=True) as c:
        with pytest.raises(psycopg.errors.RaiseException):
            c.execute("UPDATE request_events SET comment='edited'")
    # reject path needs a reason and tells the user
    r2 = (await submit(client, sci, lot["reagent_id"])).json()
    assert (await move(client, ana, r2["id"], "rejected")).status_code == 422
    rej = await move(client, ana, r2["id"], "rejected", "Duplicate of an existing order")
    assert rej.json()["reject_reason"] == "Duplicate of an existing order"
    assert any("rejected" in n["message"] for n in (await client.get("/api/notifications", headers=auth(sci))).json())


async def test_approved_without_stock_waits_for_real_restock(client, tokens):
    sci, ana = tokens["scientist"], tokens["lab_analyst"]
    lot = await mk_lot(client, ana, qty=0)
    rid_reagent = lot["reagent_id"]
    req = (await submit(client, sci, rid_reagent, quantity=10)).json()
    assert (await move(client, ana, req["id"], "approved", "will reorder")).status_code == 200
    # approval did not create stock, and the register says so
    rows = (await client.get("/api/inventory/reagents/summary", headers=auth(sci))).json()
    s = summary(rows, rid_reagent)
    assert s["status"] == "awaiting_restock" and s["usable_quantity"] == 0 and s["physical_quantity"] == 0
    # the request cannot be fulfilled while there is nothing to hand over - neither by issuing nor by claiming
    assert (await client.post(f"/api/requests/{req['id']}/fulfil", headers=auth(ana),
                              json={"note": "issuing", "lot_id": lot["lot_id"], "issue_from_lot": True})).status_code == 409
    assert (await client.post(f"/api/requests/{req['id']}/fulfil", headers=auth(ana),
                              json={"note": "just mark it", "lot_id": lot["lot_id"]})).status_code == 409
    assert (await client.get(f"/api/requests/{req['id']}", headers=auth(sci))).json()["status"] == "approved"
    my = next(r for r in (await client.get("/api/requests/mine", headers=auth(sci))).json() if r["id"] == req["id"])
    assert my["reagent_availability"] == "awaiting_restock"

    # stock actually arrives -> requester is told, register and request views update, request can then be fulfilled
    recv = await client.post(f"/api/inventory/lots/{lot['lot_id']}/receive", headers=auth(ana), json={"quantity": 40, "reason": "delivery PO-1234"})
    assert recv.status_code == 200 and recv.json()["quantity_available"] == 40 and recv.json()["usable_quantity"] == 40
    assert any(n["kind"] == "reagent_available" for n in (await client.get("/api/notifications", headers=auth(sci))).json())
    my = next(r for r in (await client.get("/api/requests/mine", headers=auth(sci))).json() if r["id"] == req["id"])
    assert my["reagent_availability"] in ("available", "low") and my["status"] == "approved"
    ful = await client.post(f"/api/requests/{req['id']}/fulfil", headers=auth(ana),
                            json={"note": "restock received and issued", "lot_id": lot["lot_id"], "issue_from_lot": True})
    assert ful.status_code == 200 and ful.json()["status"] == "fulfilled"
    assert float(db("SELECT quantity_available FROM reagent_lots WHERE id=%s", lot["lot_id"])[0][0]) == 30
    # a request for a reagent that is not in the register is fulfilled by note (there is no lot to check)
    new = (await submit(client, sci, reagent_name="Exotic enzyme", unit="mL", quantity=2)).json()
    await move(client, ana, new["id"], "approved")
    assert (await client.post(f"/api/requests/{new['id']}/fulfil", headers=auth(ana), json={"note": "Ordered and received, stored in -20 freezer"})).status_code == 200


async def test_expired_stock_is_never_usable(client, tokens):
    sci, ana = tokens["scientist"], tokens["lab_analyst"]
    exp = await mk_lot(client, ana, qty=80, expiry=PAST)
    assert exp["status"] == "red" and exp["usable_quantity"] == 0 and exp["quantity_available"] == 80
    s = summary((await client.get("/api/inventory/reagents/summary", headers=auth(sci))).json(), exp["reagent_id"])
    assert s["status"] == "expired" and s["physical_quantity"] == 80 and s["expired_quantity"] == 80 and s["usable_quantity"] == 0
    # nothing can issue from it, however it is attempted
    req = (await submit(client, sci, exp["reagent_id"], quantity=1)).json()
    r = await client.post(f"/api/requests/{req['id']}/issue", headers=auth(ana), json={"lot_id": exp["lot_id"]})
    assert r.status_code == 409 and "expired" in r.text.lower()
    await move(client, ana, req["id"], "approved")
    assert (await client.post(f"/api/requests/{req['id']}/fulfil", headers=auth(ana),
                              json={"note": "claim", "lot_id": exp["lot_id"]})).status_code == 409
    assert (await client.post(f"/api/requests/{req['id']}/transition", headers=auth(ana),
                              json={"to_status": "approved", "reserve_lot_id": exp["lot_id"]})).status_code == 409
    # adding more quantity to an expired lot does not make it usable; a second, in-date lot does, and the two are tracked separately
    rec = (await client.post(f"/api/inventory/lots/{exp['lot_id']}/receive", headers=auth(ana), json={"quantity": 5, "reason": "oops wrong lot"})).json()
    assert rec["usable_quantity"] == 0 and rec["status"] == "red"
    good = await client.post("/api/inventory/lots", headers=auth(ana), json={
        "reagent_id": exp["reagent_id"], "lot_no": "NEW-1", "capacity": 100, "quantity_available": 30, "expiry_date": FUTURE})
    assert good.status_code == 201
    s = summary((await client.get("/api/inventory/reagents/summary", headers=auth(sci))).json(), exp["reagent_id"])
    assert s["physical_quantity"] == 115 and s["expired_quantity"] == 85 and s["usable_quantity"] == 30 and s["status"] in ("available", "awaiting_restock", "low")
    assert s["lots"] == 2
    # a lot that expires today is expired; quarantined stock is unavailable, not usable
    today = await mk_lot(client, ana, qty=10, expiry=date.today().isoformat())
    assert today["usable_quantity"] == 0
    q = await mk_lot(client, ana, qty=10)
    patched = await client.patch(f"/api/inventory/lots/{q['lot_id']}", headers=auth(ana),
                                 json={"expected_version": q["row_version"], "availability": "quarantined", "reason": "QC hold"})
    assert patched.json()["usable_quantity"] == 0 and patched.json()["status"] == "red"
    assert summary((await client.get("/api/inventory/reagents/summary", headers=auth(sci))).json(), q["reagent_id"])["status"] == "unavailable"


async def test_reservations_hold_stock_without_changing_physical_stock(client, tokens):
    sci, sen, ana = tokens["scientist"], tokens["senior_analyst"], tokens["lab_analyst"]
    lot = await mk_lot(client, ana, qty=10)
    r1 = (await submit(client, sci, lot["reagent_id"], quantity=6)).json()
    r2 = (await submit(client, sen, lot["reagent_id"], quantity=6)).json()
    a = await move(client, ana, r1["id"], "approved", reserve_lot_id=lot["lot_id"])
    assert a.status_code == 200 and a.json()["reserved_quantity"] == 6
    s = summary((await client.get("/api/inventory/reagents/summary", headers=auth(sci))).json(), lot["reagent_id"])
    assert (s["physical_quantity"], s["reserved_quantity"], s["usable_quantity"]) == (10, 6, 4)
    # a second reservation cannot over-commit the lot; plain approval (no hold) is still possible
    assert (await move(client, ana, r2["id"], "approved", reserve_lot_id=lot["lot_id"])).status_code == 409
    assert (await client.get(f"/api/requests/{r2['id']}", headers=auth(sen))).json()["status"] == "submitted"
    # stock reserved for r1 cannot be issued to r2 or disposed of or adjusted away
    await move(client, ana, r2["id"], "approved")
    assert (await client.post(f"/api/requests/{r2['id']}/fulfil", headers=auth(ana),
                              json={"note": "try", "lot_id": lot["lot_id"], "issue_from_lot": True})).status_code == 409
    assert (await client.post(f"/api/inventory/lots/{lot['lot_id']}/dispose", headers=auth(ana), json={"reason": "no longer needed"})).status_code == 409
    assert (await client.post(f"/api/inventory/lots/{lot['lot_id']}/adjust", headers=auth(ana), json={"new_quantity": 3, "reason": "recount"})).status_code == 409
    # fulfilling r1 consumes its own reservation
    assert (await client.post(f"/api/requests/{r1['id']}/fulfil", headers=auth(ana),
                              json={"note": "issued", "lot_id": lot["lot_id"], "issue_from_lot": True})).status_code == 200
    row = db("SELECT quantity_available, reserved_quantity FROM reagent_lots WHERE id=%s", lot["lot_id"])[0]
    assert (float(row[0]), float(row[1])) == (4, 0)
    # rejecting an approved, reserved request releases the hold
    r3 = (await submit(client, sci, lot["reagent_id"], quantity=3)).json()
    await move(client, ana, r3["id"], "approved", reserve_lot_id=lot["lot_id"])
    assert float(db("SELECT reserved_quantity FROM reagent_lots WHERE id=%s", lot["lot_id"])[0][0]) == 3
    await move(client, ana, r3["id"], "rejected", "Project cancelled")
    assert float(db("SELECT reserved_quantity FROM reagent_lots WHERE id=%s", lot["lot_id"])[0][0]) == 0


# ------------------------------------------------------------------ integrity under concurrency
async def test_stock_updates_cannot_silently_overwrite_each_other(client, tokens):
    ana = tokens["lab_analyst"]
    lot = await mk_lot(client, ana, qty=10, capacity=1000)
    lid, v = lot["lot_id"], lot["row_version"]
    # many editors saved from the same version: exactly one wins
    res = await asyncio.gather(*[client.patch(f"/api/inventory/lots/{lid}", headers=auth(ana),
                                              json={"expected_version": v, "location": f"Shelf {i}", "reason": "move"}) for i in range(8)])
    assert sorted(r.status_code for r in res) == [200] + [409] * 7
    cur = (await client.get(f"/api/inventory?name={lot['lot_no']}", headers=auth(ana))).json()[0]
    assert cur["row_version"] == v + 1
    # stale absolute adjustment is refused; a current one works
    assert (await client.post(f"/api/inventory/lots/{lid}/adjust", headers=auth(ana),
                              json={"new_quantity": 99, "reason": "stale count", "expected_version": v})).status_code == 409
    assert (await client.post(f"/api/inventory/lots/{lid}/adjust", headers=auth(ana),
                              json={"new_quantity": 12, "reason": "fresh count", "expected_version": cur["row_version"]})).json()["quantity_available"] == 12
    # relative deliveries booked at the same moment all count (none is lost)
    res = await asyncio.gather(*[client.post(f"/api/inventory/lots/{lid}/receive", headers=auth(ana), json={"quantity": 2, "reason": "delivery"}) for _ in range(10)])
    assert all(r.status_code == 200 for r in res)
    assert float(db("SELECT quantity_available FROM reagent_lots WHERE id=%s", lid)[0][0]) == 32
    assert db("SELECT count(*) FROM inventory_transactions WHERE lot_id=%s AND type='received'", lid)[0][0] == 11
    # negative / impossible quantities never get through, API or database
    for path, body in ((f"/api/inventory/lots/{lid}/adjust", {"new_quantity": -1, "reason": "negative"}),
                       (f"/api/inventory/lots/{lid}/receive", {"quantity": -5, "reason": "negative"}),
                       (f"/api/inventory/lots/{lid}/receive", {"quantity": 0, "reason": "zero qty"}),
                       (f"/api/inventory/lots/{lid}/return", {"quantity": -1}),
                       (f"/api/inventory/lots/{lid}/adjust", {"new_quantity": 5000, "reason": "above capacity"}),
                       (f"/api/inventory/lots/{lid}/receive", {"quantity": 5000, "reason": "above capacity"})):
        assert (await client.post(path, headers=auth(ana), json=body)).status_code in (409, 422), path
    with psycopg.connect(_test_url, autocommit=True) as c:
        for sql in ("UPDATE reagent_lots SET quantity_available = -1 WHERE id = %s", "UPDATE reagent_lots SET reserved_quantity = quantity_available + 1 WHERE id = %s"):
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute(sql, (lid,))


async def test_unauthorised_inventory_changes_are_rejected(client, tokens):
    sci, sen, adm, ana = tokens["scientist"], tokens["senior_analyst"], tokens["admin"], tokens["lab_analyst"]
    lot = await mk_lot(client, ana, qty=10)
    lid = lot["lot_id"]
    calls = [("POST", f"/api/inventory/lots/{lid}/receive", {"quantity": 5, "reason": "free stock"}),
             ("POST", f"/api/inventory/lots/{lid}/adjust", {"new_quantity": 500, "reason": "free stock"}),
             ("POST", f"/api/inventory/lots/{lid}/return", {"quantity": 1}),
             ("POST", f"/api/inventory/lots/{lid}/dispose", {"reason": "sabotage"}),
             ("PATCH", f"/api/inventory/lots/{lid}", {"expected_version": 1, "expiry_date": "2099-01-01", "reason": "extend expiry"}),
             ("POST", "/api/inventory/lots", {"reagent_name": "x", "lot_no": "y", "capacity": 1, "quantity_available": 1})]
    for token in (sci, sen, adm):
        for m, path, body in calls:
            assert (await client.request(m, path, headers=auth(token), json=body)).status_code == 403, (m, path)
    assert (await client.get("/api/requests/pending", headers=auth(sci))).status_code == 403
    after = (await client.get(f"/api/inventory?name={lot['lot_no']}", headers=auth(ana))).json()[0]
    assert after["quantity_available"] == 10 and after["expiry_date"] == lot["expiry_date"] and after["row_version"] == lot["row_version"]


async def test_lab_assistant_can_search_filter_and_page_requests(client, tokens):
    sci, sen, ana = tokens["scientist"], tokens["senior_analyst"], tokens["lab_analyst"]
    a = await mk_lot(client, ana, name="Filterable Alpha Acid")
    b = await mk_lot(client, ana, name="Filterable Beta Base")
    ids = []
    for i in range(3):
        ids.append((await submit(client, sci, a["reagent_id"], urgency="urgent" if i == 0 else "low")).json()["id"])
    ids.append((await submit(client, sen, b["reagent_id"])).json()["id"])
    await move(client, ana, ids[1], "under_review")
    base = "/api/requests"
    assert (await client.get(f"{base}?reagent=Filterable%20Alpha", headers=auth(ana))).json()["total"] == 3
    assert (await client.get(f"{base}?reagent=Filterable&status=under_review", headers=auth(ana))).json()["total"] == 1
    assert (await client.get(f"{base}?reagent=Filterable&requester=t_senior", headers=auth(ana))).json()["total"] == 1
    page = (await client.get(f"{base}?reagent=Filterable&urgency=urgent", headers=auth(ana))).json()
    assert page["total"] == 1 and page["items"][0]["id"] == ids[0]
    today = date.today().isoformat()
    assert (await client.get(f"{base}?reagent=Filterable&date_from={today}&date_to={today}", headers=auth(ana))).json()["total"] == 4
    assert (await client.get(f"{base}?reagent=Filterable&date_to=2000-01-01", headers=auth(ana))).json()["total"] == 0
    p1 = (await client.get(f"{base}?reagent=Filterable&limit=3&offset=0", headers=auth(ana))).json()
    p2 = (await client.get(f"{base}?reagent=Filterable&limit=3&offset=3", headers=auth(ana))).json()
    assert len(p1["items"]) == 3 and len(p2["items"]) == 1 and p1["total"] == 4
    assert p1["items"][0]["urgency"] == "urgent"                  # urgent first
    assert {"requester_name", "reagent_name", "quantity", "purpose", "urgency", "created_at"} <= set(p1["items"][0])
