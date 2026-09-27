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


"""Unified connection factory for the Indian Quant data pipeline.

Provides PostgreSQL and Redis connections with sensible defaults.
Other projects on the same system use this to connect:

    from indian_quant.config.connections import get_engine, get_redis

Environment variables (with defaults):
    NSE_QUANT_PG_DSN     PostgreSQL connection string
    NSE_QUANT_REDIS_URL  Redis connection string
    REDIS_TTL            Cache TTL in seconds (default: 3600)
"""


import contextlib
import os
from functools import lru_cache

import redis
import sqlalchemy as sa

PG_DSN = os.getenv(
    "NSE_QUANT_PG_DSN",
    "postgresql://postgres:quant2026@127.0.0.1:5432/postgres",
)
REDIS_URL = os.getenv("NSE_QUANT_REDIS_URL", "redis://127.0.0.1:6379/0")
REDIS_TTL = int(os.getenv("REDIS_TTL", "3600"))


@lru_cache
def get_engine(dsn: str | None = None) -> sa.Engine:
    """Get a cached SQLAlchemy engine for PostgreSQL.

    Args:
        dsn: Connection string. If None, reads NSE_QUANT_PG_DSN env var.
    """
    dsn = dsn or PG_DSN
    connect_args = {}
    if dsn.startswith("postgresql"):
        connect_args["connect_timeout"] = 5
    return sa.create_engine(dsn, pool_size=2, max_overflow=5, pool_pre_ping=True, connect_args=connect_args)


@lru_cache
def get_redis(url: str | None = None) -> redis.Redis:
    """Get a cached Redis client.

    Args:
        url: Redis URL. If None, reads NSE_QUANT_REDIS_URL env var.
    """
    url = url or REDIS_URL
    return redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=3)


def ensure_schema(engine: sa.Engine | None = None) -> None:
    """Create PostgreSQL tables if they don't exist.

    Creates the cached_signals table and adds missing columns to support
    fundamentals, institutional data, and professional scores.
    """
    engine = engine or get_engine()
    meta = sa.MetaData()
    sa.Table(
        "cached_signals",
        meta,
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("exchange", sa.String(8), nullable=False),
        sa.PrimaryKeyConstraint("symbol", "exchange", name="cached_signals_pkey"),
        sa.Column("signal_date", sa.String(10)),
        sa.Column("segment", sa.String(8)),
        sa.Column("close", sa.Float),
        sa.Column("prev_close", sa.Float),
        sa.Column("ret_1d_pct", sa.Float),
        sa.Column("deliv_pct", sa.Float),
        sa.Column("deliv_z", sa.Float),
        sa.Column("vol_z", sa.Float),
        sa.Column("rsi", sa.Float),
        sa.Column("macd", sa.Float),
        sa.Column("macd_signal", sa.Float),
        sa.Column("sma_20", sa.Float),
        sa.Column("sma_50", sa.Float),
        sa.Column("atr_14", sa.Float),
        sa.Column("hi_streak", sa.Integer),
        sa.Column("signal_type", sa.String(16)),
        sa.Column("entry_zone_low", sa.Float),
        sa.Column("entry_zone_high", sa.Float),
        sa.Column("stop_loss", sa.Float),
        sa.Column("target_price", sa.Float),
        sa.Column("volume", sa.Float),
        sa.Column("cached_at", sa.String(32)),
        sa.Column("market_cap_class", sa.String(16)),
        sa.Column("market_cap_cr", sa.Float),
        sa.Column("security_type", sa.String(16)),
    )
    meta.create_all(engine)

    # Add columns to existing table if missing
    try:
        with engine.begin() as conn:
            for col, typedef in [
                ("market_cap_class", "VARCHAR(16)"),
                ("market_cap_cr", "FLOAT"),
                ("pe_trailing", "FLOAT"),
                ("price_to_book", "FLOAT"),
                ("roe", "FLOAT"),
                ("debt_to_equity", "FLOAT"),
                ("profit_margin", "FLOAT"),
                ("revenue_growth", "FLOAT"),
                ("dividend_yield", "FLOAT"),
                ("ev_to_ebitda", "FLOAT"),
                ("current_ratio", "FLOAT"),
                ("sector", "VARCHAR(64)"),
                ("industry", "VARCHAR(128)"),
                ("company_name", "TEXT"),
                ("fundamental_score", "FLOAT"),
                ("fii_pct", "FLOAT"),
                ("dii_pct", "FLOAT"),
                ("promoter_pct", "FLOAT"),
                ("fii_chg", "FLOAT"),
                ("dii_chg", "FLOAT"),
                ("promoter_chg", "FLOAT"),
                ("pledge_pct", "FLOAT"),
                ("institutional_score", "FLOAT"),
                ("professional_score", "FLOAT"),
                ("security_type", "VARCHAR(16)"),
            ]:
                with contextlib.suppress(Exception):
                    conn.execute(sa.text(f"ALTER TABLE cached_signals ADD COLUMN {col} {typedef}"))
    except Exception:
        pass


def check_data_freshness(engine: sa.Engine | None = None) -> dict:
    """Check if cached_signals data is fresh enough for trading.

    Returns dict with: latest, age_hours, total_stocks, today_count, is_fresh.
    """
    engine = engine or get_engine()
    try:
        with engine.connect() as conn:
            r = (
                conn.execute(
                    sa.text("""
                SELECT
                    MAX(cached_at)::timestamp as latest,
                    NOW() - MAX(cached_at)::timestamp as age,
                    COUNT(*) as total,
                    SUM(CASE WHEN cached_at::date = CURRENT_DATE THEN 1 ELSE 0 END) as today
                FROM cached_signals
            """)
                )
                .mappings()
                .fetchone()
            )
        age_hours = r["age"].total_seconds() / 3600 if r["age"] else 999
        return {
            "latest": str(r["latest"]) if r["latest"] else None,
            "age_hours": round(age_hours, 1),
            "total_stocks": r["total"] or 0,
            "today_count": r["today"] or 0,
            "is_fresh": age_hours < 24 and (r["today"] or 0) > 100,
        }
    except Exception as e:
        return {
            "latest": None,
            "age_hours": 999,
            "total_stocks": 0,
            "today_count": 0,
            "is_fresh": False,
            "error": str(e),
        }
