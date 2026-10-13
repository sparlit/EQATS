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
SQLite-backed storage for live-trading state -- consolidates what used to
be four separate ad hoc files (cache/live_position_state.json,
cache/fund_state.json, cache/equity_log.csv, cache/rebalance_proposal.pkl)
into one queryable local database, free and dependency-free (sqlite3 is
Python stdlib).

Kept local-only and gitignored, same as everything else under cache/ --
this holds real account/position/fund data, never meant to leave the
machine.

cache/live_rebalance_log.txt stays separate and unchanged -- it serves a
different purpose (a plain-text tail-able trail for a headless scheduled
run with no console).
"""


import contextlib
import datetime as dt
import hashlib
import json
import os
import secrets
import sqlite3
import time
import traceback

import notify
import pandas as pd
from kiteconnect.exceptions import TokenException

DB_PATH = os.path.join("cache", "state.db")
_LEGACY_EQUITY_LOG = os.path.join("cache", "equity_log.csv")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    entry_price REAL NOT NULL,
    qty INTEGER NOT NULL,
    highest_close REAL NOT NULL,
    current_stop REAL NOT NULL,
    gtt_trigger_id INTEGER,
    status TEXT NOT NULL DEFAULT 'open',
    closed_date TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS stop_update_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER REFERENCES positions(id),
    date TEXT NOT NULL,
    old_stop REAL NOT NULL,
    new_stop REAL NOT NULL,
    applied INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS fund_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    initial_capital REAL NOT NULL,
    captured_date TEXT NOT NULL
);

-- Every deposit/withdrawal, dated -- Kite's API has no visibility into
-- bank transfers, so this is manually logged (Admin page). The old
-- fund_state singleton row above is superseded by this (a proper ledger
-- lets XIRR account for deposit timing, not just a single starting
-- amount) -- see _migrate_fund_state_to_cash_flow, which carries that row
-- forward as this ledger's first entry rather than losing it.
CREATE TABLE IF NOT EXISTS cash_flows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    amount REAL NOT NULL,
    note TEXT
);

-- Recurring charges (e.g. quarterly Demat AMC) -- a declarative definition
-- posted automatically to cash_flows by post_due_recurring_charges() each
-- time next_due_date is reached, instead of the user re-adding a manual
-- cash_flows row every time it comes due. interval_months steps calendar-
-- correctly (via a real month-add, not a fixed day-count), so a charge
-- anchored to e.g. the 24th doesn't drift off that date over years the
-- way naive "+91 days" quarterly math would.
CREATE TABLE IF NOT EXISTS recurring_charges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    note TEXT NOT NULL,
    amount REAL NOT NULL,
    interval_months INTEGER NOT NULL,
    next_due_date TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

-- Idle-cash sweep audit trail (parking uninvested cash in a liquid-fund
-- ETF like LIQUIDCASE to earn interest instead of sitting idle) -- kept
-- entirely separate from `positions`/`trades` since this isn't a momentum
-- trade (no stop-loss, no ranking, never counts toward max_positions or
-- the Tradebook's win-rate/P&L stats). The real, current holding is never
-- tracked here -- always queried fresh from Kite (see live_rebalance.
-- get_cash_sweep_holding()) -- this table is pure history/audit, not a
-- source of truth for "how much do we hold right now".
CREATE TABLE IF NOT EXISTS cash_sweep_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    action TEXT NOT NULL,
    symbol TEXT NOT NULL,
    qty INTEGER NOT NULL,
    price REAL,
    amount REAL NOT NULL,
    reason TEXT,
    order_id TEXT
);

CREATE TABLE IF NOT EXISTS equity_log (
    date TEXT PRIMARY KEY,
    value REAL NOT NULL
);

-- Detected but not-yet-applied corporate actions (stock split / bonus
-- issue) on a currently-held position -- see live_rebalance.
-- detect_corporate_actions()/apply_corporate_action_adjustment(). A split
-- or bonus changes a stock's qty and price simultaneously at the broker
-- without any order this app placed, silently invalidating our own
-- entry_price/current_stop/highest_close bookkeeping AND the real GTT
-- stop-loss order sitting at the broker (still referencing the pre-split
-- qty/price) -- flagged for manual review/confirm rather than applied
-- automatically, since it touches a live stop-loss with real money behind
-- it. status: 'pending' | 'applied' | 'dismissed'.
CREATE TABLE IF NOT EXISTS corporate_action_flags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    position_id INTEGER,
    our_qty INTEGER NOT NULL,
    live_qty INTEGER NOT NULL,
    ratio REAL NOT NULL,
    old_entry_price REAL NOT NULL,
    old_current_stop REAL NOT NULL,
    old_highest_close REAL NOT NULL,
    old_gtt_trigger_id INTEGER,
    status TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS rebalance_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_time TEXT NOT NULL,
    open_slots INTEGER,
    status TEXT NOT NULL,
    error_message TEXT,
    target_per_slot REAL,
    cash_pool REAL,
    cash_needed_for_full_equal_weight REAL,
    cash_shortfall REAL,
    unsettled_proceeds REAL
);

-- status lifecycle (all 4 rebalance_* child tables below): 'proposed' ->
-- 'executed' (succeeded, resolved_at set) | 'error' (attempted, failed --
-- error_message set) | 'expired' (superseded by a newer rebalance run
-- before ever being acted on -- see save_rebalance_run()). Rows are never
-- deleted once inserted -- this preserves the full audit trail (what was
-- proposed, what actually happened to it) instead of the previous
-- behavior of physically deleting a row the moment it executed, which
-- lost that history entirely.
CREATE TABLE IF NOT EXISTS rebalance_sells (
    run_id INTEGER REFERENCES rebalance_runs(id),
    symbol TEXT, qty INTEGER, avg_price REAL, reason TEXT,
    status TEXT NOT NULL DEFAULT 'proposed', resolved_at TEXT, error_message TEXT
);

CREATE TABLE IF NOT EXISTS rebalance_buys (
    run_id INTEGER REFERENCES rebalance_runs(id),
    symbol TEXT, qty INTEGER, price REAL, stop REAL, score REAL,
    fundamental_score REAL, fundamental_rubric TEXT,
    rsi REAL, pct_52w_high REAL, vol_expansion REAL, reason TEXT,
    status TEXT NOT NULL DEFAULT 'proposed', resolved_at TEXT, error_message TEXT
);

CREATE TABLE IF NOT EXISTS rebalance_stop_updates (
    run_id INTEGER REFERENCES rebalance_runs(id),
    symbol TEXT, qty INTEGER, current_stop REAL, recommended_stop REAL,
    gtt_trigger_id INTEGER,
    status TEXT NOT NULL DEFAULT 'proposed', resolved_at TEXT, error_message TEXT
);

-- Proposed top-ups (screener.allocate_equal_weight_buys) -- additional
-- shares for an ALREADY-held position that's below its equal-weight
-- target, funded by cash left over after filling new-buy slots. Distinct
-- from rebalance_buys (which only ever opens brand-new positions).
CREATE TABLE IF NOT EXISTS rebalance_top_ups (
    run_id INTEGER REFERENCES rebalance_runs(id),
    symbol TEXT, extra_qty INTEGER, price REAL, gtt_trigger_id INTEGER,
    status TEXT NOT NULL DEFAULT 'proposed', resolved_at TEXT, error_message TEXT
);

-- Dashboard login gate. Singleton row, password stored as a salted hash
-- (PBKDF2-HMAC-SHA256) -- never in plaintext, unlike the .env value this
-- replaces.
CREATE TABLE IF NOT EXISTS dashboard_auth (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    username TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL
);

-- 'Remember me' cookie tokens (see create_remember_token()/
-- verify_remember_token() below) -- lets a browser skip the login form
-- across a service restart/reconnect within the same day. Only a SHA-256
-- hash of the token is stored, same reasoning as dashboard_auth's hashed
-- password: a stolen DB copy can't be replayed as a valid cookie.
CREATE TABLE IF NOT EXISTS remember_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

-- Strategy parameters (config.STRATEGY), editable from the dashboard's
-- Admin page instead of only via a config.py code edit + restart. One row
-- per key, value JSON-encoded so int/float/bool/str all round-trip cleanly
-- through a single TEXT column. Seeded once from config.py's in-code
-- defaults (see get_strategy_config) -- after that, the DB is the live
-- source of truth, same pattern as kite_credentials/dashboard_auth above.
CREATE TABLE IF NOT EXISTS strategy_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Kite Connect credentials. Singleton row. api_key/api_secret are stored
-- plaintext -- unlike dashboard_auth's password, these must be recoverable
-- (Kite's OAuth exchange needs the real api_secret value), so this is a
-- consolidation move, not a security upgrade, for those two. access_token
-- is a better fit for a DB than .env ever was: it's genuinely frequent-
-- changing live state (expires ~daily), same category as everything else
-- in this file.
CREATE TABLE IF NOT EXISTS kite_credentials (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    api_key TEXT NOT NULL,
    api_secret TEXT NOT NULL,
    access_token TEXT,
    access_token_updated_at TEXT
);

-- Unified execution log for every scheduled/background job (rebalance scan,
-- gap-down check, fundamentals refresh, and the dashboard's own manual
-- "Run screen"/"Run today's scan" buttons) -- see job_run() below. Before
-- this, only the rebalance scan had any persisted history at all
-- (rebalance_runs), and the other jobs had nothing queryable, only a
-- plain-text tail log.
CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_sec REAL,
    status TEXT NOT NULL DEFAULT 'running',
    summary TEXT,
    error_message TEXT
);

-- The tradebook -- a clean, append-only analytics ledger, separate from
-- `positions` (which stays focused on live trailing-stop bookkeeping).
-- Captures an entry-time technical/fundamental snapshot (for later
-- feature analytics) and a real exit reason on every closed trade, which
-- nothing in `positions` tracked before this.
-- Manually excluded symbols -- editable from Admin -- "Skip stocks from
-- scanner". Excluded from config.UNIVERSE (see config.refresh_universe()),
-- the single list the Screener, Live Rebalance, and backtest.py all fetch
-- candles for -- so a skip here takes effect everywhere at once, not just
-- one page.
CREATE TABLE IF NOT EXISTS skipped_symbols (
    symbol TEXT PRIMARY KEY,
    reason TEXT,
    added_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER REFERENCES positions(id),
    symbol TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    entry_price REAL NOT NULL,
    qty INTEGER NOT NULL,
    initial_stop REAL NOT NULL,
    entry_score REAL,
    entry_rsi REAL,
    entry_pct_52w_high REAL,
    entry_vol_expansion REAL,
    entry_fundamental_score REAL,
    entry_reason TEXT,
    exit_date TEXT,
    exit_price REAL,
    exit_reason TEXT,
    realized_pnl REAL,
    realized_ret_pct REAL,
    holding_days INTEGER,
    status TEXT NOT NULL DEFAULT 'open',
    updated_at TEXT
);

-- Browser push notification subscriptions (see notify.py, push_server.py,
-- static/sw.js) -- one row per device/browser that's clicked "Enable
-- notifications" in the dashboard. `endpoint` is the browser vendor's
-- push service URL for that specific subscription and is unique per
-- device, so it doubles as the natural primary key.
CREATE TABLE IF NOT EXISTS push_subscriptions (
    endpoint TEXT PRIMARY KEY,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Entry-confirmation streak (cfg["entry_confirm_days"]) -- backtest.py
-- tracks this as a plain in-memory dict across its own day-loop
-- (backtest.py:833, 1009-1020); live has no day-loop to hold that in
-- (every run is a fresh subprocess or a freshly-rebuilt background
-- thread), so it has to be persisted here instead. One row per symbol
-- CURRENTLY in the confirm-pool or that was at some point (a streak
-- resets to 0 rather than deleting the row, matching backtest's own
-- "sym not in confirm_syms_now -> streak = 0" reset, not removal).
-- last_confirmed_date is the idempotency key: update_entry_confirm_
-- streaks() no-ops for the whole batch if it already ran today, so a
-- double-fire (e.g. clicking "Run today's scan" twice) can't double-
-- increment every streak by mistake, same idea as paper_db.py's
-- paper_scans.scan_date UNIQUE guard, applied to a once-per-day batch
-- update instead of a per-scan row.
CREATE TABLE IF NOT EXISTS entry_confirm_streak (
    symbol TEXT PRIMARY KEY,
    streak INTEGER NOT NULL DEFAULT 0,
    last_confirmed_date TEXT NOT NULL
);
"""


