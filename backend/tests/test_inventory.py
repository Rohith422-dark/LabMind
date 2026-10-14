"""Atomic issue under concurrency + expired-lot blocking. Synthetic rows live in the TEST database only."""
import asyncio
from datetime import date, timedelta

from sqlalchemy import text

from app.db import session_maker
from tests.conftest import auth


async def seed(qty: float, expiry: date | None):
    async with session_maker()() as s:
        rid = (await s.execute(text("INSERT INTO reagents (name, unit, reorder_level) VALUES ('Test reagent', 'g', 1) "
                                    "RETURNING id"))).scalar()
        lid = (await s.execute(text("INSERT INTO reagent_lots (reagent_id, lot_no, capacity, quantity_available, expiry_date) "
                                    "VALUES (:r, :l, 100, :q, :e) RETURNING id"),
                               {"r": rid, "l": f"T-{qty}-{expiry}", "q": qty, "e": expiry})).scalar()
        await s.commit()
    return rid, lid


async def test_ten_concurrent_issues_exactly_three_succeed(client, tokens):
    rid, lid = await seed(3, date.today() + timedelta(days=365))
    sci, ana = tokens["scientist"], tokens["lab_analyst"]
    ids = []
    for _ in range(10):
        r = await client.post("/api/requests", headers=auth(sci), json={"reagent_id": str(rid), "quantity": 1, "reason": "unit test"})
        assert r.status_code == 201
        ids.append(r.json()["id"])
    res = await asyncio.gather(*[client.post(f"/api/requests/{i}/issue", headers=auth(ana), json={"lot_id": str(lid)})
                                 for i in ids])
    codes = sorted(r.status_code for r in res)
    assert codes.count(200) == 3 and codes.count(409) == 7, codes
    async with session_maker()() as s:
        qty = (await s.execute(text("SELECT quantity_available FROM reagent_lots WHERE id=:i"), {"i": lid})).scalar()
        tx = (await s.execute(text("SELECT count(*) FROM inventory_transactions WHERE lot_id=:i AND type='issued'"),
                              {"i": lid})).scalar()
    assert float(qty) == 0 and tx == 3


async def test_expired_lot_blocked_and_scientist_forbidden(client, tokens):
    rid, lid = await seed(50, date.today() - timedelta(days=1))
    sci, ana = tokens["scientist"], tokens["lab_analyst"]
    req = (await client.post("/api/requests", headers=auth(sci), json={"reagent_id": str(rid), "quantity": 1, "reason": "unit test"})).json()
    r = await client.post(f"/api/requests/{req['id']}/issue", headers=auth(ana), json={"lot_id": str(lid)})
    assert r.status_code == 409 and "expired" in r.text.lower()
    # nothing written
    again = (await client.get("/api/requests/pending", headers=auth(ana))).json()
    assert any(x["id"] == req["id"] for x in again)
    # stock-changing endpoints are analyst-only
    for path, body in ((f"/api/requests/{req['id']}/issue", {"lot_id": str(lid)}),
                       (f"/api/inventory/lots/{lid}/adjust", {"new_quantity": 5, "reason": "x y z"})):
        assert (await client.post(path, headers=auth(sci), json=body)).status_code == 403
    # mandatory reasons
    assert (await client.post(f"/api/requests/{req['id']}/reject", headers=auth(ana), json={"reason": ""})).status_code == 422
    assert (await client.post(f"/api/inventory/lots/{lid}/adjust", headers=auth(ana),
                              json={"new_quantity": 5, "reason": ""})).status_code == 422
