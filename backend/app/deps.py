import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.models.tables import User
from app.permissions import PERMISSIONS
from app.services import audit

bearer = HTTPBearer(auto_error=False)
JWT_HOURS = 8


def make_token(user: User) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=JWT_HOURS)
    return jwt.encode({"sub": str(user.id), "role": user.role, "exp": exp},
                      get_settings().jwt_secret, algorithm="HS256")


async def current_user(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                       session: AsyncSession = Depends(get_session)) -> User:
    if creds is None:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(creds.credentials, get_settings().jwt_secret, algorithms=["HS256"])
        uid = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(401, "Invalid or expired token")
    user = await session.get(User, uid)
    if user is None:
        raise HTTPException(401, "Unknown user")
    request.state.user = user
    return user


def require(permission: str):
    """Route dependency: authenticates, then checks the role against permissions.py."""
    if permission not in PERMISSIONS:
        raise KeyError(f"unknown permission {permission}")

    async def dep(request: Request, user: User = Depends(current_user)) -> User:
        if user.role not in PERMISSIONS[permission]:
            await audit.log_standalone(user, "access_denied", f"{request.method} {request.url.path}",
                                       {"permission": permission}, audit.client_ip(request))
            raise HTTPException(403, "Not permitted for your role")
        return user

    dep._permission = permission  # introspected by tests/test_rbac.py
    return Depends(dep)
