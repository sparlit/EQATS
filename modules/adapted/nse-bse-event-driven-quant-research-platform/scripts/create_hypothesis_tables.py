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


"""Create hypothesis tracking tables in PostgreSQL.

Tables:
    hypotheses            -- registry of trading hypotheses
    hypothesis_stocks     -- stocks tracked per hypothesis
    hypothesis_signals    -- date-wise signals per hypothesis
    hypothesis_trades     -- entry/exit/performance per trade
    hypothesis_analytics  -- pre-computed daily analytics per hypothesis

Usage:
    python scripts/create_hypothesis_tables.py
"""


import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import sqlalchemy as sa
from indian_quant.config.connections import get_engine

SCHEMA_SQL = """
-- Hypothesis registry
CREATE TABLE IF NOT EXISTS hypotheses (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(64) NOT NULL UNIQUE,
    description     TEXT,
    signal_logic    JSONB DEFAULT '{}',
    max_positions   INTEGER DEFAULT 7,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Stocks tracked per hypothesis (the "universe")
CREATE TABLE IF NOT EXISTS hypothesis_stocks (
    id              SERIAL PRIMARY KEY,
    hypothesis_id   INTEGER NOT NULL REFERENCES hypotheses(id) ON DELETE CASCADE,
    symbol          VARCHAR(32) NOT NULL,
    exchange        VARCHAR(8) NOT NULL DEFAULT 'NSE',
    added_at        TIMESTAMP DEFAULT NOW(),
    added_by        VARCHAR(32) DEFAULT 'system',
    removal_reason  TEXT,
    removed_at      TIMESTAMP,
    UNIQUE(hypothesis_id, symbol)
);

-- Date-wise signals per hypothesis
CREATE TABLE IF NOT EXISTS hypothesis_signals (
    id              SERIAL PRIMARY KEY,
    hypothesis_id   INTEGER NOT NULL REFERENCES hypotheses(id) ON DELETE CASCADE,
    symbol          VARCHAR(32) NOT NULL,
    signal_date     DATE NOT NULL,
    signal_type     VARCHAR(32) NOT NULL,
    strength        REAL DEFAULT 0.0,
    entry_price     REAL,
    stop_loss       REAL,
    target_price    REAL,
    close           REAL,
    deliv_z         REAL,
    vol_z           REAL,
    rsi             REAL,
    macd_hist       REAL,
    turnover        REAL,
    market_cap_cr   REAL,
    notes           TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Trades per hypothesis (entry/exit/performance)
CREATE TABLE IF NOT EXISTS hypothesis_trades (
    id              SERIAL PRIMARY KEY,
    hypothesis_id   INTEGER NOT NULL REFERENCES hypotheses(id) ON DELETE CASCADE,
    signal_id       INTEGER REFERENCES hypothesis_signals(id),
    symbol          VARCHAR(32) NOT NULL,
    exchange        VARCHAR(8) NOT NULL DEFAULT 'NSE',
    entry_date      DATE NOT NULL,
    entry_price     REAL NOT NULL,
    qty             INTEGER NOT NULL,
    entry_value     REAL NOT NULL,
    exit_date       DATE,
    exit_price      REAL,
    exit_value      REAL,
    exit_reason     VARCHAR(32),
    gross_bps       REAL,
    net_bps         REAL,
    return_pct      REAL,
    days_held       INTEGER,
    stop_pct        REAL DEFAULT 0.07,
    horizon_days    INTEGER DEFAULT 10,
    status          VARCHAR(16) DEFAULT 'OPEN',
    notes           TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Pre-computed daily analytics per hypothesis
CREATE TABLE IF NOT EXISTS hypothesis_analytics (
    id              SERIAL PRIMARY KEY,
    hypothesis_id   INTEGER NOT NULL REFERENCES hypotheses(id) ON DELETE CASCADE,
    date            DATE NOT NULL,
    total_trades    INTEGER DEFAULT 0,
    open_trades     INTEGER DEFAULT 0,
    settled_trades  INTEGER DEFAULT 0,
    win_count       INTEGER DEFAULT 0,
    loss_count      INTEGER DEFAULT 0,
    win_rate        REAL,
    avg_net_bps     REAL,
    avg_return_pct  REAL,
    max_drawdown    REAL,
    sharpe_ratio    REAL,
    total_pnl       REAL,
    capital_deployed REAL,
    created_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(hypothesis_id, date)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_hypo_stocks_hypo ON hypothesis_stocks(hypothesis_id);
CREATE INDEX IF NOT EXISTS idx_hypo_stocks_sym ON hypothesis_stocks(symbol);
CREATE INDEX IF NOT EXISTS idx_hypo_signals_hypo ON hypothesis_signals(hypothesis_id);
CREATE INDEX IF NOT EXISTS idx_hypo_signals_date ON hypothesis_signals(signal_date);
CREATE INDEX IF NOT EXISTS idx_hypo_signals_hypo_date ON hypothesis_signals(hypothesis_id, signal_date);
CREATE INDEX IF NOT EXISTS idx_hypo_trades_hypo ON hypothesis_trades(hypothesis_id);
CREATE INDEX IF NOT EXISTS idx_hypo_trades_status ON hypothesis_trades(status);
CREATE INDEX IF NOT EXISTS idx_hypo_trades_sym ON hypothesis_trades(symbol);
CREATE INDEX IF NOT EXISTS idx_hypo_analytics_hypo ON hypothesis_analytics(hypothesis_id);

-- Circuit breaker limits (daily per-stock upper/lower limits)
CREATE TABLE IF NOT EXISTS stock_circuit_limits (
    id              SERIAL PRIMARY KEY,
    symbol          VARCHAR(32) NOT NULL,
    exchange        VARCHAR(8) NOT NULL DEFAULT 'NSE',
    trade_date      DATE NOT NULL,
    prev_close      REAL,
    upper_circuit   REAL,
    lower_circuit   REAL,
    filter_pct      REAL,
    source          VARCHAR(16) NOT NULL DEFAULT 'inferred',
    created_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(symbol, exchange, trade_date, source)
);

CREATE INDEX IF NOT EXISTS idx_circuit_sym_date ON stock_circuit_limits(symbol, trade_date);
CREATE INDEX IF NOT EXISTS idx_circuit_date ON stock_circuit_limits(trade_date);
CREATE INDEX IF NOT EXISTS idx_circuit_source ON stock_circuit_limits(source);
"""


def main() -> int:
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(sa.text(SCHEMA_SQL))
    print("Hypothesis tables created successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
