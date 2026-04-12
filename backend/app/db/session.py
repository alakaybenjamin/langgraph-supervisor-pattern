from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

_connect_args: dict = {}
if settings.DB_SCHEMA and settings.DB_SCHEMA != "public":
    _connect_args["server_settings"] = {"search_path": settings.DB_SCHEMA}

engine = create_async_engine(
    settings.async_database_url,
    echo=False,
    connect_args=_connect_args,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncSession:  # type: ignore[misc]
    async with async_session() as session:
        yield session
