"""Async engine and session factory.

The engine is process-wide and created lazily, so importing this module never
opens a connection - which matters for the worker, for Alembic, and for tests
that swap in their own engine.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from api.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.sqlalchemy_url,
            echo=settings.debug,
            pool_pre_ping=True,
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        # expire_on_commit=False keeps loaded objects readable after commit,
        # which request handlers rely on when serializing a response.
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


def set_sessionmaker(factory: async_sessionmaker[AsyncSession] | None) -> None:
    """Override the factory - the seam tests use to point at their own engine."""
    global _sessionmaker
    _sessionmaker = factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """A session that commits on success and rolls back on failure.

    For the worker and other non-request callers; FastAPI handlers get a
    session from `api.deps.get_session` instead.
    """
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
