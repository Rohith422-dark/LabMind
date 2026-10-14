import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Notification


async def notify(session: AsyncSession, user_id: uuid.UUID, message: str, link: str | None = None,
                 kind: str | None = None) -> None:
    session.add(Notification(user_id=user_id, message=message, link=link, kind=kind))
    await session.flush()
