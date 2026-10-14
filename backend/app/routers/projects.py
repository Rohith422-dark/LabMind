"""Projects, ownership, collaborators and the password-gated access-request workflow.

Password workflow (a password alone never grants access):
  1. the owner sets a project password (stored as an argon2id hash, never returned or logged);
  2. a signed-in non-member sends the project id + password to POST /projects/{id}/access-requests;
  3. a correct password only creates a PENDING request and notifies the owner (wrong/locked/no password -> one generic 403);
  4. the owner approves with an explicit role (viewer/editor) -> membership row; or denies. Revoking deletes the row.
"""
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session, session_maker
from app.deps import require
from app.limiter import limiter
from app.models.tables import (
    Project, ProjectAccessRequest, ProjectMember, ProjectPasswordAttempt, User,
)
from app.services import audit, project_docs, project_memory
from app.services.access import ProjectCtx, project_access
from app.services.notify import notify

router = APIRouter(prefix="/projects", tags=["projects"])
ph = PasswordHasher()
_DUMMY_HASH = ph.hash("not-a-real-password")      # verified against when a project has no password (uniform timing)
MAX_FAILURES, LOCK_MINUTES = 5, 15
GENERIC_DENIAL = "Access could not be requested. Check the project ID and password."


def _clean_tags(v: list[str]) -> list[str]:
    return [t.strip()[:40] for t in v if t and t.strip()][:20]


class ProjectIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    objectives: str | None = Field(default=None, max_length=4000)
    domain: str | None = Field(default=None, max_length=80)
    tags: list[str] = []
    password: str | None = Field(default=None, min_length=8, max_length=128)

    _tags = field_validator("tags")(_clean_tags)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("name is too short")
        return v


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    objectives: str | None = Field(default=None, max_length=4000)
    domain: str | None = Field(default=None, max_length=80)
    tags: list[str] | None = None

    _tags = field_validator("tags")(lambda v: v if v is None else _clean_tags(v))


