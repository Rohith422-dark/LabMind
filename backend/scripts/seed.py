"""Reset and seed the demo database with REAL documents and the supplied inventory/users.

Documents go through the SAME ingestion code path as uploads. Run: npm run seed
Fails loudly on a manifest entry with no file / no SOURCES.md row, and on malformed CSV rows (with line numbers).
"""
import asyncio
import csv
import json
import secrets
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from sqlalchemy import text
from argon2 import PasswordHasher
from pydantic import BaseModel, ValidationError, field_validator

from app.config import db_name, get_settings
from app.db import session_maker
from app.models.tables import InventoryTransaction, Reagent, ReagentLot, User
from app.services import answer_cache, ingest, pubchem
from scripts.db_init import init

SEED = Path(__file__).resolve().parents[1] / "seed"
DOCS = SEED / "docs"


class Row(BaseModel):
    reagent_name: str
    cas_number: str | None = None
    grade: str | None = None
    supplier: str | None = None
    lot_no: str
    capacity: float
    quantity_available: float
    unit: str
    location: str
    received_date: date
    expiry_date: date
    storage_conditions: str | None = None
    reorder_level: float | None = None

    @field_validator("reagent_name", "lot_no", "unit", "location")
    @classmethod
    def _nonblank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v.strip()

    @field_validator("cas_number", "grade", "supplier", "storage_conditions", "reorder_level", mode="before")
    @classmethod
    def _empty_to_none(cls, v):
        return None if v is None or str(v).strip() == "" else v


def load_inventory() -> list[Row]:
    rows, errors = [], []
    with open(SEED / "inventory.csv", newline="", encoding="utf-8") as f:
        for i, rec in enumerate(csv.DictReader(f), start=2):
            try:
                row = Row(**rec)
                if row.quantity_available > row.capacity:
                    raise ValueError("quantity_available exceeds capacity")
                rows.append(row)
            except (ValidationError, ValueError, TypeError) as e:
                errors.append(f"inventory.csv line {i}: {e}")
    if errors:
        raise SystemExit("INVALID INVENTORY:\n" + "\n".join(errors))
    return rows


def validate_manifest() -> list[dict]:
    manifest = json.loads((SEED / "manifest.json").read_text(encoding="utf-8"))["documents"]
    sources = (DOCS / "SOURCES.md").read_text(encoding="utf-8")
    missing = []
    for d in manifest:
        if not (DOCS / d["file"]).exists():
            missing.append(f"{d['file']}: file not found in seed/docs (download it using the URL in SOURCES.md)")
        if d["file"] not in sources:
            missing.append(f"{d['file']}: no row in SOURCES.md")
    if missing:
        raise SystemExit("MANIFEST PROBLEMS:\n" + "\n".join(missing))
    return manifest


async def seed_users(settings) -> dict[str, User]:
    ph = PasswordHasher()
    users: dict[str, User] = {}
    async with session_maker()() as s:
        for u in json.loads((SEED / "users.json").read_text(encoding="utf-8")):
            pw = settings.password_for(u["username"])
            if not pw:
                pw = secrets.token_urlsafe(10)
                print(f"  generated password for {u['username']}: {pw}   (set USER_PASSWORDS in .env to choose your own)")
            user = User(username=u["username"], password_hash=ph.hash(pw), full_name=u["full_name"],
                        role=u["role"], department=u.get("department"))
            s.add(user)
            users[u["username"]] = user
        await s.commit()
    return users


