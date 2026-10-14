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


# Columns added after the first snapshots were taken (migration 001). A snapshot without a .cols sidecar predates them,
# so restoring must leave them out and let the column defaults apply.
LEGACY_MISSING = {
    "reagent_lots": {"reserved_quantity", "availability", "row_version"},
    "reagent_requests": {"reagent_name_text", "unit", "details", "urgency", "project_id", "reserved_lot_id", "reserved_quantity",
                         "fulfilment_note", "fulfilled_at"},
    "chat_history": {"project_id", "conversation_id", "meta"},   # conversation_id/meta predate this migration too
    "notifications": {"kind"},
}


def restore_columns(conn: psycopg.Connection, table: str) -> list[str]:
    side = SNAP_DIR / f"{table}.cols"
    if side.exists():
        return side.read_text(encoding="utf-8").split(",")
    return [c for c in columns(conn, table) if c not in LEGACY_MISSING.get(table, set())]