def get_conn(db_path: str | None = None) -> sqlite3.Connection:
    """Row-factory'd connection; ensures schema exists (idempotent CREATE
    TABLE IF NOT EXISTS) on every call -- no separate init step to forget.

    db_path resolves DB_PATH at CALL time, not import time -- every other
    function in this module calls get_conn() with no argument, so this is
    what actually lets tests redirect state_db.DB_PATH to a throwaway file
    and have it take effect everywhere. A bare `db_path: str = DB_PATH`
    default would bind the value once at function-definition time and
    silently ignore a later `state_db.DB_PATH = ...` reassignment -- a real
    bug caught during verification (a test run wrote into the live
    cache/state.db instead of its intended throwaway file before this
    fix)."""
    db_path = db_path or DB_PATH
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    # timeout=30 (not sqlite3's 5s default): every call here re-runs the
    # full schema script + 9 migration functions below, and this is a
    # fresh connection per call (no long-lived shared one) -- under real
    # concurrency (a multi-minute background job's own state_db.job_run()
    # writes racing the main UI thread's own get_conn() calls on every
    # page rerun) that setup cost is enough for two connections to
    # genuinely collide, and 5s wasn't always enough margin to wait it
    # out (confirmed live: a multi-minute Intraday Backtest run crashed
    # the main thread with "database is locked" on ensure_dashboard_auth_
    # seeded()). WAL mode on top lets readers and the one writer proceed
    # without blocking each other at all, rather than just waiting longer
    # for the same rollback-journal exclusive lock -- but switching INTO
    # WAL mode itself needs a brief exclusive lock and can raise "database
    # is locked" immediately (doesn't honor timeout=) if another
    # connection is mid-transaction right then, so it's skipped once a
    # connection reports it's already in WAL (true for every connection
    # after the very first one ever succeeds). The retry loop below is
    # what actually absorbs that one-time race, plus the same-class race
    # in the migration functions' own check-then-ALTER pattern (confirmed
    # under a 25-thread stress test against a fresh DB).
    last_err = None
    for attempt in range(8):
        try:
            conn = sqlite3.connect(db_path, timeout=30)
            if conn.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
                conn.execute("PRAGMA journal_mode=WAL")
            conn.row_factory = sqlite3.Row
            conn.executescript(_SCHEMA)
            conn.commit()
            _migrate_equity_log_once(conn)
            _migrate_fund_state_to_cash_flow(conn)
            _migrate_positions_schema(conn)
            _migrate_stop_update_log_schema(conn)
            _migrate_trades_schema(conn)
            _migrate_rebalance_buys_schema(conn)
            _migrate_rebalance_runs_schema(conn)
            _migrate_rebalance_status_columns(conn)
            _migrate_equity_log_schema(conn)
            _migrate_backfill_missing_trades(conn)
            return conn
        except sqlite3.OperationalError as e:
            last_err = e
            if "locked" not in str(e).lower() and "duplicate column" not in str(e).lower():
                raise
            time.sleep(0.1 * (attempt + 1))
    raise last_err


def _migrate_equity_log_once(conn: sqlite3.Connection) -> None:
    """One-time carry-over of cache/equity_log.csv's existing rows -- not
    an ongoing dual-write, just preserves history from before this
    migration. No-ops once equity_log already has rows."""
    existing = conn.execute("SELECT COUNT(*) FROM equity_log").fetchone()[0]
    if existing or not os.path.exists(_LEGACY_EQUITY_LOG):
        return
    try:
        legacy = pd.read_csv(_LEGACY_EQUITY_LOG)
    except Exception:
        return
    for _, row in legacy.iterrows():
        conn.execute(
            "INSERT OR IGNORE INTO equity_log (date, value) VALUES (?, ?)",
            (row["date"], float(row["value"])),
        )
    conn.commit()


def _migrate_fund_state_to_cash_flow(conn: sqlite3.Connection) -> None:
    """One-time carry-over of the old fund_state singleton row (initial
    capital, auto-captured once) as the first cash_flows ledger entry --
    preserves the original captured date/amount instead of losing it when
    the ledger takes over. No-ops once cash_flows already has rows, or if
    fund_state was never populated."""
    existing = conn.execute("SELECT COUNT(*) FROM cash_flows").fetchone()[0]
    if existing:
        return
    row = conn.execute("SELECT * FROM fund_state WHERE id = 1").fetchone()
    if row is None:
        return
    conn.execute(
        "INSERT INTO cash_flows (date, amount, note) VALUES (?, ?, ?)",
        (
            row["captured_date"],
            row["initial_capital"],
            "Migrated from initial capital auto-capture",
        ),
    )
    conn.commit()


def _migrate_positions_schema(conn: sqlite3.Connection) -> None:
    """Adds exit_price/realized_pnl/recommended_stop columns to an
    already-existing positions table -- CREATE TABLE IF NOT EXISTS above
    doesn't touch a table that already exists, so new columns need this
    explicit, idempotent check.

    recommended_stop: the latest trailing-stop VALUE COMPUTED, shown to the
    user for approval -- current_stop now means only the APPLIED stop (what
    the real broker GTT is actually set to), never written outside
    apply_stop_update(). Before this column existed, update_position_stop()
    wrote straight into current_stop every day regardless of whether the
    user had actually applied it, so main_gap_check()'s gap-down comparison
    (live_rebalance.py) could silently compare against a stop the broker
    was never told about -- see apply_stop_update()'s docstring."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(positions)")}
    if "exit_price" not in cols:
        conn.execute("ALTER TABLE positions ADD COLUMN exit_price REAL")
    if "realized_pnl" not in cols:
        conn.execute("ALTER TABLE positions ADD COLUMN realized_pnl REAL")
    if "recommended_stop" not in cols:
        conn.execute("ALTER TABLE positions ADD COLUMN recommended_stop REAL")
    conn.commit()


def _migrate_trades_schema(conn: sqlite3.Connection) -> None:
    """Adds entry_reason to an already-existing trades table -- a
    human-readable one-liner (rank, score, RSI, fundamental score) built at
    entry time, alongside the raw numeric snapshot columns, so the
    tradebook is readable at a glance without cross-referencing every
    number by hand."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(trades)")}
    if "entry_reason" not in cols:
        conn.execute("ALTER TABLE trades ADD COLUMN entry_reason TEXT")
    if "updated_at" not in cols:
        conn.execute("ALTER TABLE trades ADD COLUMN updated_at TEXT")
    conn.commit()


_backfill_missing_trades_done = False


def _migrate_backfill_missing_trades(conn: sqlite3.Connection) -> None:
    """Any OPEN position without a matching OPEN trades row (bought before
    the trades/tradebook table existed) silently breaks top_up_trade()'s
    trades-side update -- it looks for an open trade to blend the top-up's
    extra shares/cost basis into, finds none, and no-ops, so the top-up
    shows in positions but never in the Tradebook. Real example: BHEL,
    LODHA, KALYANKJIL, SONACOMS were all bought before this table existed;
    their subsequent top-ups silently vanished from the Tradebook.
    Backfills one open trades row per such position from positions' own
    currently-known qty/entry_price/stop -- the actual entry-day technical/
    fundamental snapshot isn't recoverable retroactively, so those columns
    stay null, same convention every other optional trades column already
    uses.

    Only ever runs once per process (module-level guard below), NOT on
    every get_conn() call despite being invoked from get_conn() like the
    other migrations -- record_new_position() and record_trade_entry() each
    open their own connection, so a fresh buy has a real (if brief) window
    where the position is committed 'open' but its trades row hasn't been
    inserted yet. Re-running this on every call could catch that window and
    insert a phantom duplicate trades row that then never closes (close_
    trade() only ever closes the most recently inserted open match) --
    found via QA sandbox testing, where it fired on every single buy."""
    global _backfill_missing_trades_done
    if _backfill_missing_trades_done:
        return
    conn.execute(
        "INSERT INTO trades (position_id, symbol, entry_date, entry_price, "
        "qty, initial_stop, entry_reason, status) "
        "SELECT p.id, p.symbol, p.entry_date, p.entry_price, p.qty, "
        "p.current_stop, 'Backfilled -- position predates the trades table', "
        "'open' FROM positions p WHERE p.status = 'open' AND NOT EXISTS ("
        "SELECT 1 FROM trades t WHERE t.symbol = p.symbol AND t.status = 'open')"
    )
    conn.commit()
    _backfill_missing_trades_done = True


def _migrate_rebalance_buys_schema(conn: sqlite3.Connection) -> None:
    """Adds rsi/pct_52w_high/vol_expansion/reason to an already-existing
    rebalance_buys table -- these were already in propose_rebalance()'s
    in-memory buys dict but never persisted, so a page reload (reading
    back via get_last_rebalance_run() instead of a fresh propose_rebalance()
    call) would silently lose them."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(rebalance_buys)")}
    for col, coltype in [
        ("rsi", "REAL"),
        ("pct_52w_high", "REAL"),
        ("vol_expansion", "REAL"),
        ("reason", "TEXT"),
    ]:
        if col not in cols:
            conn.execute(f"ALTER TABLE rebalance_buys ADD COLUMN {col} {coltype}")
    conn.commit()


def _migrate_rebalance_runs_schema(conn: sqlite3.Connection) -> None:
    """Adds target_per_slot/cash_pool/cash_needed_for_full_equal_weight/
    cash_shortfall to an already-existing rebalance_runs table -- without
    this, those figures only ever lived in the in-memory result dict from
    the run that just computed them, and would silently vanish the moment
    a page reload re-read the proposal via get_last_rebalance_run()
    instead."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(rebalance_runs)")}
    for col in [
        "target_per_slot",
        "cash_pool",
        "cash_needed_for_full_equal_weight",
        "cash_shortfall",
        "unsettled_proceeds",
    ]:
        if col not in cols:
            conn.execute(f"ALTER TABLE rebalance_runs ADD COLUMN {col} REAL")
    conn.commit()


def _migrate_rebalance_status_columns(conn: sqlite3.Connection) -> None:
    """Adds status/resolved_at/error_message to the 4 already-existing
    rebalance_* child tables (sells/buys/top_ups/stop_updates) -- see the
    CREATE TABLE comment above for the status lifecycle. Existing rows
    (from before this migration) default to 'proposed' via the column
    default, same as any newly-inserted row -- there's no way to know in
    hindsight which of those already executed, so they're left as
    'proposed' rather than guessed at; the next real rebalance run's
    save_rebalance_run() call will correctly expire any that are still
    stale by then."""
    for table in (
        "rebalance_sells",
        "rebalance_buys",
        "rebalance_top_ups",
        "rebalance_stop_updates",
    ):
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if "status" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN status TEXT NOT NULL DEFAULT 'proposed'")
        if "resolved_at" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN resolved_at TEXT")
        if "error_message" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN error_message TEXT")
    conn.commit()


