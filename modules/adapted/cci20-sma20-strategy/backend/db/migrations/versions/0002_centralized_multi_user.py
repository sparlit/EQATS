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


"""Centralized Multi-User Stock Scanner & Share ID Watchlists.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-23
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. daily_stock_metrics ──────────────────────────────────────────────────
    op.create_table(
        "daily_stock_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("scan_date", sa.Date(), nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("scanned_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("close", sa.Numeric(14, 4), nullable=True),
        sa.Column("cci_20", sa.Numeric(10, 4), nullable=True),
        sa.Column("sma_20", sa.Numeric(14, 4), nullable=True),
        sa.Column("yearly_low", sa.Numeric(14, 4), nullable=True),
        sa.Column("monthly_low", sa.Numeric(14, 4), nullable=True),
        sa.Column("weekly_low", sa.Numeric(14, 4), nullable=True),
        sa.Column("pct_from_y_low", sa.Numeric(8, 4), nullable=True),
        sa.Column("pct_from_m_low", sa.Numeric(8, 4), nullable=True),
        sa.Column("pct_from_w_low", sa.Numeric(8, 4), nullable=True),
        sa.Column("near_y_low", sa.Boolean(), nullable=True),
        sa.Column("near_m_low", sa.Boolean(), nullable=True),
        sa.Column("near_w_low", sa.Boolean(), nullable=True),
        sa.Column("cci_history", postgresql.JSONB(), nullable=True),
        sa.UniqueConstraint("ticker", "scan_date", name="uq_ticker_scan_date"),
    )
    op.create_index("ix_daily_metrics_ticker_date", "daily_stock_metrics", ["ticker", "scan_date"])

    # ── 2. Add columns to watchlists (if upgrading existing) ────────────────────
    # For clean UUID handling: alter or add columns
    try:
        op.add_column("watchlists", sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.execute("UPDATE watchlists SET owner_id = user_id WHERE owner_id IS NULL")
    except Exception:
        pass

    try:
        op.add_column("watchlists", sa.Column("share_id", sa.String(32), nullable=True))
        op.execute("UPDATE watchlists SET share_id = 'sh_' || substr(md5(random()::text), 1, 8) WHERE share_id IS NULL")
        op.create_index("ix_watchlists_share_id", "watchlists", ["share_id"], unique=True)
    except Exception:
        pass

    try:
        op.add_column("watchlists", sa.Column("description", sa.String(255), nullable=True))
        op.add_column("watchlists", sa.Column("is_public", sa.Boolean(), server_default="false"))
        op.add_column("watchlists", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    except Exception:
        pass

    # ── 3. watchlist_items ──────────────────────────────────────────────────────
    op.create_table(
        "watchlist_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("watchlist_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("watchlist_id", "ticker", name="uq_watchlist_ticker"),
        sa.ForeignKeyConstraint(["watchlist_id"], ["watchlists.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_watchlist_items_ticker", "watchlist_items", ["ticker"])

    # ── 4. user_subscriptions ────────────────────────────────────────────────────
    op.create_table(
        "user_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("watchlist_id", sa.Integer(), nullable=False),
        sa.Column("subscribed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "watchlist_id", name="uq_user_watchlist_sub"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["watchlist_id"], ["watchlists.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("user_subscriptions")
    op.drop_table("watchlist_items")
    op.drop_table("daily_stock_metrics")
