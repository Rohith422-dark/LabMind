"""Experimental records: flexible structured data + full, append-only version history.

Integrity rules
* An edit never overwrites history: every change inserts a row in experiment_versions (a DB trigger forbids UPDATE/DELETE).
* Edits need `expected_version`; if someone else saved first the caller gets 409 and must re-read (no silent lost updates).
* "Delete" is a void: the record stays (and so does its history) but leaves lists, search and the retrieval index.
* Links and attachments are validated to belong to the SAME project (no cross-project references).
"""
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.limiter import limiter
from app.models.tables import Experiment, ExperimentVersion, ProjectDocument, User
from app.services import audit, project_index, project_troubleshoot
from app.services.access import ProjectCtx, get_child, project_access

router = APIRouter(prefix="/projects/{project_id}/experiments", tags=["experiments"])
IDENT = re.compile(r"^[\w][\w .\-/#]{0,79}$")
CONTENT_FIELDS = ("identifier", "title", "performed_at", "objective", "reagents", "equipment", "materials", "parameters",
                  "conditions", "custom_fields", "procedure_refs", "observations", "results", "conclusions", "outcome",
                  "tags", "links", "attachments")


class Param(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    value: float | None = None
    text_value: str | None = Field(default=None, max_length=300)
    unit: str | None = Field(default=None, max_length=20)
    note: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _has_value(self):
        if self.value is None and not (self.text_value or "").strip():
            raise ValueError(f"parameter '{self.name}' needs a numeric value or a text value")
        if self.value is not None and not math.isfinite(self.value):
            raise ValueError(f"parameter '{self.name}' must be a finite number")
        return self


class ReagentUse(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    reagent_id: uuid.UUID | None = None
    lot_no: str | None = Field(default=None, max_length=80)
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=16)


class Equipment(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    id: str | None = Field(default=None, max_length=80)


class ProcedureRef(BaseModel):
    document_id: uuid.UUID | None = None
    text: str | None = Field(default=None, max_length=500)


class Link(BaseModel):
    experiment_id: uuid.UUID
    relation: Literal["previous", "next", "related"] = "related"


Scalar = str | int | float | bool


class ExperimentBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    performed_at: datetime | None = None
    objective: str | None = Field(default=None, max_length=8000)
    reagents: list[ReagentUse] = Field(default_factory=list, max_length=200)
    equipment: list[Equipment] = Field(default_factory=list, max_length=100)
    materials: list[str] = Field(default_factory=list, max_length=200)
    parameters: list[Param] = Field(default_factory=list, max_length=500)
    conditions: dict[str, Scalar] = Field(default_factory=dict)
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    procedure_refs: list[ProcedureRef] = Field(default_factory=list, max_length=100)
    observations: str | None = Field(default=None, max_length=40000)
    results: str | None = Field(default=None, max_length=40000)
    conclusions: str | None = Field(default=None, max_length=40000)
    outcome: Literal["success", "failure", "inconclusive", "unknown"] = "unknown"
    tags: list[str] = Field(default_factory=list, max_length=30)
    links: list[Link] = Field(default_factory=list, max_length=100)
    attachments: list[uuid.UUID] = Field(default_factory=list, max_length=100)

    @field_validator("conditions", "custom_fields")
    @classmethod
    def _small(cls, v: dict) -> dict:
        if len(v) > 100 or any(len(str(k)) > 80 for k in v):
            raise ValueError("too many or too long keys")
        return v

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        return [t.strip()[:40] for t in v if t and t.strip()]


class ExperimentCreate(ExperimentBody):
    identifier: str = Field(min_length=1, max_length=80)

    @field_validator("identifier")
    @classmethod
    def _ident(cls, v: str) -> str:
        v = v.strip()
        if not IDENT.match(v) or ".." in v or v.startswith("/"):
            raise ValueError("identifier may contain letters, digits, space and . - / # _ only (no '..' or leading '/')")
        return v


class ExperimentPatch(BaseModel):
    """Partial update. `expected_version` is mandatory: it is the version the editor was looking at."""
    expected_version: int = Field(ge=1)
    change_note: str | None = Field(default=None, max_length=500)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    performed_at: datetime | None = None
    objective: str | None = Field(default=None, max_length=8000)
    reagents: list[ReagentUse] | None = None
    equipment: list[Equipment] | None = None
    materials: list[str] | None = None
    parameters: list[Param] | None = None
    conditions: dict[str, Scalar] | None = None
    custom_fields: dict[str, Any] | None = None
    procedure_refs: list[ProcedureRef] | None = None
    observations: str | None = Field(default=None, max_length=40000)
    results: str | None = Field(default=None, max_length=40000)
    conclusions: str | None = Field(default=None, max_length=40000)
    outcome: Literal["success", "failure", "inconclusive", "unknown"] | None = None
    tags: list[str] | None = None
    links: list[Link] | None = None
    attachments: list[uuid.UUID] | None = None


class ExperimentOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    identifier: str
    title: str
    performed_at: datetime | None
    objective: str | None
    reagents: list
    equipment: list
    materials: list
    parameters: list
    conditions: dict
    custom_fields: dict
    procedure_refs: list
    observations: str | None
    results: str | None
    conclusions: str | None
    outcome: str
    tags: list[str]
    links: list
    attachments: list
    version: int
    created_by: uuid.UUID
    created_by_name: str | None = None
    updated_by: uuid.UUID
    updated_by_name: str | None = None
    created_at: datetime
    updated_at: datetime
    voided_at: datetime | None = None


class ExperimentPage(BaseModel):
    items: list[ExperimentOut]
    total: int
    limit: int
    offset: int


class VersionOut(BaseModel):
    version: int
    changed_fields: list[str]
    change_note: str | None
    changed_by: uuid.UUID
    changed_by_name: str | None = None
    changed_at: datetime


class VersionDetail(VersionOut):
    snapshot: dict


# ------------------------------------------------------------------ helpers
def _json_safe(v: Any) -> Any:
    if isinstance(v, (datetime,)):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, dict):
        return {k: _json_safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    return v


def snapshot(e: Experiment) -> dict:
    return {f: _json_safe(getattr(e, f)) for f in CONTENT_FIELDS} | {"version": e.version, "voided": e.voided_at is not None}


async def _names(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = (await session.execute(select(User.id, User.full_name).where(User.id.in_(ids)))).all()
    return {i: n for i, n in rows}


async def _out_many(session: AsyncSession, rows: list[Experiment]) -> list[ExperimentOut]:
    names = await _names(session, {r.created_by for r in rows} | {r.updated_by for r in rows})
    return [ExperimentOut(**{c: getattr(r, c) for c in ExperimentOut.model_fields if hasattr(r, c)
                             and c not in ("created_by_name", "updated_by_name")},
                          created_by_name=names.get(r.created_by), updated_by_name=names.get(r.updated_by)) for r in rows]


async def _validate_refs(session: AsyncSession, project_id: uuid.UUID, links: list, attachments: list, exclude: uuid.UUID | None = None):
    ids = {l["experiment_id"] if isinstance(l, dict) else str(l.experiment_id) for l in links}
    if ids:
        found = set(str(x) for x in (await session.execute(select(Experiment.id).where(
            Experiment.project_id == project_id, Experiment.id.in_([uuid.UUID(i) for i in ids])))).scalars())
        if found != ids:
            raise HTTPException(422, "A linked experiment does not exist in this project")
        if exclude and str(exclude) in ids:
            raise HTTPException(422, "An experiment cannot link to itself")
    att = {str(a) for a in attachments}
    if att:
        found = set(str(x) for x in (await session.execute(select(ProjectDocument.id).where(
            ProjectDocument.project_id == project_id, ProjectDocument.id.in_([uuid.UUID(a) for a in att]),
            ProjectDocument.status == "ready"))).scalars())
        if found != att:
            raise HTTPException(422, "An attachment is not a document of this project")


def _dump(body: BaseModel) -> dict:
    return {k: v for k, v in body.model_dump(mode="json").items() if k in CONTENT_FIELDS}


async def _get(session: AsyncSession, project_id: uuid.UUID, eid: uuid.UUID, lock: bool = False) -> Experiment:
    q = select(Experiment).where(Experiment.id == eid, Experiment.project_id == project_id)
    if lock:
        q = q.with_for_update()
    e = (await session.execute(q)).scalar_one_or_none()
    if e is None:
        raise HTTPException(404, "Experiment not found")
    return e


# ------------------------------------------------------------------ routes
@router.post("", response_model=ExperimentOut, status_code=201)
@limiter.limit("120/minute")
async def create_experiment(request: Request, body: ExperimentCreate, ctx: ProjectCtx = project_access("editor"),
                            session: AsyncSession = Depends(get_session)):
    dup = (await session.execute(select(Experiment.id).where(
        Experiment.project_id == ctx.project.id, func.lower(Experiment.identifier) == body.identifier.lower()))).first()
    if dup:
        raise HTTPException(409, f"An experiment with identifier '{body.identifier}' already exists in this project")
    data = _dump(body)
    await _validate_refs(session, ctx.project.id, data["links"], data["attachments"])
    data.pop("performed_at", None)
    e = Experiment(project_id=ctx.project.id, **data, performed_at=body.performed_at,
                   created_by=ctx.user.id, updated_by=ctx.user.id, version=1)
    session.add(e)
    await session.flush()
    session.add(ExperimentVersion(experiment_id=e.id, project_id=e.project_id, version=1, snapshot=snapshot(e),
                                  changed_fields=list(CONTENT_FIELDS), change_note="created", changed_by=ctx.user.id))
    await project_index.index_experiment(session, e)
    await audit.log(session, ctx.user, "experiment_created", str(e.id), {"project_id": str(e.project_id), "identifier": e.identifier},
                    audit.client_ip(request))
    await session.commit()
    return (await _out_many(session, [e]))[0]


@router.get("", response_model=ExperimentPage)
async def list_experiments(
    q: str | None = Query(None, max_length=200), outcome: str | None = None, tag: str | None = None,
    parameter: str | None = Query(None, max_length=120), date_from: datetime | None = None, date_to: datetime | None = None,
    sort: Literal["performed_at", "created_at", "updated_at", "identifier"] = "performed_at",
    order: Literal["asc", "desc"] = "desc", limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0),
    include_voided: bool = False, ctx: ProjectCtx = project_access("viewer"), session: AsyncSession = Depends(get_session)):
    where = ["project_id = :pid"]
    params: dict[str, Any] = {"pid": ctx.project.id, "lim": limit, "off": offset}
    if not include_voided:
        where.append("voided_at IS NULL")
    if q:
        where.append("(tsv @@ websearch_to_tsquery('english', :q) OR identifier ILIKE :qlike OR title ILIKE :qlike)")
        params.update(q=q, qlike=f"%{q}%")
    if outcome:
        where.append("outcome = :outcome")
        params["outcome"] = outcome
    if tag:
        where.append(":tag = ANY(tags)")
        params["tag"] = tag
    if parameter:
        where.append("EXISTS (SELECT 1 FROM jsonb_array_elements(parameters) p WHERE p->>'name' ILIKE :param)")
        params["param"] = f"%{parameter}%"
    if date_from:
        where.append("performed_at >= :df")
        params["df"] = date_from
    if date_to:
        where.append("performed_at <= :dt")
        params["dt"] = date_to
    w = " AND ".join(where)
    total = (await session.execute(text(f"SELECT count(*) FROM experiments WHERE {w}"), params)).scalar_one()
    ids = (await session.execute(text(f"SELECT id FROM experiments WHERE {w} ORDER BY {sort} {order} NULLS LAST, id LIMIT :lim OFFSET :off"),
                                 params)).scalars().all()
    rows = {r.id: r for r in (await session.execute(select(Experiment).where(Experiment.id.in_(ids)))).scalars()} if ids else {}
    return ExperimentPage(items=await _out_many(session, [rows[i] for i in ids]), total=total, limit=limit, offset=offset)


@router.get("/parameters", response_model=list[dict])
async def parameter_catalog(ctx: ProjectCtx = project_access("viewer"), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(text(
        "SELECT p->>'name' AS name, coalesce(p->>'unit','') AS unit, count(*) AS n FROM experiments, jsonb_array_elements(parameters) p "
        "WHERE project_id = :pid AND voided_at IS NULL GROUP BY 1, 2 ORDER BY 1, 2"), {"pid": ctx.project.id})).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{experiment_id}", response_model=ExperimentOut)
async def get_experiment(experiment_id: uuid.UUID, ctx: ProjectCtx = project_access("viewer"),
                         session: AsyncSession = Depends(get_session)):
    return (await _out_many(session, [await _get(session, ctx.project.id, experiment_id)]))[0]


@router.patch("/{experiment_id}", response_model=ExperimentOut)
@limiter.limit("120/minute")
async def update_experiment(request: Request, experiment_id: uuid.UUID, body: ExperimentPatch,
                            ctx: ProjectCtx = project_access("editor"), session: AsyncSession = Depends(get_session)):
    e = await _get(session, ctx.project.id, experiment_id, lock=True)
    if e.voided_at is not None:
        raise HTTPException(409, "This record was voided and can no longer be edited")
    if body.expected_version != e.version:
        raise HTTPException(409, f"This record changed (you edited v{body.expected_version}, current is v{e.version}). "
                                 "Reload it and re-apply your edit.")
    sent = body.model_dump(mode="json", exclude_unset=True, exclude={"expected_version", "change_note"})
    if "links" in sent or "attachments" in sent:
        await _validate_refs(session, ctx.project.id, sent.get("links", e.links), sent.get("attachments", e.attachments), e.id)
    changed = []
    for k, v in sent.items():
        if k == "performed_at":
            v = body.performed_at
        if k == "outcome" and v is None:
            continue
        if _json_safe(getattr(e, k)) != _json_safe(v):
            setattr(e, k, v)
            changed.append(k)
    if not changed:
        return (await _out_many(session, [e]))[0]
    e.version += 1
    e.updated_by, e.updated_at = ctx.user.id, datetime.now(timezone.utc)
    session.add(ExperimentVersion(experiment_id=e.id, project_id=e.project_id, version=e.version, snapshot=snapshot(e),
                                  changed_fields=changed, change_note=body.change_note, changed_by=ctx.user.id))
    await session.flush()
    await project_index.index_experiment(session, e)
    await project_index.invalidate_derived(session, e.project_id, "experiment", e.id)
    await audit.log(session, ctx.user, "experiment_updated", str(e.id), {"version": e.version, "fields": changed}, audit.client_ip(request))
    await session.commit()
    await session.refresh(e)
    return (await _out_many(session, [e]))[0]


@router.delete("/{experiment_id}", response_model=ExperimentOut)
async def void_experiment(request: Request, experiment_id: uuid.UUID, reason: str = Query(..., min_length=3, max_length=500),
                          ctx: ProjectCtx = project_access("editor"), session: AsyncSession = Depends(get_session)):
    """Void (soft delete): history is kept, the record leaves lists, search and the retrieval index."""
    e = await _get(session, ctx.project.id, experiment_id, lock=True)
    if e.voided_at is not None:
        raise HTTPException(409, "Already voided")
    e.voided_at, e.voided_by = datetime.now(timezone.utc), ctx.user.id
    e.version += 1
    e.updated_by, e.updated_at = ctx.user.id, e.voided_at
    session.add(ExperimentVersion(experiment_id=e.id, project_id=e.project_id, version=e.version, snapshot=snapshot(e),
                                  changed_fields=["voided"], change_note=f"voided: {reason}", changed_by=ctx.user.id))
    await session.flush()
    await project_index.index_experiment(session, e)      # voided -> chunks removed
    await project_index.invalidate_derived(session, e.project_id, "experiment", e.id)
    await audit.log(session, ctx.user, "experiment_voided", str(e.id), {"reason": reason}, audit.client_ip(request))
    await session.commit()
    await session.refresh(e)
    return (await _out_many(session, [e]))[0]


@router.get("/{experiment_id}/versions", response_model=list[VersionOut])
async def list_versions(experiment_id: uuid.UUID, ctx: ProjectCtx = project_access("viewer"), session: AsyncSession = Depends(get_session)):
    await _get(session, ctx.project.id, experiment_id)
    rows = (await session.execute(select(ExperimentVersion).where(
        ExperimentVersion.experiment_id == experiment_id, ExperimentVersion.project_id == ctx.project.id)
        .order_by(ExperimentVersion.version.desc()))).scalars().all()
    names = await _names(session, {r.changed_by for r in rows})
    return [VersionOut(version=r.version, changed_fields=r.changed_fields, change_note=r.change_note, changed_by=r.changed_by,
                       changed_by_name=names.get(r.changed_by), changed_at=r.changed_at) for r in rows]


@router.get("/{experiment_id}/versions/{version}", response_model=VersionDetail)
async def get_version(experiment_id: uuid.UUID, version: int, ctx: ProjectCtx = project_access("viewer"),
                      session: AsyncSession = Depends(get_session)):
    """The record exactly as it was at `version` - what a citation in an AI answer points to."""
    await _get(session, ctx.project.id, experiment_id)
    r = (await session.execute(select(ExperimentVersion).where(
        ExperimentVersion.experiment_id == experiment_id, ExperimentVersion.project_id == ctx.project.id,
        ExperimentVersion.version == version))).scalar_one_or_none()
    if r is None:
        raise HTTPException(404, "Version not found")
    names = await _names(session, {r.changed_by})
    return VersionDetail(version=r.version, changed_fields=r.changed_fields, change_note=r.change_note, changed_by=r.changed_by,
                         changed_by_name=names.get(r.changed_by), changed_at=r.changed_at, snapshot=r.snapshot)


def _pmap(params: list) -> dict[str, dict]:
    return {" ".join(str(p.get("name", "")).lower().split()): p for p in params or []}


@router.get("/{experiment_id}/compare")
async def compare(experiment_id: uuid.UUID, other: uuid.UUID = Query(..., alias="with"),
                  ctx: ProjectCtx = project_access("viewer"), session: AsyncSession = Depends(get_session)):
    """Parameter-by-parameter comparison of two records of this project (both ids are checked against the project)."""
    a = await _get(session, ctx.project.id, experiment_id)
    b = await _get(session, ctx.project.id, other)
    pa, pb = _pmap(a.parameters), _pmap(b.parameters)
    rows = []
    for key in sorted(set(pa) | set(pb)):
        x, y = pa.get(key), pb.get(key)
        row: dict[str, Any] = {"parameter": (x or y)["name"], "a": x and (x.get("value") if x.get("value") is not None else x.get("text_value")),
                               "b": y and (y.get("value") if y.get("value") is not None else y.get("text_value")),
                               "unit_a": x and x.get("unit"), "unit_b": y and y.get("unit")}
        if x and y and isinstance(row["a"], (int, float)) and isinstance(row["b"], (int, float)):
            if (x.get("unit") or "") != (y.get("unit") or ""):
                row["note"] = "units differ - not comparable"
            else:
                row["delta"] = row["b"] - row["a"]
                row["pct"] = round((row["b"] - row["a"]) / abs(row["a"]) * 100, 2) if row["a"] else None
        rows.append(row)
    names = lambda e, f: sorted({str(i.get("name", i)) if isinstance(i, dict) else str(i) for i in getattr(e, f) or []})  # noqa: E731
    return {"a": {"id": str(a.id), "identifier": a.identifier, "version": a.version, "outcome": a.outcome},
            "b": {"id": str(b.id), "identifier": b.identifier, "version": b.version, "outcome": b.outcome},
            "parameters": rows,
            "reagents": {"only_a": sorted(set(names(a, "reagents")) - set(names(b, "reagents"))),
                         "only_b": sorted(set(names(b, "reagents")) - set(names(a, "reagents")))},
            "equipment": {"only_a": sorted(set(names(a, "equipment")) - set(names(b, "equipment"))),
                          "only_b": sorted(set(names(b, "equipment")) - set(names(a, "equipment")))},
            "conditions": {k: {"a": a.conditions.get(k), "b": b.conditions.get(k)}
                           for k in sorted(set(a.conditions) | set(b.conditions)) if a.conditions.get(k) != b.conditions.get(k)}}


@router.get("/{experiment_id}/analysis")
async def analysis(experiment_id: uuid.UUID, ctx: ProjectCtx = project_access("viewer"), session: AsyncSession = Depends(get_session)):
    """Troubleshooting facts computed from the project's own records: unusual values, similar runs, successful-vs-failed
    contrasts, missing parameters. No model involved; every finding carries experiment ids and versions."""
    target = await _get(session, ctx.project.id, experiment_id)
    rows = (await session.execute(select(Experiment).where(Experiment.project_id == ctx.project.id,
                                                           Experiment.voided_at.is_(None)))).scalars().all()
    snap = lambda e: {c: getattr(e, c) for c in ("id", "identifier", "version", "outcome", "parameters", "reagents",  # noqa: E731
                                                  "equipment", "conditions")}
    return project_troubleshoot.analyse(snap(target), [snap(r) for r in rows])