def _migrate_equity_log_schema(conn: sqlite3.Connection) -> None:
    """Adds invested_amount, then holdings_value, to an already-existing
    equity_log table.

    invested_amount lets the Overview page's chart overlay cost basis
    alongside total portfolio value, so growth from new capital vs actual
    returns is visually distinguishable.

    holdings_value (added later) is the market value of holdings ONLY,
    no cash -- `value` is cash+holdings, which made the chart's
    Invested-amount-vs-value comparison misleading whenever real cash
    was sitting uninvested (value looked inflated by idle cash that was
    never "invested" at all, same basis-mismatch class of bug as the
    Capital-allocation-per-stock fix). holdings_value is the correct,
    apples-to-apples counterpart to invested_amount.

    Both are only ever populated going forward (log_equity_snapshot is
    called once/day) -- there's no way to backfill historical figures
    for days before each column existed.

    excluded (added later): soft-delete flag for a snapshot later found
    to be corrupted (e.g. a stale/transient Kite margins read that got
    written as that day's value -- log_equity_snapshot's upsert has no
    sanity check against the previous day, so a bad read sticks
    permanently once written). get_equity_log() filters these out by
    default -- the row stays in the table for audit rather than being
    hard-deleted, see soft_delete_equity_log_date()."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(equity_log)")}
    if "invested_amount" not in cols:
        conn.execute("ALTER TABLE equity_log ADD COLUMN invested_amount REAL")
    if "holdings_value" not in cols:
        conn.execute("ALTER TABLE equity_log ADD COLUMN holdings_value REAL")
    if "soft_deleted" not in cols:
        # Named soft_deleted, not "excluded" -- SQLite's own ON CONFLICT
        # DO UPDATE clause (log_equity_snapshot() above) already uses
        # "excluded" as its reserved pseudo-table name for the row being
        # inserted; naming a real column that too would be a confusing
        # collision risk for anyone editing that UPSERT later.
        conn.execute("ALTER TABLE equity_log ADD COLUMN soft_deleted INTEGER NOT NULL DEFAULT 0")
    conn.commit()


def _migrate_stop_update_log_schema(conn: sqlite3.Connection) -> None:
    """Adds atr_value/ratcheted columns to an already-existing
    stop_update_log table. atr_value: the raw ATR reading that day's stop
    was computed from (never persisted before this -- only the resulting
    old_stop/new_stop pair was, and only on days the stop actually
    ratcheted). ratcheted: whether THIS row's check actually raised the
    stop -- update_position_stop() now inserts a row every day it runs, not
    only on ratchet days, so a continuous daily history exists."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(stop_update_log)")}
    if "atr_value" not in cols:
        conn.execute("ALTER TABLE stop_update_log ADD COLUMN atr_value REAL")
    if "ratcheted" not in cols:
        conn.execute("ALTER TABLE stop_update_log ADD COLUMN ratcheted INTEGER NOT NULL DEFAULT 0")
    conn.commit()


# ---------------------------------------------------------------------------
# Positions (trailing-stop tracking)
# ---------------------------------------------------------------------------


def record_new_position(
    symbol: str, entry_price: float, qty: int, stop: float, gtt_trigger_id: int | None
) -> int:
    """Call right after a buy (+ GTT, if placed) succeeds -- seeds this
    symbol's trailing-stop bookkeeping. gtt_trigger_id=None if the GTT
    placement failed or was skipped. Returns the new position's row id --
    pass it to record_trade_entry() as position_id to link the tradebook
    row back to this position."""
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO positions (symbol, entry_date, entry_price, qty, "
        "highest_close, current_stop, gtt_trigger_id, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'open')",
        (symbol, dt.date.today().isoformat(), entry_price, qty, entry_price, stop, gtt_trigger_id),
    )
    position_id = cur.lastrowid
    conn.commit()
    conn.close()
    return position_id


def get_stale_open_symbols(held_symbols: set[str]) -> list[str]:
    """Open positions no longer in held_symbols -- about to be closed on the
    next reconciled_positions() call. Callers fetch an LTP for these first
    (e.g. via kite_client.get_ltp()) so reconciled_positions() can record a
    realized exit price -- state_db.py itself can't call kite_client (it
    would be a circular import, since kite_client already imports state_db)."""
    conn = get_conn()
    open_rows = conn.execute("SELECT symbol FROM positions WHERE status = 'open'").fetchall()
    conn.close()
    return [r["symbol"] for r in open_rows if r["symbol"] not in held_symbols]


def reconciled_positions(
    held_symbols: set[str], exit_prices: dict[str, float] | None = None
) -> dict[str, dict]:
    """Marks any 'open' row whose symbol isn't in held_symbols as 'closed'
    (closed_date=today) instead of deleting -- a GTT can close a position
    without any of this app's code running, so every read reconciles
    against real Kite holdings first; history is preserved rather than
    silently dropped. Returns the remaining open positions, keyed by
    symbol, same dict shape the old JSON version returned.

    exit_prices, if supplied (keyed by symbol, from get_stale_open_symbols()
    + a fresh LTP fetch), also records exit_price and
    realized_pnl = (exit_price - entry_price) * qty on the closing row --
    Kite's API only exposes today's trades/orders, no historical realized-
    P&L endpoint, so this LTP-at-detection-time approximation is this app's
    own reconstruction of it. Left null if no price was supplied for a
    given symbol (caller chose to skip the extra LTP call).

    Also closes the matching trades row (see close_trade()) tagged
    exit_reason='gtt_fill_or_external' -- this is the guaranteed-leftover
    path: every KNOWN exit (gap-down stop, rebalance sell, manual
    square-off) closes its trades row explicitly, with its own specific
    reason, before this function next runs for that symbol. Anything still
    caught here can only be a GTT that fired silently at the broker, or an
    out-of-band manual sell outside this app -- close_trade() no-ops
    harmlessly if an explicit call already closed the trade first."""
    exit_prices = exit_prices or {}
    conn = get_conn()
    open_rows = conn.execute("SELECT * FROM positions WHERE status = 'open'").fetchall()
    today = dt.date.today().isoformat()
    newly_closed = []
    for row in open_rows:
        if row["symbol"] not in held_symbols:
            exit_price = exit_prices.get(row["symbol"])
            realized_pnl = (
                (exit_price - row["entry_price"]) * row["qty"] if exit_price is not None else None
            )
            conn.execute(
                "UPDATE positions SET status = 'closed', closed_date = ?, "
                "exit_price = ?, realized_pnl = ? WHERE id = ?",
                (today, exit_price, realized_pnl, row["id"]),
            )
            newly_closed.append((row["symbol"], exit_price))
    conn.commit()
    remaining = conn.execute("SELECT * FROM positions WHERE status = 'open'").fetchall()
    conn.close()
    for symbol, exit_price in newly_closed:
        close_trade(symbol, exit_price, "gtt_fill_or_external")
    return {r["symbol"]: dict(r) for r in remaining}


def close_position(symbol: str, exit_price: float | None) -> None:
    """Closes the open positions row for symbol immediately (status='closed',
    closed_date=today, exit_price/realized_pnl same convention as
    reconciled_positions()). Call this right after a known, immediate exit
    (manual square-off, rebalance sell) instead of waiting for the next
    scan's reconciled_positions() pass -- without it, get_open_positions()
    keeps counting the symbol as open (inflating the topbar's Slots chip)
    until the next scheduled scan or gap-check happens to run. No-ops if
    there's no open position for this symbol."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM positions WHERE symbol = ? AND status = 'open'", (symbol,)
    ).fetchone()
    if row is None:
        conn.close()
        return
    realized_pnl = (
        (exit_price - row["entry_price"]) * row["qty"] if exit_price is not None else None
    )
    conn.execute(
        "UPDATE positions SET status = 'closed', closed_date = ?, "
        "exit_price = ?, realized_pnl = ? WHERE id = ?",
        (dt.date.today().isoformat(), exit_price, realized_pnl, row["id"]),
    )
    conn.commit()
    conn.close()


def get_realized_pnl() -> float:
    """SUM(realized_pnl) over all closed positions -- null entries (closed
    without a supplied exit price) don't contribute, same as SQL SUM's
    normal NULL handling."""
    conn = get_conn()
    row = conn.execute(
        "SELECT SUM(realized_pnl) AS total FROM positions WHERE status = 'closed'"
    ).fetchone()
    conn.close()
    return float(row["total"]) if row["total"] is not None else 0.0


def update_position_stop(
    symbol: str, highest_close: float, atr_value: float, new_stop: float
) -> None:
    """Called once daily (from live_rebalance.py's compute_stop_updates())
    for every open position, ratchet or not -- records a stop_update_log
    row EVERY time (atr_value + whether this check actually ratcheted the
    stop), so a continuous daily ATR/stop history exists, not just a trail
    of ratchet events.

    Writes the computed candidate into positions.recommended_stop only --
    never positions.current_stop. current_stop means the stop actually
    APPLIED at the broker (see apply_stop_update()) and must only change
    when an Apply action really pushes it to the real GTT; main_gap_check()
    compares live LTP against current_stop specifically because it needs
    the real, broker-side stop, not a theoretical unapplied one."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM positions WHERE symbol = ? AND status = 'open'", (symbol,)
    ).fetchone()
    if row is None:
        conn.close()
        return
    ratcheted = new_stop > row["current_stop"]
    conn.execute(
        "INSERT INTO stop_update_log (position_id, date, old_stop, "
        "new_stop, atr_value, ratcheted, applied) VALUES (?, ?, ?, ?, ?, ?, 0)",
        (
            row["id"],
            dt.date.today().isoformat(),
            row["current_stop"],
            new_stop,
            atr_value,
            int(ratcheted),
        ),
    )
    conn.execute(
        "UPDATE positions SET highest_close = ?, recommended_stop = ?, "
        "updated_at = datetime('now') WHERE id = ?",
        (highest_close, max(new_stop, row["current_stop"]), row["id"]),
    )
    conn.commit()
    conn.close()


