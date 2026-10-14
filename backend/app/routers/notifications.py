import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import require
from app.models.tables import Notification, User

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: uuid.UUID
    kind: str | None = None
    message: str
    link: str | None
    is_read: bool
    created_at: datetime
    model_config = {"from_attributes": True}


@router.get("", response_model=list[NotificationOut])
async def list_notifications(user: User = require("self.view"), session: AsyncSession = Depends(get_session)):
    return (await session.execute(select(Notification).where(Notification.user_id == user.id)
                                  .order_by(Notification.created_at.desc()).limit(50))).scalars().all()


@router.patch("/{notification_id}/read", response_model=NotificationOut)
async def mark_read(notification_id: uuid.UUID, user: User = require("self.view"),
                    session: AsyncSession = Depends(get_session)):
    n = await session.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise HTTPException(404, "Notification not found")
    n.is_read = True
    await session.commit()
    return n
