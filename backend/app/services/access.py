"""Project authorization: the ONLY place that decides whether a user may touch a project.

Rules
* Access = a row in project_members (the owner has one with role 'owner'). Nothing else grants access: not a global
  role (admins included), not knowing the project id, not knowing the project password.
* A caller who is not a member gets 404 (indistinguishable from "no such project"), so ids cannot be probed.
* Every child resource is looked up WITH its project id (`get_child`), so a document/experiment id from another
  project is 404 even when the caller is a member of the project named in the URL.
"""
import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import require
from app.models.tables import Project, ProjectMember, User

RANK = {"viewer": 1, "editor": 2, "owner": 3}
NOT_FOUND = "Project not found"


@dataclass
class ProjectCtx:
    project: Project
    role: str
    user: User

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"

    def can(self, minimum: str) -> bool:
        return RANK[self.role] >= RANK[minimum]


async def role_of(session: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID) -> str | None:
    return (await session.execute(select(ProjectMember.role).where(
        ProjectMember.project_id == project_id, ProjectMember.user_id == user_id))).scalar_one_or_none()


async def load_ctx(session: AsyncSession, user: User, project_id: uuid.UUID, minimum: str = "viewer",
                   allow_archived_write: bool = False) -> ProjectCtx:
    role = await role_of(session, user.id, project_id)
    project = await session.get(Project, project_id) if role else None
    if role is None or project is None:
        raise HTTPException(404, NOT_FOUND)
    if RANK[role] < RANK[minimum]:
        raise HTTPException(403, f"This action needs the {minimum} role on the project")
    if minimum != "viewer" and project.archived_at is not None and not allow_archived_write:
        raise HTTPException(409, "This project is archived and read-only. Ask the owner to restore it.")
    return ProjectCtx(project, role, user)


def project_access(minimum: str = "viewer", allow_archived_write: bool = False):
    """Route dependency factory: authenticates, then requires membership with at least `minimum` on {project_id}."""
    async def dep(project_id: uuid.UUID, user: User = require("projects.use"),
                  session: AsyncSession = Depends(get_session)) -> ProjectCtx:
        return await load_ctx(session, user, project_id, minimum, allow_archived_write)
    return Depends(dep)


async def get_child(session: AsyncSession, model, project_id: uuid.UUID, child_id: uuid.UUID, what: str):
    """Fetch child.id == child_id AND child.project_id == project_id, else 404 (IDOR guard)."""
    row = (await session.execute(select(model).where(model.id == child_id, model.project_id == project_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"{what} not found")
    return row


async def accessible_project_ids(session: AsyncSession, user: User) -> list[uuid.UUID]:
    return list((await session.execute(select(ProjectMember.project_id).where(ProjectMember.user_id == user.id))).scalars())
