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
SQLAlchemy 2.0 ORM models — Centralized Multi-User Stock Scanner & Sync Architecture.

Models:
  - User: Cognito authenticated user
  - Watchlist: Named watchlist owned by a user (has unique share_id e.g. sh_a8f9c2)
  - WatchlistItem: Individual tickers in a watchlist
  - UserSubscription: Links users to shared watchlists (synced)
  - DailyStockMetric: Centralized daily technical indicator cache per ticker & date
  - ScanRun / ScanResult: Legacy support tables
"""

import random
import string
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def generate_share_id(length: int = 8) -> str:
    """Generates a clean unique share ID for watchlists e.g. 'sh_8f3a9b2c'"""
    chars = string.ascii_lowercase + string.digits
    return "sh_" + "".join(random.choices(chars, k=length))


# ── Users ──────────────────────────────────────────────────────────────────────


class User(Base):
    """Cognito-authenticated user — created automatically on first JWT login."""

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cognito_sub = Column(String(128), unique=True, nullable=False, index=True)
    email = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owned_watchlists = relationship("Watchlist", back_populates="owner", cascade="all, delete-orphan")
    subscriptions = relationship("UserSubscription", back_populates="user", cascade="all, delete-orphan")


# ── Watchlists ─────────────────────────────────────────────────────────────────


class Watchlist(Base):
    """A named watchlist owned by a user with a unique share_id for syncing across users."""

    __tablename__ = "watchlists"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_watchlist_user_name"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(String(255), nullable=True)

    # Share ID for multi-user sharing & syncing e.g. "sh_a8f9c2"
    share_id = Column(String(32), unique=True, nullable=False, default=generate_share_id, index=True)
    is_public = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    owner = relationship("User", back_populates="owned_watchlists")
    items = relationship("WatchlistItem", back_populates="watchlist", cascade="all, delete-orphan")
    subscribers = relationship("UserSubscription", back_populates="watchlist", cascade="all, delete-orphan")
    scan_runs = relationship("ScanRun", back_populates="watchlist", cascade="all, delete-orphan")

    @property
    def owner_id(self):
        return self.user_id


# ── Watchlist Items ─────────────────────────────────────────────────────────────


class WatchlistItem(Base):
    """Individual tickers contained within a Watchlist."""

    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint("watchlist_id", "ticker", name="uq_watchlist_ticker"),
        Index("ix_watchlist_items_ticker", "ticker"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    watchlist_id = Column(Integer, ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False)
    ticker = Column(String(20), nullable=False)
    added_at = Column(DateTime(timezone=True), server_default=func.now())

    watchlist = relationship("Watchlist", back_populates="items")


# ── User Subscriptions ─────────────────────────────────────────────────────────


class UserSubscription(Base):
    """Sync shared watchlists across multiple users using share_id."""

    __tablename__ = "user_subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "watchlist_id", name="uq_user_watchlist_sub"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    watchlist_id = Column(Integer, ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False)
    subscribed_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="subscriptions")
    watchlist = relationship("Watchlist", back_populates="subscribers")


# ── Centralized Daily Stock Metrics Cache ───────────────────────────────────────


class DailyStockMetric(Base):
    """Centralized stock metrics calculated ONCE per unique ticker & scan date."""

    __tablename__ = "daily_stock_metrics"
    __table_args__ = (
        UniqueConstraint("ticker", "scan_date", name="uq_ticker_scan_date"),
        Index("ix_daily_metrics_ticker_date", "ticker", "scan_date"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker = Column(String(20), nullable=False, index=True)
    scan_date = Column(Date, nullable=False, server_default=func.current_date())
    scanned_at = Column(DateTime(timezone=True), server_default=func.now())

    # Price & Indicators
    close = Column(Numeric(14, 4))
    cci_20 = Column(Numeric(10, 4))
    sma_20 = Column(Numeric(14, 4))

    # Low anchors
    yearly_low = Column(Numeric(14, 4))
    monthly_low = Column(Numeric(14, 4))
    weekly_low = Column(Numeric(14, 4))

    # Proximity metrics (%)
    pct_from_y_low = Column(Numeric(8, 4))
    pct_from_m_low = Column(Numeric(8, 4))
    pct_from_w_low = Column(Numeric(8, 4))

    # Boolean proximity flags (within 5%)
    near_y_low = Column(Boolean)
    near_m_low = Column(Boolean)
    near_w_low = Column(Boolean)

    # 20-day CCI history for sparklines
    cci_history = Column(JSONB)

    # Weekly CPR (Central Pivot Range) — narrow = potential breakout
    narrow_cpr = Column(Boolean, default=False)


# ── Legacy Compatibility Models ─────────────────────────────────────────────────


class ScanRun(Base):
    """Legacy scan run container."""

    __tablename__ = "scan_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    watchlist_id = Column(
        UUID(as_uuid=True), ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scanned_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ticker_count = Column(Integer, nullable=True)

    watchlist = relationship("Watchlist", back_populates="scan_runs")
    results = relationship("ScanResult", back_populates="scan_run", cascade="all, delete-orphan")


class ScanResult(Base):
    """Legacy per-watchlist scan result."""

    __tablename__ = "scan_results"
    __table_args__ = (Index("ix_scan_results_run_id", "scan_run_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_run_id = Column(Integer, ForeignKey("scan_runs.id", ondelete="CASCADE"), nullable=False)
    ticker = Column(String(20), nullable=False)
    close = Column(Numeric(14, 4))
    cci_20 = Column(Numeric(10, 4))
    sma_20 = Column(Numeric(14, 4))
    yearly_low = Column(Numeric(14, 4))
    monthly_low = Column(Numeric(14, 4))
    weekly_low = Column(Numeric(14, 4))
    pct_from_y_low = Column(Numeric(8, 4))
    pct_from_m_low = Column(Numeric(8, 4))
    pct_from_w_low = Column(Numeric(8, 4))
    near_y_low = Column(Boolean)
    near_m_low = Column(Boolean)
    near_w_low = Column(Boolean)
    cci_history = Column(JSONB)

    scan_run = relationship("ScanRun", back_populates="results")