def apply_stop_update(symbol: str) -> float | None:
    """Call right after kite_client.modify_gtt_trigger(...) succeeds for
    this symbol's open position -- copies recommended_stop into
    current_stop (the applied, broker-real stop) and marks that position's
    most recent stop_update_log row as applied. Returns the new applied
    stop, or None if there's no open position / nothing recommended.

    Only the MOST RECENT stop_update_log row is marked applied, not every
    unapplied one -- if a stop was recommended on day 1 but not applied
    until day 3 (by which point day 2 had already recommended a higher
    value), only day 2's row ever actually reached the broker; day 1's
    row stays unapplied, accurately reflecting that its value was
    superseded before ever being pushed."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM positions WHERE symbol = ? AND status = 'open'", (symbol,)
    ).fetchone()
    if row is None or row["recommended_stop"] is None:
        conn.close()
        return None
    new_current = row["recommended_stop"]
    conn.execute(
        "UPDATE positions SET current_stop = ?, updated_at = datetime('now') WHERE id = ?",
        (new_current, row["id"]),
    )
    last_log_id = conn.execute(
        "SELECT id FROM stop_update_log WHERE position_id = ? ORDER BY id DESC LIMIT 1",
        (row["id"],),
    ).fetchone()
    if last_log_id is not None:
        conn.execute("UPDATE stop_update_log SET applied = 1 WHERE id = ?", (last_log_id["id"],))
    conn.commit()
    conn.close()
    return float(new_current)


def get_open_positions() -> dict[str, dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM positions WHERE status = 'open'").fetchall()
    conn.close()
    return {r["symbol"]: dict(r) for r in rows}


def has_pending_corporate_action_flag(symbol: str) -> bool:
    """Idempotency guard for detect_corporate_actions() -- one pending
    flag per symbol at a time, so a daily re-detect doesn't pile up
    duplicate rows for the same still-unresolved split/bonus."""
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM corporate_action_flags WHERE symbol = ? AND status = 'pending'", (symbol,)
    ).fetchone()
    conn.close()
    return row is not None


def insert_corporate_action_flag(
    symbol: str,
    position_id: int | None,
    our_qty: int,
    live_qty: int,
    ratio: float,
    old_entry_price: float,
    old_current_stop: float,
    old_highest_close: float,
    old_gtt_trigger_id: int | None,
) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO corporate_action_flags (detected_date, symbol, position_id, "
        "our_qty, live_qty, ratio, old_entry_price, old_current_stop, "
        "old_highest_close, old_gtt_trigger_id, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
        (
            dt.date.today().isoformat(),
            symbol,
            position_id,
            our_qty,
            live_qty,
            ratio,
            old_entry_price,
            old_current_stop,
            old_highest_close,
            old_gtt_trigger_id,
        ),
    )
    conn.commit()
    conn.close()


def get_corporate_action_flags(status: str | None = "pending") -> pd.DataFrame:
    conn = get_conn()
    if status:
        df = pd.read_sql(
            "SELECT * FROM corporate_action_flags WHERE status = ? "
            "ORDER BY detected_date DESC, id DESC",
            conn,
            params=(status,),
        )
    else:
        df = pd.read_sql(
            "SELECT * FROM corporate_action_flags ORDER BY detected_date DESC, id DESC", conn
        )
    conn.close()
    return df


def resolve_corporate_action_flag(flag_id: int, status: str) -> None:
    """status: 'applied' or 'dismissed'."""
    conn = get_conn()
    conn.execute("UPDATE corporate_action_flags SET status = ? WHERE id = ?", (status, flag_id))
    conn.commit()
    conn.close()


def apply_corporate_action_to_position(
    position_id: int,
    new_qty: int,
    new_entry_price: float,
    new_current_stop: float,
    new_highest_close: float,
) -> None:
    """Rescales one position's bookkeeping after a confirmed split/bonus --
    see live_rebalance.apply_corporate_action_adjustment(). recommended_stop
    is rescaled too when it was already set (proportionally, same ratio),
    left NULL otherwise."""
    conn = get_conn()
    row = conn.execute(
        "SELECT recommended_stop FROM positions WHERE id = ?", (position_id,)
    ).fetchone()
    new_recommended = None
    if row is not None and row["recommended_stop"] is not None:
        old_row = conn.execute(
            "SELECT current_stop FROM positions WHERE id = ?", (position_id,)
        ).fetchone()
        if old_row is not None and old_row["current_stop"]:
            ratio = new_current_stop / old_row["current_stop"]
            new_recommended = row["recommended_stop"] * ratio
    conn.execute(
        "UPDATE positions SET qty = ?, entry_price = ?, current_stop = ?, "
        "highest_close = ?, recommended_stop = ?, updated_at = datetime('now') "
        "WHERE id = ?",
        (
            new_qty,
            new_entry_price,
            new_current_stop,
            new_highest_close,
            new_recommended,
            position_id,
        ),
    )
    conn.commit()
    conn.close()


def apply_corporate_action_to_trade(
    symbol: str, new_qty: int, new_entry_price: float, new_initial_stop: float
) -> None:
    """Rescales the matching OPEN trades row so realized P&L stays correct
    once this position eventually closes -- otherwise entry_price would
    stay in pre-split terms while qty/exit_price are post-split."""
    conn = get_conn()
    conn.execute(
        "UPDATE trades SET qty = ?, entry_price = ?, initial_stop = ? "
        "WHERE symbol = ? AND status = 'open'",
        (new_qty, new_entry_price, new_initial_stop, symbol),
    )
    conn.commit()
    conn.close()


def get_stop_update_log(position_id: int) -> pd.DataFrame:
    """Full daily stop-computation history for one position -- date,
    old_stop, new_stop, atr_value, ratcheted, applied -- as written by
    update_position_stop()/apply_stop_update(). One row per day the daily
    job actually ran for this position; empty if the position predates
    this log (added later than the position itself) or the daily job
    never ran for it (e.g. a same-day-closed trade). Used by the
    Tradebook's trade chart to show the REAL history live actually
    computed and applied, instead of re-simulating it."""
    conn = get_conn()
    df = pd.read_sql(
        "SELECT date, old_stop, new_stop, atr_value, ratcheted, applied "
        "FROM stop_update_log WHERE position_id = ? ORDER BY date, id",
        conn,
        params=(position_id,),
    )
    conn.close()
    return df


def top_up_trade(symbol: str, extra_qty: int, price: float) -> None:
    """Call right after buying MORE shares of an ALREADY-open position
    (screener.allocate_equal_weight_buys' top-up mechanic) succeeds --
    weighted-averages the cost basis into both the positions row (qty,
    entry_price) and the matching open trades row, mirroring backtest.py's
    top_up_position(). Distinct from record_new_position(), which only
    ever opens a brand-new position. No-ops if there's no open position
    for this symbol."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM positions WHERE symbol = ? AND status = 'open'", (symbol,)
    ).fetchone()
    if row is None or extra_qty <= 0:
        conn.close()
        return
    new_qty = row["qty"] + extra_qty
    new_entry_price = (row["entry_price"] * row["qty"] + price * extra_qty) / new_qty
    conn.execute(
        "UPDATE positions SET qty = ?, entry_price = ?, updated_at = datetime('now') WHERE id = ?",
        (new_qty, new_entry_price, row["id"]),
    )
    conn.commit()
    conn.close()

    trades_conn = get_conn()
    trade_row = trades_conn.execute(
        "SELECT * FROM trades WHERE symbol = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    if trade_row is not None:
        t_new_qty = trade_row["qty"] + extra_qty
        t_new_entry = (trade_row["entry_price"] * trade_row["qty"] + price * extra_qty) / t_new_qty
        trades_conn.execute(
            "UPDATE trades SET qty = ?, entry_price = ?, updated_at = ? WHERE id = ?",
            (t_new_qty, t_new_entry, dt.datetime.now().isoformat(), trade_row["id"]),
        )
        trades_conn.commit()
    trades_conn.close()


def upsert_manual_position(
    symbol: str, entry_price: float, qty: int, stop: float, gtt_trigger_id: int | None
) -> None:
    """Used when placing a stop-loss for a position this app didn't itself
    open (e.g. bought directly on Kite, outside the Live Rebalance/manual-
    order flows) -- creates a new open position row if none exists yet
    (using Kite's own real entry_price/qty for that symbol), or just updates
    the current_stop/gtt_trigger_id if one already does (e.g. re-placing a
    GTT that expired or was cancelled). Either way, the position becomes
    fully known to reconciled_positions()/get_open_positions() afterward, so
    future trailing-stop updates pick it up like any other position.

    Also seeds a matching trades row (empty snapshot -- no screener data
    exists for a position this app didn't pick) on the first-insert path
    only, so this position's eventual close still has an open trade row
    for close_trade() to find -- otherwise it would only ever be caught by
    reconciled_positions()'s generic fallback with no trades row to close
    at all, silently missing it from the tradebook entirely."""
    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM positions WHERE symbol = ? AND status = 'open'", (symbol,)
    ).fetchone()
    if row is None:
        cur = conn.execute(
            "INSERT INTO positions (symbol, entry_date, entry_price, qty, "
            "highest_close, current_stop, gtt_trigger_id, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'open')",
            (
                symbol,
                dt.date.today().isoformat(),
                entry_price,
                qty,
                entry_price,
                stop,
                gtt_trigger_id,
            ),
        )
        new_position_id = cur.lastrowid
        conn.commit()
        conn.close()
        record_trade_entry(
            symbol,
            entry_price,
            qty,
            stop,
            snapshot={
                "entry_reason": "Backfilled -- bought outside this app "
                "(e.g. directly on Kite), stop-loss added here after the fact"
            },
            position_id=new_position_id,
        )
        return
    conn.execute(
        "UPDATE positions SET current_stop = ?, gtt_trigger_id = ?, "
        "updated_at = datetime('now') WHERE id = ?",
        (stop, gtt_trigger_id, row["id"]),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Cash-flow ledger -- every deposit/withdrawal, dated. Supersedes the old
# fund_state singleton row (see _migrate_fund_state_to_cash_flow): a proper
# ledger lets XIRR account for deposit timing, not just a single starting
# amount, matching the user's stated plan to add money monthly.
# ---------------------------------------------------------------------------


def record_cash_flow(date: str, amount: float, note: str = "") -> None:
    """Manual entry -- called from the Admin page's deposit/withdrawal
    form. amount is positive for a deposit, negative for a withdrawal.
    Kite's API has no visibility into bank transfers, so this can't be
    automated beyond the very first entry (see
    ensure_first_cash_flow_captured)."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO cash_flows (date, amount, note) VALUES (?, ?, ?)", (date, amount, note)
    )
    conn.commit()
    conn.close()


def get_cash_flows() -> pd.DataFrame:
    """Full ledger, oldest first -- feeds the XIRR calc and the Admin
    page's audit-trail table. Includes `id` so the Admin page's editable
    table can target a specific row for update/delete -- callers that
    only need date/amount/note (the XIRR calc) can simply ignore it."""
    conn = get_conn()
    log = pd.read_sql("SELECT id, date, amount, note FROM cash_flows ORDER BY date, id", conn)
    conn.close()
    return log


def update_cash_flow(id: int, date: str, amount: float, note: str = "") -> None:
    """Corrects an existing entry (wrong date/amount/note typo) in place --
    used by the Admin page's editable ledger table."""
    conn = get_conn()
    conn.execute(
        "UPDATE cash_flows SET date = ?, amount = ?, note = ? WHERE id = ?",
        (date, amount, note, id),
    )
    conn.commit()
    conn.close()


def delete_cash_flow(id: int) -> None:
    """Removes an entry logged in error -- used by the Admin page's
    editable ledger table."""
    conn = get_conn()
    conn.execute("DELETE FROM cash_flows WHERE id = ?", (id,))
    conn.commit()
    conn.close()


def _add_months(date_iso: str, months: int) -> str:
    """Calendar-correct month add (not a fixed day-count) -- a charge
    anchored to e.g. the 24th stays on the 24th every cycle instead of
    drifting. Clamps to the target month's last day for an overflow (e.g.
    31 Jan + 1 month -> 28/29 Feb)."""
    import calendar

    d = dt.date.fromisoformat(date_iso)
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day).isoformat()


def get_recurring_charges() -> pd.DataFrame:
    """Every recurring-charge definition (e.g. quarterly Demat AMC),
    active or not -- the Ledger page's own small CRUD section, separate
    from the one-off manual cash_flows entries."""
    conn = get_conn()
    df = pd.read_sql(
        "SELECT id, note, amount, interval_months, next_due_date, active "
        "FROM recurring_charges ORDER BY next_due_date, id",
        conn,
    )
    conn.close()
    return df


def add_recurring_charge(
    note: str, amount: float, interval_months: int, next_due_date: str
) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO recurring_charges (note, amount, interval_months, "
        "next_due_date, active) VALUES (?, ?, ?, ?, 1)",
        (note, amount, interval_months, next_due_date),
    )
    conn.commit()
    conn.close()


def update_recurring_charge(
    id: int, note: str, amount: float, interval_months: int, next_due_date: str, active: bool
) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE recurring_charges SET note = ?, amount = ?, interval_months = ?, "
        "next_due_date = ?, active = ? WHERE id = ?",
        (note, amount, interval_months, next_due_date, int(active), id),
    )
    conn.commit()
    conn.close()


def delete_recurring_charge(id: int) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM recurring_charges WHERE id = ?", (id,))
    conn.commit()
    conn.close()


def post_due_recurring_charges() -> list[str]:
    """Posts a cash_flows entry (dated on the actual due date, not
    necessarily today, so a late-running job doesn't misdate it) for every
    active recurring charge whose next_due_date has arrived, then advances
    next_due_date by interval_months -- looped, in case more than one
    cycle was missed (e.g. the job didn't run for a while). Safe to call
    every day: a charge not yet due is untouched. Returns a log line per
    charge actually posted, for the caller's own run log."""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM recurring_charges WHERE active = 1").fetchall()
    conn.close()
    today = dt.date.today().isoformat()
    posted = []
    for row in rows:
        due = row["next_due_date"]
        while due <= today:
            record_cash_flow(due, -abs(row["amount"]), row["note"])
            posted.append(f"{row['note']}: Rs.{row['amount']:.2f} posted for {due}")
            due = _add_months(due, row["interval_months"])
        if due != row["next_due_date"]:
            conn = get_conn()
            conn.execute(
                "UPDATE recurring_charges SET next_due_date = ? WHERE id = ?", (due, row["id"])
            )
            conn.commit()
            conn.close()
    return posted


def record_cash_sweep(
    date: str,
    action: str,
    symbol: str,
    qty: int,
    price: float,
    amount: float,
    reason: str,
    order_id: str | None = None,
) -> None:
    """One row per real buy/sell of the cash-sweep instrument -- see
    live_rebalance.sweep_idle_cash()/ensure_cash_for_buys(). Pure audit
    trail; not the source of truth for the current holding (that's always
    queried fresh from Kite)."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO cash_sweep_log (date, action, symbol, qty, price, amount, "
        "reason, order_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (date, action, symbol, qty, price, amount, reason, order_id),
    )
    conn.commit()
    conn.close()


def get_cash_sweep_log() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql(
        "SELECT date, action, symbol, qty, price, amount, reason, order_id "
        "FROM cash_sweep_log ORDER BY date DESC, id DESC",
        conn,
    )
    conn.close()
    return df


def ensure_first_cash_flow_captured(available_cash: float) -> None:
    """Auto-captures the very first deposit from Kite's own available cash,
    the first time it's non-zero and the ledger is still empty -- same
    first-time-only behavior capture_initial_capital used to provide, so
    the user isn't required to manually log money already sitting in the
    account. Every deposit after this one is manual (Admin page), per the
    user's plan to add money monthly."""
    conn = get_conn()
    existing = conn.execute("SELECT COUNT(*) FROM cash_flows").fetchone()[0]
    conn.close()
    if existing or available_cash <= 0:
        return
    record_cash_flow(
        dt.date.today().isoformat(), available_cash, "Auto-captured initial available cash"
    )