class PasswordIn(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class ProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    objectives: str | None = None
    domain: str | None = None
    tags: list[str] = []
    owner_id: uuid.UUID
    owner_name: str | None = None
    role: str
    archived: bool
    has_password: bool
    created_at: datetime
    updated_at: datetime
    experiments: int = 0
    documents: int = 0
    members: int = 0
    pending_access_requests: int = 0


class MemberOut(BaseModel):
    user_id: uuid.UUID
    username: str
    full_name: str
    role: str
    added_at: datetime


class MemberIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    role: Literal["viewer", "editor"]


class RoleIn(BaseModel):
    role: Literal["viewer", "editor"]


class AccessRequestIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    message: str | None = Field(default=None, max_length=500)


class AccessRequestOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID
    username: str | None = None
    full_name: str | None = None
    project_name: str | None = None
    message: str | None = None
    status: str
    role_granted: str | None = None
    created_at: datetime
    decided_at: datetime | None = None


class DecisionIn(BaseModel):
    approve: bool
    role: Literal["viewer", "editor"] = "viewer"


async def _out(session: AsyncSession, p: Project, role: str) -> ProjectOut:
    counts = (await session.execute(text(
        "SELECT (SELECT count(*) FROM experiments WHERE project_id=:p AND voided_at IS NULL) AS e, "
        "(SELECT count(*) FROM project_documents WHERE project_id=:p AND status='ready') AS d, "
        "(SELECT count(*) FROM project_members WHERE project_id=:p) AS m, "
        "(SELECT count(*) FROM project_access_requests WHERE project_id=:p AND status='pending') AS r"), {"p": p.id})).one()
    owner = await session.get(User, p.owner_id)
    return ProjectOut(
        id=p.id, name=p.name, description=p.description, objectives=p.objectives, domain=p.domain, tags=p.tags or [],
        owner_id=p.owner_id, owner_name=owner.full_name if owner else None, role=role, archived=p.archived_at is not None,
        has_password=p.password_hash is not None, created_at=p.created_at, updated_at=p.updated_at,
        experiments=counts.e, documents=counts.d, members=counts.m,
        pending_access_requests=counts.r if role == "owner" else 0)


# ------------------------------------------------------------------ projects
@router.post("", response_model=ProjectOut, status_code=201)
@limiter.limit("30/minute")
async def create_project(request: Request, body: ProjectIn, user: User = require("projects.use"),
                         session: AsyncSession = Depends(get_session)):
    p = Project(name=body.name, description=body.description, objectives=body.objectives, domain=body.domain,
                tags=body.tags, owner_id=user.id, password_hash=ph.hash(body.password) if body.password else None)
    session.add(p)
    await session.flush()
    session.add(ProjectMember(project_id=p.id, user_id=user.id, role="owner", added_by=user.id))
    await audit.log(session, user, "project_created", str(p.id), {"name": p.name, "password_set": bool(body.password)},
                    audit.client_ip(request))
    await session.commit()
    return await _out(session, p, "owner")


@router.get("", response_model=list[ProjectOut])
async def list_projects(include_archived: bool = False, user: User = require("projects.use"),
                        session: AsyncSession = Depends(get_session)):
    """Only projects the caller is a member of - there is no way to list or search other people's projects."""
    q = select(Project, ProjectMember.role).join(ProjectMember, ProjectMember.project_id == Project.id).where(
        ProjectMember.user_id == user.id).order_by(Project.updated_at.desc())
    if not include_archived:
        q = q.where(Project.archived_at.is_(None))
    return [await _out(session, p, role) for p, role in (await session.execute(q)).all()]


@router.get("/access-requests/mine", response_model=list[AccessRequestOut])
async def my_access_requests(user: User = require("projects.use"), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(text(
        "SELECT r.id, r.project_id, r.user_id, r.message, r.status, r.role_granted, r.created_at, r.decided_at, p.name AS project_name "
        "FROM project_access_requests r JOIN projects p ON p.id = r.project_id WHERE r.user_id = :u ORDER BY r.created_at DESC"),
        {"u": user.id})).mappings().all()
    return [AccessRequestOut(**dict(r)) for r in rows]


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(ctx: ProjectCtx = project_access("viewer"), session: AsyncSession = Depends(get_session)):
    return await _out(session, ctx.project, ctx.role)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(request: Request, body: ProjectPatch, ctx: ProjectCtx = project_access("owner"),
                         session: AsyncSession = Depends(get_session)):
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        if k == "name" and v is not None:
            v = v.strip()
        setattr(ctx.project, k, v)
    ctx.project.updated_at = func.now()
    await audit.log(session, ctx.user, "project_updated", str(ctx.project.id), {"fields": sorted(changes)}, audit.client_ip(request))
    await session.commit()
    await session.refresh(ctx.project)
    return await _out(session, ctx.project, ctx.role)


@router.post("/{project_id}/archive", response_model=ProjectOut)
async def archive_project(request: Request, ctx: ProjectCtx = project_access("owner", allow_archived_write=True),
                          session: AsyncSession = Depends(get_session)):
    ctx.project.archived_at = datetime.now(timezone.utc)
    await audit.log(session, ctx.user, "project_archived", str(ctx.project.id), ip=audit.client_ip(request))
    await session.commit()
    return await _out(session, ctx.project, ctx.role)


@router.post("/{project_id}/restore", response_model=ProjectOut)
async def restore_project(request: Request, ctx: ProjectCtx = project_access("owner", allow_archived_write=True),
                          session: AsyncSession = Depends(get_session)):
    ctx.project.archived_at = None
    await audit.log(session, ctx.user, "project_restored", str(ctx.project.id), ip=audit.client_ip(request))
    await session.commit()
    return await _out(session, ctx.project, ctx.role)


@router.delete("/{project_id}", status_code=204)
async def delete_project(request: Request, confirm_name: str = Query(..., description="must equal the project name"),
                         ctx: ProjectCtx = project_access("owner", allow_archived_write=True),
                         session: AsyncSession = Depends(get_session)):
    """Permanent. Cascades to experiments + their history, documents, chunks/embeddings, conversations, project memories and
    stored files. The audit trail entry is kept (it holds the id and name only)."""
    if confirm_name.strip() != ctx.project.name:
        raise HTTPException(422, "confirm_name does not match the project name")
    pid, name = ctx.project.id, ctx.project.name
    members = (await session.execute(select(ProjectMember.user_id).where(ProjectMember.project_id == pid))).scalars().all()
    await audit.log(session, ctx.user, "project_deleted", str(pid), {"name": name}, audit.client_ip(request))
    await session.execute(delete(Project).where(Project.id == pid))
    for uid in members:
        if uid != ctx.user.id:
            await notify(session, uid, f"Project '{name}' was deleted by its owner.", None, kind="project")
    await session.commit()
    project_docs.remove_project_files(pid)


# ------------------------------------------------------------------ password (owner only)
@router.put("/{project_id}/password", status_code=204)
async def set_password(request: Request, body: PasswordIn, ctx: ProjectCtx = project_access("owner"),
                       session: AsyncSession = Depends(get_session)):
    ctx.project.password_hash = ph.hash(body.password)
    await audit.log(session, ctx.user, "project_password_set", str(ctx.project.id), ip=audit.client_ip(request))  # never the value
    await session.commit()


@router.delete("/{project_id}/password", status_code=204)
async def clear_password(request: Request, ctx: ProjectCtx = project_access("owner"),
                         session: AsyncSession = Depends(get_session)):
    ctx.project.password_hash = None
    await audit.log(session, ctx.user, "project_password_cleared", str(ctx.project.id), ip=audit.client_ip(request))
    await session.commit()


# ------------------------------------------------------------------ members
@router.get("/{project_id}/members", response_model=list[MemberOut])
async def list_members(ctx: ProjectCtx = project_access("viewer"), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(ProjectMember, User).join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == ctx.project.id).order_by(ProjectMember.created_at))).all()
    return [MemberOut(user_id=u.id, username=u.username, full_name=u.full_name, role=m.role, added_at=m.created_at) for m, u in rows]


