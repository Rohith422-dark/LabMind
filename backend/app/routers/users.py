import uuid

from argon2 import PasswordHasher
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import require
from app.models.tables import User
from app.schemas.auth import RoleUpdate, UserCreate, UserOut
from app.services import audit

router = APIRouter(prefix="/users", tags=["users"])
ph = PasswordHasher()


@router.get("", response_model=list[UserOut])
async def list_users(admin: User = require("users.manage"), session: AsyncSession = Depends(get_session)):
    return (await session.execute(select(User).order_by(User.created_at))).scalars().all()


@router.post("", response_model=UserOut, status_code=201)
async def create_user(request: Request, body: UserCreate, admin: User = require("users.manage"),
                      session: AsyncSession = Depends(get_session)):
    user = User(username=body.username, password_hash=ph.hash(body.password), full_name=body.full_name,
                role=body.role, department=body.department)
    session.add(user)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "Username already exists")
    await audit.log(session, admin, "user_created", user.username, {"role": user.role}, audit.client_ip(request))
    await session.commit()
    return user


@router.patch("/{user_id}/role", response_model=UserOut)
async def set_role(request: Request, user_id: uuid.UUID, body: RoleUpdate, admin: User = require("users.manage"),
                   session: AsyncSession = Depends(get_session)):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if user.id == admin.id:
        raise HTTPException(409, "You cannot change your own role")
    old = user.role
    user.role = body.role
    await audit.log(session, admin, "role_changed", user.username, {"from": old, "to": body.role},
                    audit.client_ip(request))
    await session.commit()
    return user
