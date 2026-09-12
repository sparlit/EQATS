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


import sqlite3

from config import DB_PATH

SCHEMA = """
-- ============================================================
-- Core universe
-- ============================================================
CREATE TABLE IF NOT EXISTS stocks (
  symbol TEXT PRIMARY KEY, name TEXT, sector TEXT,
  active INTEGER DEFAULT 1, updated_at TEXT
);

CREATE TABLE IF NOT EXISTS universe_broad (
  symbol TEXT PRIMARY KEY, name TEXT, mcap_cr REAL, close REAL,
  pe REAL, perf1m REAL, perf3m REAL, relvol REAL, updated_at TEXT
);

-- ============================================================
-- Prices
-- ============================================================
CREATE TABLE IF NOT EXISTS prices_daily (
  symbol TEXT, date TEXT,
  open REAL, high REAL, low REAL, close REAL, volume REAL,
  PRIMARY KEY (symbol, date)
);

CREATE TABLE IF NOT EXISTS price_meta (
  symbol TEXT PRIMARY KEY, last_date TEXT, rows INTEGER, updated_at TEXT
);

CREATE TABLE IF NOT EXISTS technicals_daily (
  symbol TEXT, date TEXT, close REAL, dma20 REAL, dma50 REAL,
  dma200 REAL, rsi REAL, vol_ratio REAL, high52 REAL, low52 REAL,
  mom20 REAL, above200 INTEGER,
  PRIMARY KEY (symbol, date)
);

-- ============================================================
-- Fundamentals + sentiment
-- ============================================================
CREATE TABLE IF NOT EXISTS fundamentals (
  symbol TEXT PRIMARY KEY, name TEXT, sector TEXT,
  current_price REAL, market_cap_cr REAL, pe REAL, pb REAL,
  roe REAL, roce REAL, debt_to_equity REAL, interest_coverage REAL,
  operating_margin REAL, net_profit_margin REAL,
  sales_growth_3y REAL, profit_growth_3y REAL,
  promoter_holding REAL, pledge_pct REAL, fii_holding REAL,
  dividend_yield REAL, cfo_positive INTEGER, uploaded_at TEXT
);

CREATE TABLE IF NOT EXISTS sentiment_results (
  symbol TEXT, created_at TEXT, headline_count INTEGER,
  positive INTEGER, neutral INTEGER, negative INTEGER,
  sentiment_score REAL, major_negative TEXT
);

CREATE TABLE IF NOT EXISTS sentiment_headlines (
  symbol TEXT, created_at TEXT, title TEXT, age_days INTEGER,
  label TEXT, prob REAL
);

CREATE TABLE IF NOT EXISTS corp_calendar (
  symbol TEXT, event_date TEXT, kind TEXT, detail TEXT
);

-- ============================================================
-- Scans + pipeline
-- ============================================================
CREATE TABLE IF NOT EXISTS scan_results (
  scan_date TEXT, symbol TEXT, passed INTEGER,
  fundamental_score REAL, ml_score REAL, risk_flags TEXT, status TEXT,
  PRIMARY KEY (scan_date, symbol)
);

CREATE TABLE IF NOT EXISTS scan_reasons (
  scan_date TEXT, symbol TEXT, rule_name TEXT, passed INTEGER,
  actual_value REAL, expected_text TEXT, reason_text TEXT
);

CREATE TABLE IF NOT EXISTS pipeline (
  symbol TEXT PRIMARY KEY, status TEXT, added_date TEXT,
  updated_date TEXT, reason TEXT, notes TEXT, review_date TEXT
);

CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);

-- ============================================================
-- ML
-- ============================================================
CREATE TABLE IF NOT EXISTS ml_predictions (
  symbol TEXT, prediction_date TEXT,
  ml_score_6m REAL, ml_score_12m REAL, final_ml_score REAL,
  ml_rank REAL, model_version TEXT,
  PRIMARY KEY (symbol, prediction_date)
);

CREATE TABLE IF NOT EXISTS model_runs (
  run_date TEXT, note TEXT, rows INTEGER, winners REAL,
  auc REAL, base_win REAL, top10_win REAL, n_features INTEGER,
  price_only_auc REAL, delta_auc REAL, delta_top10 REAL,
  PRIMARY KEY (run_date, note)
);

CREATE TABLE IF NOT EXISTS pwin_daily (
  symbol TEXT, date TEXT, p_win REAL, why TEXT,
  PRIMARY KEY (symbol, date)
);

-- ============================================================
-- Events + quality
-- ============================================================
CREATE TABLE IF NOT EXISTS events (
  date TEXT, symbol TEXT, kind TEXT, text TEXT
);

CREATE TABLE IF NOT EXISTS data_quality_log (
  run_at TEXT, status TEXT, severity TEXT,
  check_name TEXT, message TEXT
);

-- ============================================================
-- Market context
-- ============================================================
CREATE TABLE IF NOT EXISTS breadth_daily (
  date TEXT PRIMARY KEY, above50 REAL, adv REAL, dec REAL
);

CREATE TABLE IF NOT EXISTS institutional (
  symbol TEXT, date TEXT, accum REAL, delivery_pct REAL,
  UNIQUE(symbol, date)
);

CREATE TABLE IF NOT EXISTS macro_flow (
  date TEXT PRIMARY KEY, fii_net_cr REAL, dii_net_cr REAL
);

CREATE TABLE IF NOT EXISTS delivery_daily (
  date TEXT, symbol TEXT, traded_qty INTEGER,
  deliverable_qty INTEGER, delivery_pct REAL,
  close REAL, created_at TEXT,
  PRIMARY KEY(date, symbol)
);

-- ============================================================
-- Patterns + templates
-- ============================================================
CREATE TABLE IF NOT EXISTS pattern_tags (
  date TEXT, symbol TEXT, pattern TEXT, direction TEXT,
  status TEXT, confidence REAL,
  breakout_level REAL, stop_level REAL, target_level REAL,
  notes TEXT, params TEXT, created_at TEXT,
  PRIMARY KEY(date, symbol, pattern)
);

CREATE TABLE IF NOT EXISTS pattern_grades (
  tag_date TEXT, symbol TEXT, pattern TEXT, outcome TEXT,
  exit_date TEXT, r_multiple REAL, graded_at TEXT,
  PRIMARY KEY(tag_date, symbol, pattern)
);

CREATE TABLE IF NOT EXISTS template_scores (
  date TEXT, symbol TEXT, template TEXT, similarity REAL,
  created_at TEXT,
  PRIMARY KEY(date, symbol, template)
);

-- ============================================================
-- Swing desk + top picks
-- ============================================================
CREATE TABLE IF NOT EXISTS swing_signals (
  signal_date TEXT, symbol TEXT, entry_trigger REAL,
  stop REAL, target REAL, risk_pct REAL, pullback REAL,
  impulse REAL, ema_zone TEXT, outcome TEXT, updated_at TEXT
);

CREATE TABLE IF NOT EXISTS top_picks (
  date TEXT, symbol TEXT, p_win REAL, accum REAL,
  sector_rs REAL, sector TEXT, setup INTEGER,
  composite REAL, delivery REAL
);

-- ============================================================
-- Validation + webhooks
-- ============================================================
CREATE TABLE IF NOT EXISTS validation_log (
  run_date TEXT, mode TEXT, payload TEXT,
  PRIMARY KEY (run_date, mode)
);

CREATE TABLE IF NOT EXISTS webhook_events (
  created_at TEXT, source TEXT, symbol TEXT, kind TEXT,
  price REAL, payload TEXT
);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    return conn
