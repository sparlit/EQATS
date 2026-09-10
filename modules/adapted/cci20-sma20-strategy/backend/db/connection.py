from __future__ import annotations

import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


"""
Database connection factory.

Two drivers — one per execution context:
  • Async (asyncpg)  — FastAPI Lambda: non-blocking, one connection per Lambda instance.
  • Sync  (psycopg2) — Scanner Lambda: runs outside async event loop.

Environment variables
  DATABASE_URL       postgresql+asyncpg://user:pass@host/db?sslmode=require
  DATABASE_URL_SYNC  postgresql://user:pass@host/db?sslmode=require
                     (auto-derived from DATABASE_URL if omitted)
"""

import os
from typing import TYPE_CHECKING

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

# ── Async engine (API Lambda) ──────────────────────────────────────────────────

_async_engine = None
_async_session_factory: async_sessionmaker | None = None


def _build_async_engine():
    global _async_engine, _async_session_factory
    if _async_engine is None:
        url = os.environ["DATABASE_URL"]
        if not url.startswith("postgresql+asyncpg://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        # asyncpg expects ssl=require instead of sslmode=require
        url = url.replace("?sslmode=require", "?ssl=require")

        _async_engine = create_async_engine(
            url,
            pool_size=1,  # Lambda: one connection per warm instance
            max_overflow=0,
            pool_pre_ping=True,  # detect Neon auto-paused connections
            pool_recycle=280,  # recycle before Neon 300 s idle timeout
            echo=os.environ.get("SQL_ECHO", "").lower() == "true",
        )
        _async_session_factory = async_sessionmaker(
            _async_engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )


async def get_db() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency — yields a managed async session."""
    _build_async_engine()
    assert _async_session_factory is not None
    async with _async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Sync engine (Scanner Lambda) ──────────────────────────────────────────────


def get_sync_session() -> Generator[Session]:
    """Sync session for the scanner (psycopg2). Disposes engine on exit."""
    raw = os.environ.get("DATABASE_URL_SYNC") or os.environ["DATABASE_URL"]
    url = raw.replace("+asyncpg", "").replace("postgresql+psycopg2://", "postgresql://")
    if not url.startswith("postgresql://"):
        url = url.replace("postgres://", "postgresql://", 1)

    engine = create_engine(url, pool_pre_ping=True, pool_size=1, max_overflow=0)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()
