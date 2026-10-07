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


"""Initial journal and paper trading tables.

Revision ID: 001_initial
Revises: None
Create Date: 2026-09-07
"""
from collections.abc import Sequence

from alembic import op

revision: str = "001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # trade_journal
    op.execute("""
        CREATE TABLE IF NOT EXISTS trade_journal (
            id              SERIAL PRIMARY KEY,
            paper_trade_id  INTEGER UNIQUE,
            hypothesis_id   INTEGER,
            symbol          VARCHAR(32) NOT NULL,
            entry_date      DATE NOT NULL,
            entry_price     REAL NOT NULL,
            entry_signal    TEXT,
            entry_rationale TEXT,
            setup_type      VARCHAR(32) DEFAULT 'delivery_momentum',
            stop_loss       REAL,
            target_price    REAL,
            position_size   INTEGER,
            risk_amount     REAL,
            conviction      REAL,
            sector          VARCHAR(64),
            nifty_level     REAL,
            market_breadth  REAL,
            exit_date       DATE,
            exit_price      REAL,
            exit_reason     VARCHAR(32),
            exit_rationale  TEXT,
            days_held       INTEGER,
            return_pct      REAL,
            return_bps      REAL,
            net_bps         REAL,
            review_date     DATE,
            review_rating   INTEGER,
            what_went_right TEXT,
            what_went_wrong TEXT,
            lessons_learned TEXT,
            would_repeat    BOOLEAN,
            setup_quality   VARCHAR(16),
            execution_grade VARCHAR(8),
            notes           TEXT,
            stop_moved      BOOLEAN DEFAULT FALSE,
            stop_history    JSONB DEFAULT '[]',
            created_at      TIMESTAMP DEFAULT NOW()
        )
    """)

    # trade_journal indexes
    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_tj_symbol ON trade_journal(symbol)",
        "CREATE INDEX IF NOT EXISTS idx_tj_entry_date ON trade_journal(entry_date)",
        "CREATE INDEX IF NOT EXISTS idx_tj_exit_reason ON trade_journal(exit_reason)",
        "CREATE INDEX IF NOT EXISTS idx_tj_setup ON trade_journal(setup_type)",
        "CREATE INDEX IF NOT EXISTS idx_tj_paper_id ON trade_journal(paper_trade_id)",
        "CREATE INDEX IF NOT EXISTS idx_tj_hypothesis ON trade_journal(hypothesis_id)",
        "CREATE INDEX IF NOT EXISTS idx_tj_reviewed ON trade_journal(review_date) WHERE review_date IS NOT NULL",
    ]:
        op.execute(idx_sql)

    # paper_signals
    op.execute("""
        CREATE TABLE IF NOT EXISTS paper_signals (
            id                  SERIAL PRIMARY KEY,
            created_at          TIMESTAMPTZ NOT NULL,
            symbol              VARCHAR(32) NOT NULL,
            segment             VARCHAR(8),
            side                VARCHAR(4) NOT NULL DEFAULT 'BUY',
            close_at_signal     REAL NOT NULL,
            qty                 INTEGER NOT NULL,
            horizon_days        INTEGER NOT NULL,
            stop_pct            REAL NOT NULL,
            status              VARCHAR(16) NOT NULL DEFAULT 'OPEN',
            exit_date           DATE,
            exit_close          REAL,
            realized_net_bps    REAL,
            note                TEXT,
            entry_date          DATE,
            days_held           INTEGER DEFAULT 0,
            position_value      REAL DEFAULT 0,
            risk_amount         REAL DEFAULT 0,
            return_pct          REAL,
            return_bps          REAL,
            horizon_label       VARCHAR(8) DEFAULT '10d',
            capital_allocated   REAL DEFAULT 0,
            exit_reason         VARCHAR(32),
            max_drawdown_bps    REAL,
            peak_return_bps     REAL,
            conviction_score    REAL DEFAULT 0,
            kelly_fraction      REAL DEFAULT 0
        )
    """)

    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_ps_status ON paper_signals(status, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_ps_symbol ON paper_signals(symbol)",
    ]:
        op.execute(idx_sql)

    # daily_suggestions
    op.execute("""
        CREATE TABLE IF NOT EXISTS daily_suggestions (
            id                  SERIAL PRIMARY KEY,
            suggestion_date     DATE NOT NULL,
            symbol              VARCHAR(32) NOT NULL,
            segment             VARCHAR(8) NOT NULL,
            signal_type         VARCHAR(16) NOT NULL,
            direction           VARCHAR(4) NOT NULL DEFAULT 'BUY',
            close_at_signal     REAL NOT NULL,
            deliv_pct           REAL,
            deliv_z             REAL,
            vol_z               REAL,
            entry_zone_low      REAL,
            entry_zone_high     REAL,
            stop_loss           REAL,
            target_price        REAL,
            horizon_days        INTEGER NOT NULL,
            qty_suggested       INTEGER NOT NULL,
            status              VARCHAR(16) NOT NULL DEFAULT 'PENDING',
            actual_exit_date    DATE,
            actual_exit_close   REAL,
            actual_return_bps   REAL,
            predicted_return_bps REAL,
            hit                 BOOLEAN,
            note                TEXT
        )
    """)

    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_ds_date ON daily_suggestions(suggestion_date)",
        "CREATE INDEX IF NOT EXISTS idx_ds_symbol ON daily_suggestions(symbol)",
        "CREATE INDEX IF NOT EXISTS idx_ds_status ON daily_suggestions(status)",
    ]:
        op.execute(idx_sql)

    # Unified view
    op.execute("""
        CREATE OR REPLACE VIEW v_all_trades AS
            SELECT
                'paper'::text       AS source,
                id, symbol, entry_date,
                close_at_signal    AS entry_price,
                NULL::text          AS entry_signal,
                NULL::text          AS entry_rationale,
                'delivery_momentum' AS setup_type,
                exit_date,
                exit_close          AS exit_price,
                exit_reason, days_held, return_pct,
                realized_net_bps    AS net_bps,
                sector,
                conviction_score    AS conviction,
                created_at::timestamp
            FROM paper_signals
            WHERE status IN ('SETTLED', 'EXITED')
          UNION ALL
            SELECT
                'hypothesis'::text  AS source,
                id, symbol, entry_date, entry_price,
                NULL::text          AS entry_signal,
                NULL::text          AS entry_rationale,
                NULL::text          AS setup_type,
                exit_date, exit_price,
                exit_reason, days_held, return_pct, net_bps,
                NULL::text          AS sector,
                NULL::double precision AS conviction,
                created_at
            FROM hypothesis_trades
            WHERE status = 'SETTLED'
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_all_trades")
    op.execute("DROP TABLE IF EXISTS daily_suggestions")
    op.execute("DROP TABLE IF EXISTS paper_signals")
    op.execute("DROP TABLE IF EXISTS trade_journal")
