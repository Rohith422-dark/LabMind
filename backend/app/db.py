from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

_engine = None
_maker = None


class Base(DeclarativeBase):
    pass


def engine():
    global _engine, _maker
    if _engine is None:
        _engine = create_async_engine(get_settings().async_url, pool_size=10, max_overflow=10)
        _maker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def session_maker() -> async_sessionmaker[AsyncSession]:
    engine()
    return _maker


async def get_session():
    async with session_maker()() as s:
        yield s
