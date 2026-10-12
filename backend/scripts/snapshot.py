"""Freeze the seeded demo state: export every table with COPY to backend/seed/snapshot/. Usage: npm run snapshot"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg

from app.config import db_name, get_settings
from scripts._snap import ORDER, SNAP_DIR, columns


def main() -> None:
    s = get_settings()
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    for f in SNAP_DIR.glob("*.copy"):
        f.unlink()
    with psycopg.connect(s.database_url) as conn:
        total = 0
        for t in ORDER:
            cols = ", ".join(f'"{c}"' for c in columns(conn, t))
            n = conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
            with open(SNAP_DIR / f"{t}.copy", "wb") as out, conn.cursor().copy(f'COPY "{t}" ({cols}) TO STDOUT') as cp:
                for block in cp:
                    out.write(bytes(block))
            print(f"  {t:26} {n:6} rows")
            total += n
    size = sum(f.stat().st_size for f in SNAP_DIR.glob("*.copy")) / 1e6
    print(f"snapshot of {db_name(s.database_url)}: {total} rows, {size:.1f} MB -> {SNAP_DIR}")


if __name__ == "__main__":
    main()
