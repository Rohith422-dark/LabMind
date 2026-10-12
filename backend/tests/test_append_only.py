import psycopg
import pytest

from app.services import audit
from tests.conftest import _test_url


@pytest.mark.parametrize("table", ["audit_log", "inventory_transactions"])
@pytest.mark.parametrize("stmt", ["UPDATE {t} SET id = id", "DELETE FROM {t}"])
async def test_raw_sql_mutation_rejected_by_database(table, stmt):
    if table == "audit_log":
        await audit.log_standalone(None, "append_only_probe")  # a properly chained row
    with psycopg.connect(_test_url, autocommit=True) as c:
        if table == "inventory_transactions":
            c.execute("INSERT INTO reagents (name) VALUES ('ao')")
            c.execute("INSERT INTO reagent_lots (reagent_id, lot_no, capacity, quantity_available) "
                      "SELECT id, 'AO-1', 1, 1 FROM reagents WHERE name='ao' LIMIT 1")
            c.execute("INSERT INTO inventory_transactions (lot_id, type, quantity, performed_by) "
                      "SELECT l.id, 'received', 1, u.id FROM reagent_lots l, users u WHERE l.lot_no='AO-1' LIMIT 1")
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            c.execute(stmt.format(t=table))
