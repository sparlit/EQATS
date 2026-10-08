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


"""Shared SQLAlchemy engine factory.

Centralizes engine creation so every database engine in the project follows the
same connection-pooling policy. This exists to enforce one rule across the whole
codebase, including all broker ``master_contract_db.py`` modules:

    All SQLite engines MUST use NullPool.

With NullPool each operation gets a fresh connection that is closed immediately
after use, so no file descriptors to the SQLite database file accumulate. A real
pool (the SQLAlchemy default QueuePool, or an explicit ``pool_size``/``max_overflow``)
holds connections open per worker thread and leaks descriptors over the lifetime
of the long-running Gunicorn/eventlet process.

StaticPool must NOT be used for SQLite: a single shared connection causes
"bad parameter or other API misuse" and "cannot commit - SQL statements in
progress" errors when concurrent requests corrupt the shared cursor state.

For non-SQLite backends (e.g. PostgreSQL) a normal connection pool is used.

SQLite pragmas (WAL journal mode, synchronous=NORMAL) are applied to every
connection process-wide by the listener in ``database/__init__.py`` — they do
not need to be set here.

See CLAUDE.md "SQLite Connection Pooling (NullPool)" and the reference
implementation in ``database/auth_db.py``.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool


def create_db_engine(database_url=None):
    """Create a SQLAlchemy engine with the project-wide pooling policy.

    Args:
        database_url: SQLAlchemy database URL. Falls back to the ``DATABASE_URL``
            environment variable when not provided.

    Returns:
        A configured SQLAlchemy ``Engine``. SQLite URLs use ``NullPool`` with
        ``check_same_thread=False``; other backends use a QueuePool.
    """
    database_url = database_url or os.getenv("DATABASE_URL")

    if database_url and "sqlite" in database_url:
        # SQLite: NullPool so each checkout creates a fresh connection that is
        # closed immediately. Session cleanup is handled by app.py
        # teardown_appcontext. StaticPool must NOT be used (see module docstring).
        return create_engine(
            database_url,
            poolclass=NullPool,
            connect_args={"check_same_thread": False},
        )

    # Non-SQLite backends (e.g. PostgreSQL): use a real connection pool.
    return create_engine(database_url, pool_size=50, max_overflow=100, pool_timeout=10)
