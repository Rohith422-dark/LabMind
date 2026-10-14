"""Restore the frozen demo state in seconds, WITHOUT calling the AI API. CLI only (no HTTP endpoint).
Usage: npm run demo:reset"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg

from app.config import db_name, get_settings
from scripts._snap import ORDER, SNAP_DIR, restore_columns


def main() -> int:
    s = get_settings()
    if db_name(s.database_url) == db_name(s.test_database_url):
        print("refusing: DATABASE_URL equals TEST_DATABASE_URL")
        return 1
    missing = [t for t in ORDER if not (SNAP_DIR / f"{t}.copy").exists()]
    if missing:
        print(f"no snapshot found ({missing[0]}.copy missing). Run `npm run seed` then `npm run snapshot` first.")
        return 1
    t0 = time.time()
    with psycopg.connect(s.database_url) as conn:
        conn.execute("TRUNCATE " + ", ".join(f'"{t}"' for t in ORDER) + " CASCADE")
        for t in ORDER:
            cols = ", ".join(f'"{c}"' for c in restore_columns(conn, t))
            with conn.cursor().copy(f'COPY "{t}" ({cols}) FROM STDIN') as cp:
                with open(SNAP_DIR / f"{t}.copy", "rb") as f:
                    while chunk := f.read(1 << 20):
                        cp.write(chunk)
        conn.execute("SELECT setval(pg_get_serial_sequence('audit_log', 'id'), COALESCE((SELECT max(id) FROM audit_log), 1))")
        conn.commit()
        counts = {t: conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in ("users", "documents", "chunks", "reagent_lots", "audit_log", "answer_cache")}
    print(f"restored in {time.time() - t0:.1f}s: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