@router.post("/{project_id}/members", response_model=MemberOut, status_code=201)
async def add_member(request: Request, body: MemberIn, ctx: ProjectCtx = project_access("owner"),
                     session: AsyncSession = Depends(get_session)):
    target = (await session.execute(select(User).where(User.username == body.username.strip()))).scalar_one_or_none()
    if target is None:
        raise HTTPException(404, "User not found")
    existing = (await session.execute(select(ProjectMember).where(
        ProjectMember.project_id == ctx.project.id, ProjectMember.user_id == target.id))).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "That user is already a member")
    m = ProjectMember(project_id=ctx.project.id, user_id=target.id, role=body.role, added_by=ctx.user.id)
    session.add(m)
    await session.flush()
    await notify(session, target.id, f"You were added to project '{ctx.project.name}' as {body.role}.", "/projects", kind="project")
    await audit.log(session, ctx.user, "project_member_added", str(ctx.project.id),
                    {"user": target.username, "role": body.role}, audit.client_ip(request))
    await session.commit()
    return MemberOut(user_id=target.id, username=target.username, full_name=target.full_name, role=m.role, added_at=m.created_at)


@router.patch("/{project_id}/members/{user_id}", response_model=MemberOut)
async def change_member_role(request: Request, user_id: uuid.UUID, body: RoleIn,
                             ctx: ProjectCtx = project_access("owner"), session: AsyncSession = Depends(get_session)):
    m = (await session.execute(select(ProjectMember).where(
        ProjectMember.project_id == ctx.project.id, ProjectMember.user_id == user_id))).scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "Member not found")
    if m.role == "owner":
        raise HTTPException(409, "The owner's role cannot be changed")
    m.role = body.role
    await audit.log(session, ctx.user, "project_member_role_changed", str(ctx.project.id),
                    {"user_id": str(user_id), "role": body.role}, audit.client_ip(request))
    await session.commit()
    u = await session.get(User, user_id)
    return MemberOut(user_id=u.id, username=u.username, full_name=u.full_name, role=m.role, added_at=m.created_at)


@router.delete("/{project_id}/members/{user_id}", status_code=204)
async def remove_member(request: Request, user_id: uuid.UUID, ctx: ProjectCtx = project_access("viewer"),
                        session: AsyncSession = Depends(get_session)):
    """The owner may revoke anyone; any member may leave. The owner cannot be removed."""
    if not ctx.is_owner and user_id != ctx.user.id:
        raise HTTPException(403, "Only the owner can remove other members")
    m = (await session.execute(select(ProjectMember).where(
        ProjectMember.project_id == ctx.project.id, ProjectMember.user_id == user_id))).scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "Member not found")
    if m.role == "owner":
        raise HTTPException(409, "The owner cannot be removed; delete or archive the project instead")
    await session.delete(m)
    await project_memory.purge_user_project_state(session, user_id, ctx.project.id)
    if user_id != ctx.user.id:
        await notify(session, user_id, f"Your access to project '{ctx.project.name}' was revoked.", None, kind="project")
    await audit.log(session, ctx.user, "project_member_removed", str(ctx.project.id), {"user_id": str(user_id)}, audit.client_ip(request))
    await session.commit()


# ------------------------------------------------------------------ password-gated access requests
async def _record_failure(project_id: uuid.UUID, user_id: uuid.UUID) -> None:
    async with session_maker()() as s:     # own transaction: must persist even though the request then fails
        row = await s.get(ProjectPasswordAttempt, (project_id, user_id))
        if row is None:
            row = ProjectPasswordAttempt(project_id=project_id, user_id=user_id, failures=0)
            s.add(row)
        row.failures += 1
        if row.failures >= MAX_FAILURES:
            row.locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCK_MINUTES)
            row.failures = 0
        await s.commit()


