"""Apply backend/migrations/*.sql in order, once each (recorded in schema_migrations).

New tables come from the SQLAlchemy models (scripts/db_init.py runs create_all first); the numbered SQL files carry
everything create_all cannot do on a database that already exists: ALTER TABLE, data back-fills, triggers.

Usage: python scripts/migrate.py [--test]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg

from app.config import get_settings

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def apply(url: str) -> list[str]:
    applied: list[str] = []
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        done = {r[0] for r in c.execute("SELECT name FROM schema_migrations").fetchall()}
        for f in sorted(MIGRATIONS.glob("*.sql")):
            if f.name in done:
                continue
            with c.transaction():
                c.execute(f.read_text(encoding="utf-8"))
                c.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (f.name,))
            applied.append(f.name)
    return applied


if __name__ == "__main__":
    from scripts.db_init import init   # creates any new tables first, then applies the SQL migrations

    s = get_settings()
    init(s.test_database_url if "--test" in sys.argv else s.database_url)
