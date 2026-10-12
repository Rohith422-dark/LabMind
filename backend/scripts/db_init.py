"""Idempotent schema setup: extensions, tables, append-only triggers.

Usage: python scripts/db_init.py [--test]   (--test targets TEST_DATABASE_URL, creating it if needed)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg
from psycopg import sql
from sqlalchemy import create_engine

from app.config import db_name, get_settings
from app.db import Base
import app.models.tables  # noqa: F401  (register models)

TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION forbid_mutation() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION '% is append-only: % not allowed', TG_TABLE_NAME, TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log;
CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

DROP TRIGGER IF EXISTS inv_tx_append_only ON inventory_transactions;
CREATE TRIGGER inv_tx_append_only BEFORE UPDATE OR DELETE ON inventory_transactions
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
"""


def ensure_database(url: str) -> None:
    name = db_name(url)
    admin = url.rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(admin, autocommit=True) as c:
        if not c.execute("SELECT 1 FROM pg_database WHERE datname=%s", (name,)).fetchone():
            c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            print(f"created database {name}")


def init(url: str) -> None:
    ensure_database(url)
    with psycopg.connect(url, autocommit=True) as c:
        for ext in ("vector", "pg_trgm", "pgcrypto"):
            c.execute(f"CREATE EXTENSION IF NOT EXISTS {ext}")
    eng = create_engine(url.replace("postgresql://", "postgresql+psycopg://", 1))
    Base.metadata.create_all(eng)
    eng.dispose()
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(TRIGGER_SQL)
    print(f"schema ready: {db_name(url)}")


if __name__ == "__main__":
    s = get_settings()
    init(s.test_database_url if "--test" in sys.argv else s.database_url)
