"""Shared helpers for snapshot / demo_reset: text-format COPY in foreign-key order (pure Python, any Postgres)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg

SNAP_DIR = Path(__file__).resolve().parents[1] / "seed" / "snapshot"

# parents before children
ORDER = [
    "users", "documents", "document_files", "sop_steps", "chunks", "reagents", "reagent_lots", "reagent_requests",
    "inventory_transactions", "chat_history", "knowledge_gaps", "troubleshooting_sessions", "notifications",
    "audit_log", "ingest_jobs", "answer_cache",
]


def columns(conn: psycopg.Connection, table: str) -> list[str]:
    """Writable columns (generated columns such as chunks.tsv are rebuilt by the database)."""
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s "
        "AND is_generated='NEVER' ORDER BY ordinal_position", (table,)).fetchall()
    return [r[0] for r in rows]