async def seed_inventory(rows: list[Row], analyst: User) -> None:
    cache_path = SEED / "reagents.cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "smart-lab-assistant-hackathon"}) as client:
        for r in rows:
            if r.cas_number and r.cas_number not in cache:
                try:
                    cache[r.cas_number] = await pubchem.fetch(client, r.cas_number)
                    print(f"  PubChem {r.reagent_name}: CID {cache[r.cas_number] and cache[r.cas_number]['cid']}")
                except Exception as e:  # noqa: BLE001
                    print(f"  PubChem lookup failed for {r.reagent_name} ({e}); hazards left empty")
                    cache[r.cas_number] = None
    cache_path.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    async with session_maker()() as s:
        reagents: dict[str, Reagent] = {}
        for r in rows:
            if r.reagent_name in reagents:
                continue
            pc = cache.get(r.cas_number) if r.cas_number else None
            reagents[r.reagent_name] = rg = Reagent(
                name=r.reagent_name, cas_number=r.cas_number, formula=(pc or {}).get("formula"),
                hazard_classes=(pc or {}).get("hazard_classes", []), hazard_statements=(pc or {}).get("hazard_statements", []),
                pubchem_cid=(pc or {}).get("cid"), storage_conditions=r.storage_conditions, supplier=r.supplier,
                reorder_level=r.reorder_level, unit=r.unit)
            s.add(rg)
        await s.flush()
        for r in rows:
            lot = ReagentLot(reagent_id=reagents[r.reagent_name].id, lot_no=r.lot_no, grade=r.grade, capacity=r.capacity,
                             quantity_available=r.quantity_available, location=r.location, expiry_date=r.expiry_date,
                             received_date=r.received_date, storage_conditions=r.storage_conditions, supplier=r.supplier)
            s.add(lot)
            await s.flush()
            s.add(InventoryTransaction(lot_id=lot.id, type="received", quantity=r.quantity_available,
                                       performed_by=analyst.id, reason="opening stock register"))
        await s.commit()
    print(f"  {len(reagents)} reagents, {len(rows)} lots")


async def seed_documents(manifest: list[dict], senior: User) -> None:
    for d in sorted(manifest, key=lambda d: (d["doc_code"], d["version"])):
        data = (DOCS / d["file"]).read_bytes()
        async with session_maker()() as s:
            job_id = await ingest.create_job(s, senior, d["file"], data)
            await s.commit()
        await ingest.run_job(job_id)
        async with session_maker()() as s:
            from app.models.tables import IngestJob
            job = await s.get(IngestJob, job_id)
            if job.status != "ready":
                raise SystemExit(f"ingest failed for {d['file']}: {job.error}")
            steps = d.get("steps") or (job.preview["steps"] if d["doc_type"] in ("SOP", "protocol") else [])
            meta = {k: d.get(k) for k in ("doc_code", "title", "doc_type", "department", "equipment", "change_note")}
            await ingest.publish(s, senior, job, meta, steps, None, None)
            await s.commit()
        print(f"  {d['doc_code']} v{d['version']}: {job.preview['chunk_count']} chunks, {len(steps)} steps"
              + (f", warnings: {job.preview['warnings']}" if job.preview["warnings"] else ""))


async def prewarm(users: dict[str, User]) -> None:
    from app.services import rag
    qpath = SEED / "demo-questions.json"
    if not qpath.exists():
        print("  no demo-questions.json yet; skipping cache pre-warm")
        return
    qs = [q for q in json.loads(qpath.read_text(encoding="utf-8")) if q["kind"] == "answerable"]
    for q in qs:
        n_tokens = 0
        async for ev in rag.answer_stream(users["scientist"], q["question"], [], None):
            n_tokens += ev["type"] == "token"
        print(f"  pre-warmed: {q['question'][:70]}  ({n_tokens} tokens)")
    async with session_maker()() as s:  # the demo starts with an empty chat history (cache + audit remain)
        await s.execute(text("DELETE FROM chat_history"))
        await s.execute(text("DELETE FROM conversations WHERE project_id IS NULL"))
        await s.execute(text("DELETE FROM knowledge_gaps"))
        await s.commit()


async def main() -> None:
    settings = get_settings()
    if db_name(settings.database_url) == db_name(settings.test_database_url):
        raise SystemExit("DATABASE_URL equals TEST_DATABASE_URL; refusing to seed.")
    manifest = validate_manifest()
    inventory_rows = load_inventory()
    print(f"Resetting {db_name(settings.database_url)} ...")
    init(settings.database_url, reset=True)
    print("Users:")
    users = await seed_users(settings)
    print("Inventory (PubChem master data + supplied register):")
    await seed_inventory(inventory_rows, users["analyst"])
    print("Documents (same code path as uploads):")
    await seed_documents(manifest, users["senior"])
    print("Pre-warming answer cache:")
    await prewarm(users)
    print("Done. Next: `npm run snapshot` to freeze this state.")


if __name__ == "__main__":
    asyncio.run(main())
