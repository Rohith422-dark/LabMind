from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.deps import make_token, require
from app.limiter import limiter
from app.models.tables import User
from app.permissions import permissions_for
from app.schemas.auth import DemoUserCard, LoginIn, LoginOut, MeOut, UserOut
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])
ph = PasswordHasher()


def _login_out(user: User) -> LoginOut:
    return LoginOut(token=make_token(user), user=UserOut.model_validate(user),
                    permissions=permissions_for(user.role))


@router.post("/login", response_model=LoginOut)
@limiter.limit("20/minute")
async def login(request: Request, body: LoginIn, session: AsyncSession = Depends(get_session)):
    user = (await session.execute(select(User).where(User.username == body.username))).scalar_one_or_none()
    ok = False
    if user:
        try:
            ok = ph.verify(user.password_hash, body.password)
        except VerifyMismatchError:
            ok = False
    if not ok:
        await audit.log(session, None, "login_failed", body.username, ip=audit.client_ip(request))
        await session.commit()
        raise HTTPException(401, "Invalid username or password")
    await audit.log(session, user, "login", user.username, ip=audit.client_ip(request))
    await session.commit()
    return _login_out(user)


@router.get("/demo-users", response_model=list[DemoUserCard])
async def demo_users(session: AsyncSession = Depends(get_session)):
    """Public name/role cards for the one-click demo login (no secrets)."""
    rows = (await session.execute(select(User).order_by(User.created_at))).scalars().all()
    return [DemoUserCard(username=u.username, full_name=u.full_name, role=u.role, department=u.department)
            for u in rows]


@router.post("/demo-login", response_model=LoginOut)
@limiter.limit("30/minute")
async def demo_login(request: Request, username: str, session: AsyncSession = Depends(get_session)):
    """One-click login for the demo cards. Only available when DEMO_CARDS=1 or DEMO_MODE=1."""
    if not (get_settings().demo_mode or get_settings().demo_cards):
        raise HTTPException(404, "Not found")
    user = (await session.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if user is None:
        raise HTTPException(404, "Unknown user")
    await audit.log(session, user, "login", user.username, {"via": "demo_card"}, audit.client_ip(request))
    await session.commit()
    return _login_out(user)


@router.get("/me", response_model=MeOut)
async def me(user: User = require("self.view")):
    return MeOut(user=UserOut.model_validate(user), permissions=permissions_for(user.role))