@router.post("/{project_id}/access-requests", response_model=AccessRequestOut, status_code=201)
@limiter.limit("20/minute")
async def request_access(request: Request, project_id: uuid.UUID, body: AccessRequestIn,
                         user: User = require("projects.use"), session: AsyncSession = Depends(get_session)):
    """Prove knowledge of the project password -> a PENDING request for the owner. Grants nothing by itself."""
    project = await session.get(Project, project_id)
    attempt = await session.get(ProjectPasswordAttempt, (project_id, user.id)) if project else None
    locked = bool(attempt and attempt.locked_until and attempt.locked_until > datetime.now(timezone.utc))
    ok = False
    try:
        ok = ph.verify(project.password_hash if project and project.password_hash else _DUMMY_HASH, body.password)
    except VerifyMismatchError:
        ok = False
    ok = ok and project is not None and project.password_hash is not None and not locked
    if not ok:
        if project is not None and project.password_hash is not None and not locked:
            await _record_failure(project_id, user.id)
        await audit.log_standalone(user, "project_access_denied", str(project_id), {"locked": locked}, audit.client_ip(request))
        raise HTTPException(403, GENERIC_DENIAL)
    if attempt:
        attempt.failures, attempt.locked_until = 0, None
    if (await session.execute(select(ProjectMember.id).where(ProjectMember.project_id == project_id,
                                                              ProjectMember.user_id == user.id))).first():
        raise HTTPException(409, "You already have access to this project")
    pending = (await session.execute(select(ProjectAccessRequest).where(
        ProjectAccessRequest.project_id == project_id, ProjectAccessRequest.user_id == user.id,
        ProjectAccessRequest.status == "pending"))).scalar_one_or_none()
    if pending:
        raise HTTPException(409, "You already have a pending request for this project")
    req = ProjectAccessRequest(project_id=project_id, user_id=user.id, message=body.message)
    session.add(req)
    await session.flush()
    await notify(session, project.owner_id, f"{user.full_name} asked for access to project '{project.name}'.",
                 f"/projects/{project.id}", kind="project")
    await audit.log(session, user, "project_access_requested", str(project_id), ip=audit.client_ip(request))
    await session.commit()
    return AccessRequestOut(id=req.id, project_id=project_id, user_id=user.id, username=user.username, full_name=user.full_name,
                            project_name=project.name, message=req.message, status=req.status, created_at=req.created_at)


@router.get("/{project_id}/access-requests", response_model=list[AccessRequestOut])
async def list_access_requests(status: str = "pending", ctx: ProjectCtx = project_access("owner"),
                               session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(text(
        "SELECT r.id, r.project_id, r.user_id, u.username, u.full_name, r.message, r.status, r.role_granted, r.created_at, r.decided_at "
        "FROM project_access_requests r JOIN users u ON u.id = r.user_id WHERE r.project_id = :p AND r.status = :s ORDER BY r.created_at"),
        {"p": ctx.project.id, "s": status})).mappings().all()
    return [AccessRequestOut(**dict(r)) for r in rows]


@router.post("/{project_id}/access-requests/{request_id}/decision", response_model=AccessRequestOut)
async def decide_access_request(request: Request, request_id: uuid.UUID, body: DecisionIn,
                                ctx: ProjectCtx = project_access("owner"), session: AsyncSession = Depends(get_session)):
    req = (await session.execute(select(ProjectAccessRequest).where(
        ProjectAccessRequest.id == request_id, ProjectAccessRequest.project_id == ctx.project.id).with_for_update())).scalar_one_or_none()
    if req is None:
        raise HTTPException(404, "Request not found")
    if req.status != "pending":
        raise HTTPException(409, f"This request was already {req.status}")
    req.status = "approved" if body.approve else "denied"
    req.decided_by, req.decided_at = ctx.user.id, datetime.now(timezone.utc)
    if body.approve:
        req.role_granted = body.role
        session.add(ProjectMember(project_id=ctx.project.id, user_id=req.user_id, role=body.role, added_by=ctx.user.id))
    await notify(session, req.user_id, f"Your access request for project '{ctx.project.name}' was "
                 + (f"approved ({body.role})." if body.approve else "declined."), "/projects" if body.approve else None, kind="project")
    await audit.log(session, ctx.user, "project_access_decided", str(ctx.project.id),
                    {"request_id": str(req.id), "approved": body.approve, "role": body.role if body.approve else None},
                    audit.client_ip(request))
    await session.commit()
    u = await session.get(User, req.user_id)
    return AccessRequestOut(id=req.id, project_id=req.project_id, user_id=req.user_id, username=u.username, full_name=u.full_name,
                            message=req.message, status=req.status, role_granted=req.role_granted, created_at=req.created_at,
                            decided_at=req.decided_at)