# ---------------------------------------------------------------------------
# Equity log
# ---------------------------------------------------------------------------


def log_equity_snapshot(
    value: float, invested_amount: float | None = None, holdings_value: float | None = None
) -> pd.DataFrame:
    """Upserts today's portfolio value (and optionally cost basis /
    holdings-only market value, for the Overview page's chart); returns
    the full log as a DataFrame with ["date", "value", "invested_amount",
    "holdings_value"]. Uses COALESCE on conflict rather than a blind
    overwrite -- this runs on every page load, so a later call that
    doesn't pass invested_amount/holdings_value (or an older caller that
    doesn't know about them) won't silently wipe out a value an earlier
    call already recorded for today."""
    conn = get_conn()
    today = dt.date.today().isoformat()
    conn.execute(
        "INSERT INTO equity_log (date, value, invested_amount, holdings_value) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(date) DO UPDATE SET value = excluded.value, "
        "invested_amount = COALESCE(excluded.invested_amount, equity_log.invested_amount), "
        "holdings_value = COALESCE(excluded.holdings_value, equity_log.holdings_value)",
        (today, value, invested_amount, holdings_value),
    )
    conn.commit()
    log = pd.read_sql(
        "SELECT date, value, invested_amount, holdings_value FROM equity_log ORDER BY date", conn
    )
    conn.close()
    return log


def get_equity_log(include_soft_deleted: bool = False) -> pd.DataFrame:
    """Read-only variant of log_equity_snapshot() for callers that want
    today's chart data WITHOUT writing a new row -- e.g. page_cockpit()
    skips the write entirely when the freshly-computed portfolio_value
    looks invalid (a Kite auth failure or transient fetch error silently
    returning 0 would otherwise get logged as a real snapshot and put a
    fake drop-to-zero in the equity curve; this happened for real before
    this guard existed -- see the 2026-07-18..24 rows manually cleaned
    up from a live install).

    Soft-deleted rows (soft_deleted=1, see
    soft_delete_equity_log_date()) are filtered out by default -- every
    normal reader (the equity chart, XIRR, max-drawdown, day-change)
    should never see them. Pass include_soft_deleted=True only for an
    audit/admin view of the full, uncensored history."""
    conn = get_conn()
    where = "" if include_soft_deleted else "WHERE soft_deleted = 0"
    log = pd.read_sql(
        f"SELECT date, value, invested_amount, holdings_value, soft_deleted "
        f"FROM equity_log {where} ORDER BY date",
        conn,
    )
    conn.close()
    return log


def soft_delete_equity_log_date(date: str, deleted: bool = True) -> None:
    """Marks (or unmarks) one equity_log row as soft-deleted -- for a
    snapshot later found to be corrupted (e.g. a stale Kite margins read
    that got written as that day's value, see log_equity_snapshot's own
    docstring). The row stays in the table -- get_equity_log() just
    filters it out by default -- rather than a hard DELETE, so it's
    reversible and still there for audit if needed."""
    conn = get_conn()
    conn.execute("UPDATE equity_log SET soft_deleted = ? WHERE date = ?", (int(deleted), date))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Rebalance run history (replaces rebalance_proposal.pkl)
# ---------------------------------------------------------------------------


def save_rebalance_run(result: dict) -> int:
    """Persists a propose_rebalance() result dict (run_time, sells, buys,
    stop_updates, holdings, open_slots) -- returns the new run_id.

    Before inserting the new run's rows, marks any still-'proposed' row
    from a PREVIOUS run as 'expired' -- a fresh scan supersedes whatever
    was proposed before (rankings/prices/holdings have moved on), so an
    old sell/buy/top-up/stop-update nobody acted on shouldn't linger as
    'proposed' forever once a newer proposal exists."""
    conn = get_conn()
    now = dt.datetime.now().isoformat()
    for table in (
        "rebalance_sells",
        "rebalance_buys",
        "rebalance_top_ups",
        "rebalance_stop_updates",
    ):
        conn.execute(
            f"UPDATE {table} SET status = 'expired', resolved_at = ? WHERE status = 'proposed'",
            (now,),
        )
    cur = conn.execute(
        "INSERT INTO rebalance_runs (run_time, open_slots, status, "
        "target_per_slot, cash_pool, cash_needed_for_full_equal_weight, "
        "cash_shortfall, unsettled_proceeds) VALUES (?, ?, 'success', ?, ?, ?, ?, ?)",
        (
            result["run_time"].isoformat(),
            int(result["open_slots"]),
            result.get("target_per_slot"),
            result.get("cash_pool"),
            result.get("cash_needed_for_full_equal_weight"),
            result.get("cash_shortfall"),
            result.get("unsettled_proceeds"),
        ),
    )
    run_id = cur.lastrowid
    for _, r in result["sells"].iterrows():
        conn.execute(
            "INSERT INTO rebalance_sells (run_id, symbol, qty, avg_price, reason) "
            "VALUES (?, ?, ?, ?, ?)",
            (run_id, r["symbol"], int(r["qty"]), float(r["avg_price"]), r["reason"]),
        )
    for _, r in result["buys"].iterrows():
        fscore = r.get("fundamental_score")
        conn.execute(
            "INSERT INTO rebalance_buys (run_id, symbol, qty, price, stop, score, "
            "fundamental_score, fundamental_rubric, rsi, pct_52w_high, "
            "vol_expansion, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                r["symbol"],
                int(r["qty"]),
                float(r["price"]),
                float(r["stop"]),
                float(r["score"]),
                None if pd.isna(fscore) else float(fscore),
                r.get("fundamental_rubric"),
                r.get("rsi"),
                r.get("pct_52w_high"),
                r.get("vol_expansion"),
                r.get("reason"),
            ),
        )
    for _, r in result.get("stop_updates", pd.DataFrame()).iterrows():
        conn.execute(
            "INSERT INTO rebalance_stop_updates (run_id, symbol, qty, current_stop, "
            "recommended_stop, gtt_trigger_id) VALUES (?, ?, ?, ?, ?, ?)",
            (
                run_id,
                r["symbol"],
                int(r["qty"]),
                float(r["current_stop"]),
                float(r["recommended_stop"]),
                None if pd.isna(r["gtt_trigger_id"]) else int(r["gtt_trigger_id"]),
            ),
        )
    for _, r in result.get("top_ups", pd.DataFrame()).iterrows():
        conn.execute(
            "INSERT INTO rebalance_top_ups (run_id, symbol, extra_qty, price, "
            "gtt_trigger_id) VALUES (?, ?, ?, ?, ?)",
            (
                run_id,
                r["symbol"],
                int(r["extra_qty"]),
                float(r["price"]),
                None if pd.isna(r["gtt_trigger_id"]) else int(r["gtt_trigger_id"]),
            ),
        )
    conn.commit()
    conn.close()
    return run_id


def save_rebalance_failure(error_message: str) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO rebalance_runs (run_time, status, error_message) VALUES (?, 'failed', ?)",
        (dt.datetime.now().isoformat(), error_message),
    )
    conn.commit()
    conn.close()


def get_rebalance_run_items(run_id: int) -> dict:
    """Like get_last_rebalance_run()'s sells/buys/top_ups/stop_updates
    queries, but EVERY status for this run_id (not status='proposed' only),
    each row carrying its own 'status' -- the single-run building block
    get_rebalance_day_items() below uses to cover a whole day's worth of
    runs at once. Deliberately a SEPARATE function rather than changing
    get_last_rebalance_run() itself: trading_service.py's auto-execute
    loop and the Overview/sidebar 'likely exit' hints both depend on that
    function's proposed-only filtering to know what's still actually
    pending -- broadening it would make already-resolved items look
    pending again there."""
    conn = get_conn()
    sells = pd.read_sql(
        "SELECT symbol, qty, avg_price, reason, status FROM rebalance_sells WHERE run_id = ?",
        conn,
        params=(run_id,),
    )
    buys = pd.read_sql(
        "SELECT symbol, qty, price, stop, score, fundamental_score, "
        "fundamental_rubric, rsi, pct_52w_high, vol_expansion, reason, status "
        "FROM rebalance_buys WHERE run_id = ?",
        conn,
        params=(run_id,),
    )
    stop_updates = pd.read_sql(
        "SELECT symbol, qty, current_stop, recommended_stop, gtt_trigger_id, status "
        "FROM rebalance_stop_updates WHERE run_id = ?",
        conn,
        params=(run_id,),
    )
    top_ups = pd.read_sql(
        "SELECT symbol, extra_qty, price, gtt_trigger_id, status "
        "FROM rebalance_top_ups WHERE run_id = ?",
        conn,
        params=(run_id,),
    )
    conn.close()
    return {"sells": sells, "buys": buys, "stop_updates": stop_updates, "top_ups": top_ups}


def get_rebalance_day_items(date: str) -> dict:
    """Like get_rebalance_run_items(), but aggregates EVERY run's items
    for a given calendar date (YYYY-MM-DD, matched against rebalance_runs.
    run_time) instead of a single run_id -- so the Live Rebalance page's
    Proposed sells/buys/top-ups/stop-updates sections can show the FULL
    day's activity (e.g. an early auto-execute run followed by a later
    manual re-scan that found nothing new) with each row's own status,
    rather than only the single latest run in isolation. Each row also
    carries run_id/run_time so multiple runs' items are distinguishable
    once merged into one table. Newest run first.

    Duplicate symbols across runs the same day (e.g. a top-up proposed at
    10am, superseded by a re-proposal at 2pm) are NOT deduped here --
    save_rebalance_run()'s own expiry step already marks the earlier one
    'expired' when a later run re-proposes the same symbol, so only ever
    one row per symbol carries status='proposed' at a time; both rows are
    kept so the day's full history stays visible, exactly like
    get_rebalance_run_items()'s single-run version already does within
    one run."""
    conn = get_conn()
    like = f"{date}%"
    sells = pd.read_sql(
        "SELECT rb.symbol, rb.qty, rb.avg_price, rb.reason, rb.status, "
        "rb.run_id, rr.run_time FROM rebalance_sells rb "
        "JOIN rebalance_runs rr ON rb.run_id = rr.id "
        "WHERE rr.run_time LIKE ? ORDER BY rr.run_time DESC",
        conn,
        params=(like,),
    )
    buys = pd.read_sql(
        "SELECT rb.symbol, rb.qty, rb.price, rb.stop, rb.score, "
        "rb.fundamental_score, rb.fundamental_rubric, rb.rsi, rb.pct_52w_high, "
        "rb.vol_expansion, rb.reason, rb.status, rb.run_id, rr.run_time "
        "FROM rebalance_buys rb JOIN rebalance_runs rr ON rb.run_id = rr.id "
        "WHERE rr.run_time LIKE ? ORDER BY rr.run_time DESC",
        conn,
        params=(like,),
    )
    stop_updates = pd.read_sql(
        "SELECT rb.symbol, rb.qty, rb.current_stop, rb.recommended_stop, "
        "rb.gtt_trigger_id, rb.status, rb.run_id, rr.run_time "
        "FROM rebalance_stop_updates rb JOIN rebalance_runs rr ON rb.run_id = rr.id "
        "WHERE rr.run_time LIKE ? ORDER BY rr.run_time DESC",
        conn,
        params=(like,),
    )
    top_ups = pd.read_sql(
        "SELECT rb.symbol, rb.extra_qty, rb.price, rb.gtt_trigger_id, rb.status, "
        "rb.run_id, rr.run_time FROM rebalance_top_ups rb "
        "JOIN rebalance_runs rr ON rb.run_id = rr.id "
        "WHERE rr.run_time LIKE ? ORDER BY rr.run_time DESC",
        conn,
        params=(like,),
    )
    conn.close()
    return {"sells": sells, "buys": buys, "stop_updates": stop_updates, "top_ups": top_ups}


