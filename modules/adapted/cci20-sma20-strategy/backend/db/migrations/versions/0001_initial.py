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


"""Initial schema — users, watchlists, scan_runs, scan_results.

Revision ID: 0001
Revises:
Create Date: 2026-07-26
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── users ──────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("cognito_sub", sa.String(128), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_cognito_sub", "users", ["cognito_sub"], unique=True)

    # ── watchlists ─────────────────────────────────────────────────────────────
    op.create_table(
        "watchlists",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "name", name="uq_watchlist_user_name"),
    )
    op.create_index("ix_watchlists_user_id", "watchlists", ["user_id"])

    # ── scan_runs ──────────────────────────────────────────────────────────────
    op.create_table(
        "scan_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("watchlist_id", sa.Integer(), nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ticker_count", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["watchlist_id"], ["watchlists.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_scan_runs_watchlist_id", "scan_runs", ["watchlist_id"])

    # ── scan_results ───────────────────────────────────────────────────────────
    op.create_table(
        "scan_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scan_run_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(20), nullable=False),
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
        sa.ForeignKeyConstraint(["scan_run_id"], ["scan_runs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_scan_results_run_id", "scan_results", ["scan_run_id"])


def downgrade() -> None:
    op.drop_table("scan_results")
    op.drop_table("scan_runs")
    op.drop_table("watchlists")
    op.drop_table("users")
