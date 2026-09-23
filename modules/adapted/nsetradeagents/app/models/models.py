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


from datetime import UTC, date, datetime, timezone
from typing import Optional

from app.core.database import Base
from sqlalchemy import Boolean, Date, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func


def utcnow() -> datetime:
    """Naive UTC, set by Python rather than the database.

    server_default=func.now() is UTC on SQLite but server-local time on
    Postgres — this keeps the value identical on both.
    """
    return datetime.now(UTC).replace(tzinfo=None)


class Trade(Base):
    """A position, open or closed. The authoritative record of what was traded."""

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20))
    entry_price: Mapped[float]
    quantity: Mapped[int]
    entry_value: Mapped[float]
    stop_loss: Mapped[float]
    take_profit: Mapped[float]
    current_price: Mapped[float | None] = mapped_column(nullable=True)
    atr_pct: Mapped[float | None] = mapped_column(nullable=True)
    peak_price: Mapped[float | None] = mapped_column(nullable=True)
    trail_stop: Mapped[float | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | closed
    close_price: Mapped[float | None]
    close_reason: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # stop | trail | target | timeout | manual — see app/portfolio/exits.py
    pnl: Mapped[float | None]
    pnl_pct: Mapped[float | None]
    confidence: Mapped[float | None]
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    technical_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    sector: Mapped[str | None] = mapped_column(String(50), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())
    closed_at: Mapped[datetime | None]


class PortfolioSnapshot(Base):
    """Portfolio value at a point in time.

    Drives the equity chart and the circuit breaker's drawdown check.
    """

    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    total_value: Mapped[float]
    cash: Mapped[float]
    invested: Mapped[float]
    open_positions: Mapped[int]
    daily_pnl: Mapped[float] = mapped_column(default=0.0)
    cumulative_pnl: Mapped[float] = mapped_column(default=0.0)
    unrealised_pnl: Mapped[float] = mapped_column(default=0.0)
    snapshot_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())


class DecisionRecord(Base):
    """One row per candidate the scan evaluated, whether it was bought or not.

    Holds the score and the band each dimension landed in, the indicators at
    the time, and space for the veto's verdict. `outcome_*` is filled in later
    by the post-mortem, so passed-over candidates can be judged alongside
    the ones that were traded.
    """

    __tablename__ = "decision_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    as_of: Mapped[date] = mapped_column(Date)
    ticker: Mapped[str] = mapped_column(String(20))
    git_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # scoring — null if blocked before we got this far
    score: Mapped[int | None] = mapped_column(nullable=True)
    entry_timing: Mapped[str | None] = mapped_column(String(20), nullable=True)
    momentum_quality: Mapped[str | None] = mapped_column(String(20), nullable=True)
    risk_reward_view: Mapped[str | None] = mapped_column(String(20), nullable=True)
    market_regime: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # what the stock looked like that day
    price: Mapped[float | None] = mapped_column(nullable=True)
    rsi: Mapped[float | None] = mapped_column(nullable=True)
    atr_pct: Mapped[float | None] = mapped_column(nullable=True)
    volume_ratio: Mapped[float | None] = mapped_column(nullable=True)
    momentum_5d: Mapped[float | None] = mapped_column(nullable=True)
    day_change_pct: Mapped[float | None] = mapped_column(nullable=True)

    # what the market looked like that day. The inputs, not just the band they
    # produced — market_regime is 25 of the 100 points and does not rank
    # candidates, so recalibrating it later needs the raw values.
    india_vix: Mapped[float | None] = mapped_column(nullable=True)
    nifty_20d_pct: Mapped[float | None] = mapped_column(nullable=True)

    # what we did
    entered: Mapped[bool] = mapped_column(Boolean, default=False)
    block_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Whether the breadth gate was open when this decision was made. It only
    # reaches block_reason for candidates that would otherwise have executed,
    # so without this a score-blocked candidate looks identical in an open and
    # a shut market — and the gate itself could never be judged from live data.
    regime_open: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # The raw breadth reading, not just the pass/fail. Storing only the boolean
    # would freeze the 50% floor permanently; the float lets the threshold
    # itself be re-examined against live outcomes.
    breadth_pct: Mapped[float | None] = mapped_column(nullable=True)

    # Why the volume spiked — the screener buys spikes by construction, so this
    # is the information it structurally lacks: earnings reaction, order win,
    # index inclusion, block deal, sector move, or nothing identifiable.
    # Unpopulated until the classifier is built; classifying a spike months
    # later is far harder than doing it on the day.
    catalyst: Mapped[str | None] = mapped_column(String(30), nullable=True)
    catalyst_fact: Mapped[str | None] = mapped_column(Text, nullable=True)

    # veto — null for candidates that never reached it
    veto_verdict: Mapped[str | None] = mapped_column(String(10), nullable=True)
    veto_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    veto_cited_fact: Mapped[str | None] = mapped_column(Text, nullable=True)
    veto_source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    veto_checked: Mapped[str | None] = mapped_column(Text, nullable=True)
    veto_transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    veto_model: Mapped[str | None] = mapped_column(String(50), nullable=True)
    veto_mode: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # outcome — empty until the post-mortem fills it
    outcome_pnl_pct: Mapped[float | None] = mapped_column(nullable=True)
    outcome_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
    outcome_exit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Return minus the smallcap index over the same window. Raw return alone
    # misjudges whole years: in 2025 the system lost 4.2% while its universe
    # lost 5.3%, which is a good year that looks like a bad one.
    outcome_alpha_pct: Mapped[float | None] = mapped_column(nullable=True)
    outcome_filled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())


class ScanRun(Base):
    """One row per scan attempt, written whether or not it found anything.

    Separates "ran and found nothing" from "never ran", which is the only
    thing a health check actually needs to know.
    """

    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    ran_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    candidates_found: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