def get_last_rebalance_run() -> dict | None:
    """Same shape dashboard.py/live_rebalance.py already expect from the
    old pickle: {"run_time", "sells", "buys", "stop_updates", "open_slots"}
    (holdings isn't persisted -- callers already fetch that fresh from
    Kite, it's only ever a live snapshot, never historical)."""
    conn = get_conn()
    run = conn.execute(
        "SELECT * FROM rebalance_runs WHERE status = 'success' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if run is None:
        conn.close()
        return None
    run_id = run["id"]
    # Only 'proposed' rows -- anything already executed/errored/expired
    # shouldn't show as still needing action (see _mark_rebalance_items()
    # and save_rebalance_run()'s expiry step).
    sells = pd.read_sql(
        "SELECT symbol, qty, avg_price, reason FROM rebalance_sells "
        "WHERE run_id = ? AND status = 'proposed'",
        conn,
        params=(run_id,),
    )
    buys = pd.read_sql(
        "SELECT symbol, qty, price, stop, score, fundamental_score, "
        "fundamental_rubric, rsi, pct_52w_high, vol_expansion, reason "
        "FROM rebalance_buys WHERE run_id = ? AND status = 'proposed'",
        conn,
        params=(run_id,),
    )
    stop_updates = pd.read_sql(
        "SELECT symbol, qty, current_stop, recommended_stop, gtt_trigger_id "
        "FROM rebalance_stop_updates WHERE run_id = ? AND status = 'proposed'",
        conn,
        params=(run_id,),
    )
    top_ups = pd.read_sql(
        "SELECT symbol, extra_qty, price, gtt_trigger_id "
        "FROM rebalance_top_ups WHERE run_id = ? AND status = 'proposed'",
        conn,
        params=(run_id,),
    )
    conn.close()
    return {
        "run_id": run_id,
        "run_time": dt.datetime.fromisoformat(run["run_time"]),
        "sells": sells,
        "buys": buys,
        "stop_updates": stop_updates,
        "top_ups": top_ups,
        "open_slots": run["open_slots"],
        "target_per_slot": run["target_per_slot"],
        "cash_pool": run["cash_pool"],
        "cash_needed_for_full_equal_weight": run["cash_needed_for_full_equal_weight"],
        "cash_shortfall": run["cash_shortfall"],
        "unsettled_proceeds": run["unsettled_proceeds"],
    }


def get_rebalance_history(
    status: list[str] | None = None,
    action_type: list[str] | None = None,
    symbol: str | None = None,
    since: str | None = None,
    limit: int = 500,
) -> pd.DataFrame:
    """Every proposed sell/buy/top-up/stop-update across every rebalance
    run, normalized into one filterable table -- action_type distinguishes
    which of the 4 rebalance_* tables a row came from. qty/price/detail
    map differently per action_type (top-ups use extra_qty as qty and
    have no reason; stop-updates use qty + recommended_stop as price and
    have no reason) -- see the column comments below. status/resolved_at/
    error_message reflect the proposed/executed/error/expired lifecycle
    (see _mark_rebalance_items() and save_rebalance_run()'s expiry step).

    All filters optional and ANDed together where given; status/
    action_type accept a list (OR within the list -- e.g. status=
    ["error", "expired"] for "anything that didn't execute")."""
    conn = get_conn()
    query = """
        SELECT rb.run_id, rr.run_time, rb.status, 'sell' AS action_type,
               rb.symbol, rb.qty, rb.avg_price AS price, rb.reason AS detail,
               rb.resolved_at, rb.error_message
        FROM rebalance_sells rb JOIN rebalance_runs rr ON rb.run_id = rr.id
        UNION ALL
        SELECT rb.run_id, rr.run_time, rb.status, 'buy',
               rb.symbol, rb.qty, rb.price, rb.reason,
               rb.resolved_at, rb.error_message
        FROM rebalance_buys rb JOIN rebalance_runs rr ON rb.run_id = rr.id
        UNION ALL
        SELECT rb.run_id, rr.run_time, rb.status, 'top_up',
               rb.symbol, rb.extra_qty, rb.price, NULL,
               rb.resolved_at, rb.error_message
        FROM rebalance_top_ups rb JOIN rebalance_runs rr ON rb.run_id = rr.id
        UNION ALL
        SELECT rb.run_id, rr.run_time, rb.status, 'stop_update',
               rb.symbol, rb.qty, rb.recommended_stop, NULL,
               rb.resolved_at, rb.error_message
        FROM rebalance_stop_updates rb JOIN rebalance_runs rr ON rb.run_id = rr.id
    """
    df = pd.read_sql(query, conn)
    conn.close()

    if status:
        df = df[df["status"].isin(status)]
    if action_type:
        df = df[df["action_type"].isin(action_type)]
    if symbol:
        df = df[df["symbol"] == symbol]
    if since:
        df = df[df["run_time"] >= since]
    df = df.sort_values("run_time", ascending=False).head(limit).reset_index(drop=True)
    # One consistent "YYYY-MM-DD HH:MM:SS" format for both timestamp
    # columns -- run_time/resolved_at otherwise show as raw ISO strings
    # with fractional seconds (e.g. "2026-07-31T09:26:07.540831"), which
    # read inconsistently next to every other timestamp in this app.
    for col in ("run_time", "resolved_at"):
        df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")
    return df


def _mark_rebalance_items(
    table: str,
    run_id: int | None,
    symbols: list[str],
    status: str,
    error_message: str | None = None,
) -> None:
    """Shared implementation for every mark_rebalance_*_executed/failed()
    below -- sets status + resolved_at (and error_message, for failures)
    on matching rows INSTEAD OF deleting them, so the full history of
    what was proposed and what actually happened to it survives (the
    previous behavior physically deleted a row the moment it executed,
    losing that trail entirely). get_last_rebalance_run() only ever reads
    status='proposed' rows, so from the UI's perspective this looks
    identical to the old delete-based behavior -- executed/error/expired
    rows just stop showing as still-pending, without being destroyed.
    `table` is always one of this module's own 4 literal table name
    constants, never user input."""
    if not symbols or run_id is None:
        return
    conn = get_conn()
    now = dt.datetime.now().isoformat()
    conn.executemany(
        f"UPDATE {table} SET status = ?, resolved_at = ?, error_message = ? "
        "WHERE run_id = ? AND symbol = ?",
        [(status, now, error_message, run_id, s) for s in symbols],
    )
    conn.commit()
    conn.close()


def mark_rebalance_sells_executed(run_id: int | None, symbols: list[str]) -> None:
    _mark_rebalance_items("rebalance_sells", run_id, symbols, "executed")


def mark_rebalance_sells_failed(run_id: int | None, symbols_errors: dict[str, str]) -> None:
    for symbol, error in symbols_errors.items():
        _mark_rebalance_items("rebalance_sells", run_id, [symbol], "error", error)


def mark_rebalance_buys_executed(run_id: int | None, symbols: list[str]) -> None:
    _mark_rebalance_items("rebalance_buys", run_id, symbols, "executed")


def mark_rebalance_buys_failed(run_id: int | None, symbols_errors: dict[str, str]) -> None:
    for symbol, error in symbols_errors.items():
        _mark_rebalance_items("rebalance_buys", run_id, [symbol], "error", error)


def mark_rebalance_top_ups_executed(run_id: int | None, symbols: list[str]) -> None:
    _mark_rebalance_items("rebalance_top_ups", run_id, symbols, "executed")


def mark_rebalance_top_ups_failed(run_id: int | None, symbols_errors: dict[str, str]) -> None:
    for symbol, error in symbols_errors.items():
        _mark_rebalance_items("rebalance_top_ups", run_id, [symbol], "error", error)


def mark_rebalance_stop_updates_executed(run_id: int | None, symbols: list[str]) -> None:
    _mark_rebalance_items("rebalance_stop_updates", run_id, symbols, "executed")


def mark_rebalance_stop_updates_failed(run_id: int | None, symbols_errors: dict[str, str]) -> None:
    for symbol, error in symbols_errors.items():
        _mark_rebalance_items("rebalance_stop_updates", run_id, [symbol], "error", error)


def set_rebalance_open_slots(run_id: int | None, open_slots: int) -> None:
    """Keeps the persisted run's open_slots in sync as sells/buys actually
    execute (a sell frees a slot, a buy fills one) -- otherwise a stale
    open_slots value (computed back when the proposal was first generated)
    keeps showing after a relogin, same staleness as the buy/sell rows
    themselves."""
    if run_id is None:
        return
    conn = get_conn()
    conn.execute(
        "UPDATE rebalance_runs SET open_slots = ? WHERE id = ?", (max(int(open_slots), 0), run_id)
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Dashboard login gate -- replaces plaintext DASHBOARD_USERNAME/PASSWORD in
# .env with a salted hash stored here. The password itself is never stored,
# only PBKDF2-HMAC-SHA256(password, salt, 200_000 rounds) -- a standard,
# NIST-recommended construction available in the stdlib (hashlib), no new
# dependency needed.
# ---------------------------------------------------------------------------


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000).hex()


def ensure_dashboard_auth_seeded(default_username: str, default_password: str) -> None:
    """First-run only: seeds the singleton row from the given defaults
    (typically config.DASHBOARD_USERNAME/PASSWORD, themselves defaulting to
    the Admin/Admin placeholder) -- hashed immediately, never held in
    plaintext past this call. No-ops once a row already exists, so this is
    safe to call on every dashboard load."""
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM dashboard_auth WHERE id = 1").fetchone()
    if row is None:
        salt = secrets.token_bytes(16)
        conn.execute(
            "INSERT INTO dashboard_auth (id, username, password_hash, salt) VALUES (1, ?, ?, ?)",
            (default_username, _hash_password(default_password, salt), salt.hex()),
        )
        conn.commit()
    conn.close()


def verify_dashboard_login(username: str, password: str) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT * FROM dashboard_auth WHERE id = 1").fetchone()
    conn.close()
    if row is None:
        return False
    salt = bytes.fromhex(row["salt"])
    return username == row["username"] and _hash_password(password, salt) == row["password_hash"]


def update_dashboard_password(username: str, new_password: str) -> None:
    """Overwrites the singleton row -- used by the dashboard's own
    change-password form, so a password can be changed without touching
    .env or restarting the process. Also revokes every outstanding
    'remember me' token -- a changed password should invalidate any
    session remembered under the old one, not leave it silently valid
    until its own expiry."""
    conn = get_conn()
    salt = secrets.token_bytes(16)
    conn.execute(
        "UPDATE dashboard_auth SET username = ?, password_hash = ?, salt = ? WHERE id = 1",
        (username, _hash_password(new_password, salt), salt.hex()),
    )
    conn.execute("DELETE FROM remember_tokens")
    conn.commit()
    conn.close()


def is_using_default_dashboard_password(default_username: str, default_password: str) -> bool:
    """For the loud on-screen warning -- true only while still on the
    seeded Admin/Admin-style default, false the moment it's ever changed."""
    return verify_dashboard_login(default_username, default_password)


# ---------------------------------------------------------------------------
# "Remember me" -- an opt-in browser cookie that survives a service restart
# or reconnect (Streamlit's own session_state does not -- see dashboard.py's
# login gate) so a same-day reconnect doesn't require re-entering the
# password. Deliberately expires at the next 6 AM rather than after a fixed
# duration -- lines up with Kite's own daily ~6 AM access-token expiry, so
# "log in once, stay in for the rest of today, sign in fresh again
# tomorrow morning" holds for both systems together instead of two
# different, confusing cutoffs.
# ---------------------------------------------------------------------------


def _next_daily_cutoff(now: dt.datetime | None = None) -> dt.datetime:
    now = now or dt.datetime.now()
    cutoff = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if now >= cutoff:
        cutoff += dt.timedelta(days=1)
    return cutoff


def create_remember_token(username: str) -> tuple[str, int]:
    """Issues a fresh remember-me token for `username`, valid until the
    next 6 AM. Returns (raw_token, max_age_seconds) -- the raw token is
    handed to the browser as a cookie value and never itself stored; only
    its SHA-256 hash lives in the DB (see module note above)."""
    conn = get_conn()
    conn.execute(
        "DELETE FROM remember_tokens WHERE expires_at < ?", (dt.datetime.now().isoformat(),)
    )
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = _next_daily_cutoff()
    conn.execute(
        "INSERT INTO remember_tokens (username, token_hash, created_at, expires_at) "
        "VALUES (?, ?, ?, ?)",
        (username, token_hash, dt.datetime.now().isoformat(), expires_at.isoformat()),
    )
    conn.commit()
    conn.close()
    max_age = max(1, int((expires_at - dt.datetime.now()).total_seconds()))
    return token, max_age


def verify_remember_token(token: str) -> str | None:
    """Returns the matching username if `token` is a valid, unexpired
    remember-me cookie value; None if it's missing, expired, or doesn't
    match anything on record (tampered/stale)."""
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    conn = get_conn()
    row = conn.execute(
        "SELECT username, expires_at FROM remember_tokens WHERE token_hash = ?", (token_hash,)
    ).fetchone()
    conn.close()
    if row is None or dt.datetime.fromisoformat(row["expires_at"]) < dt.datetime.now():
        return None
    return row["username"]


def delete_remember_token(token: str) -> None:
    """Revokes one specific device's remember-me cookie -- used on explicit
    log-out, so signing out actually ends that browser's remembered
    session instead of just clearing session_state until the next
    reconnect silently signs it back in."""
    if not token:
        return
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    conn = get_conn()
    conn.execute("DELETE FROM remember_tokens WHERE token_hash = ?", (token_hash,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Strategy configuration -- config.STRATEGY, editable from the Admin page
# instead of only via a code edit + restart.
# ---------------------------------------------------------------------------


def get_strategy_config(defaults: dict) -> dict:
    """Returns the live strategy config, DB values taking precedence over
    `defaults` key by key. Self-healing like every other table here: any
    key in `defaults` missing from the DB (first run, or a new parameter
    added to config.py after the DB already existed) gets seeded from
    `defaults` and returned as-is -- so adding a new STRATEGY key later
    doesn't require a manual migration, only a code change to config.py."""
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM strategy_config").fetchall()
    stored = {r["key"]: json.loads(r["value"]) for r in rows}
    missing = {k: v for k, v in defaults.items() if k not in stored}
    if missing:
        conn.executemany(
            "INSERT INTO strategy_config (key, value) VALUES (?, ?)",
            [(k, json.dumps(v)) for k, v in missing.items()],
        )
        conn.commit()
    conn.close()
    return {**defaults, **stored, **missing}


def update_strategy_config(updates: dict) -> None:
    """Upserts the given {key: value} pairs -- used by the Admin page's
    strategy settings form. Only ever called with keys that already exist
    (from a form pre-filled by get_strategy_config), but INSERT OR REPLACE
    handles a brand-new key just as well."""
    conn = get_conn()
    conn.executemany(
        "INSERT OR REPLACE INTO strategy_config (key, value) VALUES (?, ?)",
        [(k, json.dumps(v)) for k, v in updates.items()],
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Manually skipped symbols -- editable from Admin -- "Skip stocks from
# scanner". See config.refresh_universe(), which reads get_skipped_symbols()
# to exclude these from config.UNIVERSE (the Screener/Live Rebalance/
# backtest.py's shared candidate universe).
# ---------------------------------------------------------------------------


def add_skipped_symbol(symbol: str, reason: str = "") -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO skipped_symbols (symbol, reason) VALUES (?, ?) "
        "ON CONFLICT(symbol) DO UPDATE SET reason = excluded.reason",
        (symbol, reason),
    )
    conn.commit()
    conn.close()


def remove_skipped_symbol(symbol: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM skipped_symbols WHERE symbol = ?", (symbol,))
    conn.commit()
    conn.close()


def get_skipped_symbols() -> list[str]:
    conn = get_conn()
    rows = conn.execute("SELECT symbol FROM skipped_symbols ORDER BY symbol").fetchall()
    conn.close()
    return [r["symbol"] for r in rows]


def get_skipped_symbols_df() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query(
        "SELECT symbol, reason, added_at FROM skipped_symbols ORDER BY symbol", conn
    )
    conn.close()
    return df


# ---------------------------------------------------------------------------
# Kite Connect credentials -- replaces KITE_API_KEY/KITE_API_SECRET/
# KITE_ACCESS_TOKEN in .env. api_key/api_secret stay plaintext (must be
# recoverable, unlike a password); access_token is genuinely a better fit
# here than .env ever was, since it's frequently-changing live state
# (expires roughly daily), the same category as everything else in this
# file.
# ---------------------------------------------------------------------------


def ensure_kite_credentials_seeded(api_key: str, api_secret: str, access_token: str = "") -> None:
    """First-run only: seeds from whatever's currently in .env (config.py's
    fallback values). No-ops once a row exists, so this never clobbers a
    token/key that's since been updated through the DB directly."""
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM kite_credentials WHERE id = 1").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO kite_credentials (id, api_key, api_secret, "
            "access_token, access_token_updated_at) VALUES (1, ?, ?, ?, ?)",
            (
                api_key,
                api_secret,
                access_token,
                dt.datetime.now().isoformat() if access_token else None,
            ),
        )
        conn.commit()
    conn.close()


def get_kite_credentials() -> dict:
    """Returns {"api_key", "api_secret", "access_token", ...} or all-empty
    if nothing has been seeded yet (fresh install, no .env values either)."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM kite_credentials WHERE id = 1").fetchone()
    conn.close()
    if row is None:
        return {
            "api_key": "",
            "api_secret": "",
            "access_token": "",
            "access_token_updated_at": None,
        }
    return dict(row)


def save_kite_access_token(token: str) -> None:
    """Called after a successful OAuth exchange -- see
    kite_client.exchange_request_token(). Only updates the token, leaves
    api_key/api_secret untouched."""
    conn = get_conn()
    conn.execute(
        "UPDATE kite_credentials SET access_token = ?, access_token_updated_at = ? WHERE id = 1",
        (token, dt.datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def update_kite_api_credentials(api_key: str, api_secret: str) -> None:
    """Used by the dashboard's Kite API settings form, for whenever the
    user regenerates keys in the Kite developer console."""
    conn = get_conn()
    conn.execute(
        "UPDATE kite_credentials SET api_key = ?, api_secret = ? WHERE id = 1",
        (api_key, api_secret),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Job execution log -- unified history for every scheduled/background job
# (rebalance scan, gap-down check, fundamentals refresh, and the
# dashboard's manual "Run screen"/"Run today's scan" buttons). Wrap a job's
# body in the job_run() context manager below rather than calling
# start_job_run/finish_job_run directly.
# ---------------------------------------------------------------------------


def start_job_run(job_type: str, trigger_type: str) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO job_runs (job_type, trigger_type, started_at, status) "
        "VALUES (?, ?, ?, 'running')",
        (job_type, trigger_type, dt.datetime.now().isoformat()),
    )
    run_id = cur.lastrowid
    conn.commit()
    conn.close()
    return run_id


def finish_job_run(
    run_id: int, status: str, summary: str | None = None, error: str | None = None
) -> None:
    conn = get_conn()
    row = conn.execute("SELECT started_at FROM job_runs WHERE id = ?", (run_id,)).fetchone()
    started = dt.datetime.fromisoformat(row["started_at"])
    finished = dt.datetime.now()
    conn.execute(
        "UPDATE job_runs SET finished_at = ?, duration_sec = ?, status = ?, "
        "summary = ?, error_message = ? WHERE id = ?",
        (
            finished.isoformat(),
            (finished - started).total_seconds(),
            status,
            summary,
            error,
            run_id,
        ),
    )
    conn.commit()
    conn.close()


@contextlib.contextmanager
def job_run(job_type: str, trigger_type: str):
    """Wrap a job's entire body in this. Records a 'running' row
    immediately, then 'success' or 'failed' (with the full traceback) when
    the block exits -- and always re-raises on failure, so a systemd unit
    still exits non-zero / a caller still sees the exception; this only
    ADDS a persisted record, it never swallows an error.

    Yields a plain dict -- set result["summary"] inside the `with` block to
    whatever one-line, job-type-specific text should show in the Job Log
    (e.g. "3 buys, 1 sell, 2 stop updates"); it's read only after the block
    finishes successfully.

    Usage:
        with state_db.job_run("rebalance_scan", "scheduled") as result:
            outcome = propose_rebalance(...)
            result["summary"] = f"{len(outcome['buys'])} buys, ..."
    """
    run_id = start_job_run(job_type, trigger_type)
    result: dict = {"summary": None}
    try:
        yield result
    except TokenException:
        finish_job_run(run_id, "failed", error=traceback.format_exc())
        # Safety net alongside check_kite_token.py's proactive ~07:00
        # check -- covers a token that expires/gets revoked mid-day for
        # any other reason, or the proactive check itself not having run.
        title = "KK Trading -- Kite login needed"
        message = f"{job_type} failed: Kite session expired. Log in to resume automated runs."
        for dead in notify.send_webpush_all(
            get_push_subscriptions(), title, message, notify.DASHBOARD_URL
        ):
            delete_push_subscription(dead)
        raise
    except Exception:
        finish_job_run(run_id, "failed", error=traceback.format_exc())
        raise
    else:
        finish_job_run(run_id, "success", summary=result.get("summary"))
        # Only the unattended scheduled run gets a completion push -- a
        # manual "Run today's scan" click means you're already watching
        # the screen, so a push for that would just be noise.
        if job_type == "rebalance_scan" and trigger_type == "scheduled":
            title = "KK Trading -- rebalance complete"
            message = result.get("summary") or "Rebalance scan finished."
            for dead in notify.send_webpush_all(
                get_push_subscriptions(), title, message, notify.DASHBOARD_URL
            ):
                delete_push_subscription(dead)


def cleanup_stale_manual_jobs() -> int:
    """Marks any job_runs row still 'running' with trigger_type='manual'
    as 'failed' (interrupted). Meant to be called exactly ONCE per
    process, at dashboard startup (see background_jobs.py) -- NOT from
    inside job_run() or on every get_conn() call, which would wrongly
    kill a job genuinely still running in this same process.

    Scoped to trigger_type='manual' ONLY, and deliberately not a general
    "any running row is stale" cleanup: 'manual' jobs only ever run as a
    background thread inside THIS dashboard process (background_jobs.py),
    so a 'manual' row still 'running' when the dashboard is just starting
    up can only be orphaned from a PREVIOUS instance of this same process
    -- e.g. the systemd service restarting (a code deploy) while a manual
    "Run screen"/"Run today's scan" thread was still executing, killing
    the whole process mid-job with no chance for job_run()'s own except/
    else to ever run. Real example: a screen_run row stuck at 'running'
    since a deploy-time restart, never auto-clearing. 'scheduled' rows are
    NOT touched here -- those come from independent, short-lived CLI
    processes (live_rebalance.py, fundamentals_agent.py) that can be
    running concurrently with this dashboard process, so blindly marking
    every 'running' row stale here could kill a genuinely-still-running
    scheduled job in another process."""
    conn = get_conn()
    cur = conn.execute(
        "UPDATE job_runs SET status = 'failed', finished_at = ?, "
        "error_message = 'Interrupted -- process restarted while this job "
        "was running (e.g. a code deploy), so it never reached its own "
        "completion handler' WHERE status = 'running' AND trigger_type = 'manual'",
        (dt.datetime.now().isoformat(),),
    )
    n = cur.rowcount
    conn.commit()
    conn.close()
    return n


def get_job_runs(
    job_type: str | None = None,
    status: str | None = None,
    since: str | None = None,
    limit: int = 200,
) -> pd.DataFrame:
    """since: an ISO date/datetime string, inclusive lower bound on
    started_at. All filters optional -- omit to get the unfiltered history
    (most recent `limit` rows)."""
    conn = get_conn()
    where, params = [], []
    if job_type:
        where.append("job_type = ?")
        params.append(job_type)
    if status:
        where.append("status = ?")
        params.append(status)
    if since:
        where.append("started_at >= ?")
        params.append(since)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    df = pd.read_sql(
        f"SELECT * FROM job_runs {clause} ORDER BY id DESC LIMIT ?", conn, params=params + [limit]
    )
    conn.close()
    return df


def prune_job_runs(days: int = 30) -> int:
    """Deletes job_runs rows older than `days` days (by started_at), so the
    table doesn't grow unbounded over the life of the deployment. Meant to
    be called once daily -- see live_rebalance.main_exit_price_correction()."""
    conn = get_conn()
    cutoff = (dt.datetime.now() - dt.timedelta(days=days)).isoformat()
    cur = conn.execute("DELETE FROM job_runs WHERE started_at < ?", (cutoff,))
    n = cur.rowcount
    conn.commit()
    conn.close()
    return n


def get_last_job_run(job_type: str) -> dict | None:
    """For the Job Log page's quick-glance strip -- last run of one job
    type, whatever its status."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM job_runs WHERE job_type = ? ORDER BY id DESC LIMIT 1", (job_type,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Tradebook -- append-only analytics ledger, separate from `positions`
# (which stays focused on live trailing-stop bookkeeping). One row per
# trade, capturing an entry-time technical/fundamental snapshot and a real
# exit reason -- neither existed anywhere before this.
# ---------------------------------------------------------------------------


def record_trade_entry(
    symbol: str,
    entry_price: float,
    qty: int,
    stop: float,
    snapshot: dict,
    position_id: int | None = None,
    entry_date: str | None = None,
) -> int:
    """snapshot: whatever entry-time context is available, keyed by the
    trades columns it maps to -- score/rsi/pct_52w_high/vol_expansion/
    fundamental_score/entry_reason. Missing keys are left null rather than
    required, since not every caller (e.g. a manual position add) has a
    full screener row to draw from.

    snapshot["entry_reason"]: a human-readable one-liner built by the
    caller from the same numbers (e.g. "Ranked #2 of 9 momentum candidates
    (score 2.39); RSI 58, 92% of 52w high; fundamental score 87/100") --
    see live_rebalance.py's propose_rebalance() buy loop for how it's
    constructed. Left null if the caller doesn't have enough context
    (manual/backfilled positions) rather than fabricated.

    entry_date: defaults to today (the normal case, called right after a
    live buy) -- pass an explicit ISO date to backfill a trade that
    happened before this table existed (e.g. from positions.entry_date +
    rebalance_buys' recorded score for that day)."""
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO trades (position_id, symbol, entry_date, entry_price, "
        "qty, initial_stop, entry_score, entry_rsi, entry_pct_52w_high, "
        "entry_vol_expansion, entry_fundamental_score, entry_reason, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')",
        (
            position_id,
            symbol,
            entry_date or dt.date.today().isoformat(),
            entry_price,
            qty,
            stop,
            snapshot.get("score"),
            snapshot.get("rsi"),
            snapshot.get("pct_52w_high"),
            snapshot.get("vol_expansion"),
            snapshot.get("fundamental_score"),
            snapshot.get("entry_reason"),
        ),
    )
    trade_id = cur.lastrowid
    conn.commit()
    conn.close()
    return trade_id


def close_trade(symbol: str, exit_price: float | None, exit_reason: str) -> None:
    """Closes the most recent OPEN trades row for this symbol. exit_price
    may be None (price genuinely unavailable) -- realized_pnl/
    realized_ret_pct are then left null, same NULL-tolerant convention
    positions.realized_pnl already uses. No-ops (does nothing) if there's
    no open trade for this symbol -- callers that aren't sure one exists
    (e.g. reconciled_positions' fallback path) can call this unconditionally.

    Also auto-logs the DP (Depository Participant) charge for this sale as
    a cash_flows entry, per config.STRATEGY["dp_charge_per_scrip"] (0 ->
    no-op) -- this is the single chokepoint every real exit path goes
    through (rebalance sell, gap-down stop, manual square-off, GTT-fill
    reconciliation), so hooking it here is the only way to guarantee it's
    never missed the way a manually-remembered ledger entry can be.
    Deferred import: config.py imports state_db at module level, so a
    top-level `import config` here would be circular; both are fully
    loaded by the time any caller actually reaches this function."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM trades WHERE symbol = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    if row is None:
        conn.close()
        return
    today = dt.date.today().isoformat()
    holding_days = (dt.date.today() - dt.date.fromisoformat(row["entry_date"])).days
    realized_pnl = None
    realized_ret_pct = None
    if exit_price is not None:
        realized_pnl = (exit_price - row["entry_price"]) * row["qty"]
        realized_ret_pct = (exit_price / row["entry_price"] - 1) * 100
    conn.execute(
        "UPDATE trades SET status = 'closed', exit_date = ?, exit_price = ?, "
        "exit_reason = ?, realized_pnl = ?, realized_ret_pct = ?, "
        "holding_days = ? WHERE id = ?",
        (today, exit_price, exit_reason, realized_pnl, realized_ret_pct, holding_days, row["id"]),
    )
    conn.commit()
    conn.close()

    import config

    dp_charge = config.STRATEGY.get("dp_charge_per_scrip", 0.0)
    if dp_charge > 0:
        record_cash_flow(today, -dp_charge, f"DP charge -- {symbol} sold")


def correct_trade_exit_price(symbol: str, exit_date: str, real_exit_price: float) -> int:
    """Overwrites exit_price (and recomputed realized_pnl/realized_ret_pct)
    on every trades row that closed for this symbol on this date -- see
    live_rebalance.correct_todays_exit_prices(). close_trade() (and
    reconciled_positions()) can only ever record an LTP-at-detection-time
    APPROXIMATION as exit_price, since Kite's order-placement response
    never includes the real fill price -- this replaces it with the real
    average fill price once Kite's own end-of-day order book has it.
    Also corrects the matching positions row(s) so the two stay in sync
    (positions.realized_pnl mirrors trades.realized_pnl, same convention
    reconciled_positions() already keeps). Returns how many trades rows
    were updated (0 if none matched -- e.g. this symbol's close wasn't
    today, or was already reconciled by a different day's run)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, entry_price, qty FROM trades WHERE symbol = ? "
        "AND exit_date = ? AND status = 'closed'",
        (symbol, exit_date),
    ).fetchall()
    for row in rows:
        realized_pnl = (real_exit_price - row["entry_price"]) * row["qty"]
        realized_ret_pct = (real_exit_price / row["entry_price"] - 1) * 100
        conn.execute(
            "UPDATE trades SET exit_price = ?, realized_pnl = ?, realized_ret_pct = ? WHERE id = ?",
            (real_exit_price, realized_pnl, realized_ret_pct, row["id"]),
        )
    conn.execute(
        "UPDATE positions SET exit_price = ?, "
        "realized_pnl = (? - entry_price) * qty "
        "WHERE symbol = ? AND closed_date = ? AND status = 'closed'",
        (real_exit_price, real_exit_price, symbol, exit_date),
    )
    conn.commit()
    conn.close()
    return len(rows)


def get_trades(
    symbol: str | None = None, status: str | None = None, since: str | None = None
) -> pd.DataFrame:
    """Also carries the position's latest known stop as
    latest_recommended_stop -- COALESCE(p.recommended_stop, p.current_stop):
    p.recommended_stop is the trailing-stop value compute_stop_updates()
    recalculates once per day, as part of whenever the rebalance scan next
    runs (scheduled time has moved before -- see nse-rebalance.timer -- so
    deliberately not hardcoded here), using that day's ATR, NOT yet
    necessarily pushed to the real broker GTT (see apply_stop_update()).
    For a position bought since the last scan ran, that's still NULL, so
    this falls back to p.current_stop -- the actual applied/initial GTT
    stop -- rather than showing blank (which read as missing/broken data
    for a freshly-bought position, when really there's just nothing to
    ratchet yet). Null only for a closed trade, or a trade whose position
    was never linked (shouldn't happen for anything recorded through this
    app's own flows)."""
    conn = get_conn()
    where, params = [], []
    if symbol:
        where.append("t.symbol = ?")
        params.append(symbol)
    if status:
        where.append("t.status = ?")
        params.append(status)
    if since:
        where.append("t.entry_date >= ?")
        params.append(since)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    df = pd.read_sql(
        f"SELECT t.*, COALESCE(p.recommended_stop, p.current_stop) AS latest_recommended_stop "
        f"FROM trades t LEFT JOIN positions p ON t.position_id = p.id "
        f"{clause} ORDER BY t.entry_date DESC, t.id DESC",
        conn,
        params=params,
    )
    conn.close()
    return df


# ---------------------------------------------------------------------------
# Browser push notification subscriptions (see notify.py, push_server.py)
# ---------------------------------------------------------------------------


def save_push_subscription(endpoint: str, p256dh: str, auth: str) -> None:
    """Upsert -- re-subscribing the same device (endpoint) just refreshes
    its keys rather than erroring on the PRIMARY KEY."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO push_subscriptions (endpoint, p256dh, auth) VALUES (?, ?, ?) "
        "ON CONFLICT(endpoint) DO UPDATE SET p256dh = excluded.p256dh, auth = excluded.auth",
        (endpoint, p256dh, auth),
    )
    conn.commit()
    conn.close()


def delete_push_subscription(endpoint: str) -> None:
    """Called both for an explicit unsubscribe and for cleaning up a
    subscription notify.send_webpush_all() found dead (410 Gone/404 from
    the browser vendor's push service -- e.g. the device was uninstalled
    or notifications were revoked outside this app)."""
    conn = get_conn()
    conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
    conn.commit()
    conn.close()


def get_push_subscriptions() -> list[dict]:
    """All currently-registered devices, in the shape pywebpush's
    subscription_info expects -- {"endpoint": ..., "keys": {"p256dh":
    ..., "auth": ...}}."""
    conn = get_conn()
    rows = conn.execute("SELECT endpoint, p256dh, auth FROM push_subscriptions").fetchall()
    conn.close()
    return [
        {"endpoint": r["endpoint"], "keys": {"p256dh": r["p256dh"], "auth": r["auth"]}}
        for r in rows
    ]


def get_entry_confirm_streaks() -> dict[str, int]:
    """{symbol: streak} for every symbol with any recorded streak (0 or
    more -- a 0 row means it was in the confirm-pool at some point but
    isn't right now, kept rather than deleted so its history doesn't
    silently vanish). live_rebalance.py filters new-buy eligibility on
    `streak >= entry_confirm_days`, exactly matching backtest.py's own
    `candidate_streak.get(sym, 0) >= confirm_days` check."""
    conn = get_conn()
    rows = conn.execute("SELECT symbol, streak FROM entry_confirm_streak").fetchall()
    conn.close()
    return {r["symbol"]: r["streak"] for r in rows}


def update_entry_confirm_streaks(confirm_syms_now: set[str], today: str) -> bool:
    """Once-per-day batch update, mirroring backtest.py's own logic
    (backtest.py:1009-1020) exactly: every symbol NOT in confirm_syms_now
    this time resets to 0 (not deleted); every symbol IN it increments by
    1 (starting from 0 if never seen before). Idempotent per calendar
    day -- if EVERY existing row already has last_confirmed_date ==
    today, this is a no-op (returns False) rather than double-
    incrementing everyone, protecting against a double-fire (e.g.
    clicking "Run today's scan" twice, or both the scheduled job and a
    manual click landing the same day). Only meaningful once at least
    one row exists; the very first call of all always proceeds (nothing
    to have already been updated today). Returns True if it actually
    updated, False if it was a no-op."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT symbol, streak, last_confirmed_date FROM entry_confirm_streak"
    ).fetchall()
    if rows and all(r["last_confirmed_date"] == today for r in rows):
        conn.close()
        return False
    existing = {r["symbol"]: r["streak"] for r in rows}
    updates = []
    for sym in existing:
        if sym not in confirm_syms_now:
            updates.append((sym, 0, today))
    for sym in confirm_syms_now:
        updates.append((sym, existing.get(sym, 0) + 1, today))
    conn.executemany(
        "INSERT INTO entry_confirm_streak (symbol, streak, last_confirmed_date) "
        "VALUES (?, ?, ?) ON CONFLICT(symbol) DO UPDATE SET "
        "streak = excluded.streak, last_confirmed_date = excluded.last_confirmed_date",
        updates,
    )
    conn.commit()
    conn.close()
    return True
