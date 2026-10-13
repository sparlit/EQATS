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
SQLite-backed storage for the intraday "DaysLowVolumnBreakout" strategy
-- kept in its own file (cache/intraday_state.db), separate from
state_db.py's cache/state.db (or cache/users/<id>/state.db). This
strategy's shape (MIS, half-position exits, day-bounded, paper/live
mode split) is structurally distinct from the momentum strategy's CNC
swing positions -- no shared tables, so a schema change here can never
touch the momentum strategy's data and vice versa.

Same conventions as state_db.py: a fresh connection per call (never a
held-open connection across calls), idempotent schema creation on every
get_conn(), and DB_PATH as a plain reassignable module global so tests
can point it at a throwaway file (see verify_intraday_db.py).
"""


import os
import sqlite3
import time

import pandas as pd

DB_PATH = os.path.join("cache", "intraday_state.db")

_SCHEMA = """
-- One row per trading day the engine actually ran the day-bias check,
-- regardless of outcome -- day_bias is NULL when the day was SKIPPED
-- (ratio didn't clear either threshold, Spec.md §2.2), so "was today
-- skipped, what was the ratio" is a single-row lookup, not an absence.
CREATE TABLE IF NOT EXISTS intraday_days (
    date TEXT PRIMARY KEY,
    nifty_ratio REAL,
    day_bias TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- The day's selected candidates (Spec.md §2.4) -- only rows for days
-- that actually had a day_bias (no rows at all for a skipped day).
CREATE TABLE IF NOT EXISTS intraday_daily_selection (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL REFERENCES intraday_days(date),
    rank INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    ret_first15_pct REAL NOT NULL,
    UNIQUE(date, symbol)
);

-- Signal-candle state (Spec.md §3) -- lets the Dashboard show "signal
-- formed at HH:MM, watching for breakout" before any position exists.
CREATE TABLE IF NOT EXISTS intraday_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    signal_time TEXT NOT NULL,
    signal_high REAL NOT NULL,
    signal_low REAL NOT NULL,
    signal_atr REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One row per triggered entry (Spec.md §4) -- qty_remaining tracks the
-- half-position split (§5) as legs close; status flips to 'closed' once
-- qty_remaining reaches 0.
CREATE TABLE IF NOT EXISTS intraday_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    signal_time TEXT,
    entry_time TEXT NOT NULL,
    entry_price REAL NOT NULL,
    stop_price REAL NOT NULL,
    target_price REAL NOT NULL,
    qty INTEGER NOT NULL,
    qty_remaining INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    mode TEXT NOT NULL,
    order_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One row per exit leg (Spec.md §5) -- up to 2 per position (target
-- half + runner half), each carrying its own cost/P&L (costs.py's
-- round-trip model is computed per leg, not once for the whole
-- position, since each leg has its own qty/exit_price).
CREATE TABLE IF NOT EXISTS intraday_legs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL REFERENCES intraday_positions(id),
    leg_type TEXT NOT NULL,
    qty INTEGER NOT NULL,
    exit_price REAL NOT NULL,
    exit_time TEXT NOT NULL,
    gross_pnl REAL NOT NULL,
    costs REAL NOT NULL,
    net_pnl REAL NOT NULL,
    order_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Day-to-day compounding capital (Spec.md §7), tracked SEPARATELY per
-- mode -- switching to live must never inherit paper mode's simulated
-- P&L, and paper mode should keep compounding independently even after
-- live trading starts (so paper stays a meaningful ongoing dry run,
-- not frozen the moment live begins).
CREATE TABLE IF NOT EXISTS intraday_capital_state (
    mode TEXT PRIMARY KEY,
    starting_capital REAL NOT NULL,
    current_capital REAL NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def get_conn(db_path: str | None = None) -> sqlite3.Connection:
    db_path = db_path or DB_PATH
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    # timeout=30 + WAL: this file is hit concurrently from genuinely
    # separate OS processes (the live/paper intraday_engine.py process
    # AND the dashboard's own Streamlit process), not just separate
    # threads -- the same "database is locked" risk state_db.get_conn()
    # had (fresh connection + full schema/migration cost on every call,
    # sqlite3's 5s default timeout) applies here too, if anything with
    # more exposure given the cross-process access. The retry loop
    # absorbs the brief race switching INTO WAL mode for the very first
    # connection ever (skipped on every later one, once a connection
    # reports it's already in WAL) and the same-class race in the
    # migration function's own check-then-ALTER pattern.
    last_err = None
    for attempt in range(8):
        try:
            conn = sqlite3.connect(db_path, timeout=30)
            if conn.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
                conn.execute("PRAGMA journal_mode=WAL")
            conn.row_factory = sqlite3.Row
            conn.executescript(_SCHEMA)
            conn.commit()
            _migrate_daily_selection_schema(conn)
            return conn
        except sqlite3.OperationalError as e:
            last_err = e
            if "locked" not in str(e).lower() and "duplicate column" not in str(e).lower():
                raise
            time.sleep(0.1 * (attempt + 1))
    raise last_err


def _migrate_daily_selection_schema(conn: sqlite3.Connection) -> None:
    """Adds per-candidate day-state tracking to intraday_daily_selection,
    independent of intraday_signals -- a candidate invalidated (EMA21
    gate) BEFORE ever forming a signal candle (e.g. HEROMOTOCO on
    2026-09-16, invalidated on its very first eligible candle) has no
    intraday_signals row at all to update, so without this the Dashboard
    has no way to distinguish "still watching" from "permanently done
    for the day" -- it silently showed the same generic 'No signal yet'
    badge for both."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(intraday_daily_selection)")}
    if "status" not in cols:
        conn.execute(
            "ALTER TABLE intraday_daily_selection ADD COLUMN status TEXT NOT NULL DEFAULT 'watching'"
        )
    if "status_updated_at" not in cols:
        conn.execute("ALTER TABLE intraday_daily_selection ADD COLUMN status_updated_at TEXT")
    # v2 Spec §6 -- entry-time sector-confirmation gate, resolved once at
    # 09:30 per candidate (sector name, that sector's own first-15m A/D
    # ratio, and whether it cleared the strict 2.0/0.5 threshold).
    if "sector" not in cols:
        conn.execute("ALTER TABLE intraday_daily_selection ADD COLUMN sector TEXT")
    if "sector_ratio" not in cols:
        conn.execute("ALTER TABLE intraday_daily_selection ADD COLUMN sector_ratio REAL")
    if "sector_gate_pass" not in cols:
        conn.execute("ALTER TABLE intraday_daily_selection ADD COLUMN sector_gate_pass INTEGER")
    conn.commit()

    # The raw advancer/decliner counts behind intraday_days.nifty_ratio --
    # previously only the ratio itself was kept, so the Dashboard had
    # nothing to show side by side with NSE's own live A/D widget (which
    # displays counts, e.g. "36 / 14") for a direct visual diff -- a
    # bare "1.94" next to "36 / 14" isn't comparable at a glance.
    day_cols = {r["name"] for r in conn.execute("PRAGMA table_info(intraday_days)")}
    if "advancers" not in day_cols:
        conn.execute("ALTER TABLE intraday_days ADD COLUMN advancers INTEGER")
    if "decliners" not in day_cols:
        conn.execute("ALTER TABLE intraday_days ADD COLUMN decliners INTEGER")
    conn.commit()

    # v5.2 EMA-trail exit: once price first touches the 1:2R target, the
    # first-half booking is DEFERRED and trailed against EMA5/EMA10
    # instead. target_touch_time (NULL = target not yet touched) and
    # trail_ema (5 or 10) are persisted so the exit state survives in the
    # DB, is visible to the Dashboard, and doesn't live only in the
    # engine process's memory.
    pos_cols = {r["name"] for r in conn.execute("PRAGMA table_info(intraday_positions)")}
    if "target_touch_time" not in pos_cols:
        conn.execute("ALTER TABLE intraday_positions ADD COLUMN target_touch_time TEXT")
    if "trail_ema" not in pos_cols:
        conn.execute("ALTER TABLE intraday_positions ADD COLUMN trail_ema INTEGER")
    conn.commit()

    # v5.4 -- overnight-gap filter (checked once, pre-market, before a
    # candidate is even ranked into the day's top-N pool). Persisted for
    # every SELECTED candidate (they've all already passed the filter,
    # by construction) purely for Dashboard visibility -- candidates
    # that got discarded for gapping too far are logged, not stored,
    # since intraday_daily_selection only ever holds the day's actual
    # picks (rank 1..N), same as before this column existed.
    if "gap_pct" not in cols:
        conn.execute("ALTER TABLE intraday_daily_selection ADD COLUMN gap_pct REAL")
    conn.commit()


# ---------------------------------------------------------------------------
# Days / daily selection -- Spec.md §2
# ---------------------------------------------------------------------------


def record_day(
    date: str,
    nifty_ratio: float,
    day_bias: str | None,
    advancers: int | None = None,
    decliners: int | None = None,
) -> None:
    """One call per trading day the engine runs the 09:30 check --
    day_bias=None records a SKIPPED day (ratio didn't clear either
    threshold), not an error. advancers/decliners are the raw NIFTY50
    counts nifty_ratio was computed from -- kept alongside it so the
    Dashboard can show them next to NSE's own live A/D widget for a
    direct, same-format comparison."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO intraday_days (date, nifty_ratio, day_bias, advancers, decliners) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(date) DO UPDATE SET nifty_ratio = excluded.nifty_ratio, "
        "day_bias = excluded.day_bias, advancers = excluded.advancers, decliners = excluded.decliners",
        (date, nifty_ratio, day_bias, advancers, decliners),
    )
    conn.commit()
    conn.close()


def get_day(date: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM intraday_days WHERE date = ?", (date,)).fetchone()
    conn.close()
    return dict(row) if row else None


def record_candidates(date: str, candidates: list[dict]) -> None:
    """candidates: [{"rank", "symbol", "ret_first15_pct", "gap_pct"(optional)}, ...]
    -- call once after record_day() when day_bias is not None."""
    conn = get_conn()
    conn.executemany(
        "INSERT INTO intraday_daily_selection (date, rank, symbol, ret_first15_pct, gap_pct) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(date, symbol) DO UPDATE SET "
        "rank = excluded.rank, ret_first15_pct = excluded.ret_first15_pct, "
        "gap_pct = excluded.gap_pct",
        [
            (date, c["rank"], c["symbol"], c["ret_first15_pct"], c.get("gap_pct"))
            for c in candidates
        ],
    )
    conn.commit()
    conn.close()


def get_candidates(date: str) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql(
        "SELECT rank, symbol, ret_first15_pct, gap_pct, status, sector, sector_ratio, "
        "sector_gate_pass FROM intraday_daily_selection WHERE date = ? ORDER BY rank",
        conn,
        params=(date,),
    )
    conn.close()
    if not df.empty:
        df["sector_gate_pass"] = df["sector_gate_pass"].astype("boolean")
    return df


def mark_candidate_status(date: str, symbol: str, status: str) -> None:
    """status: 'watching' (default) | 'invalidated' | 'sector_gate_failed'
    | 'traded'. Called the moment a candidate's day is decided one way or
    the other, so the Dashboard can show a definitive state instead of
    inferring it from intraday_signals (which has no row at all for a
    candidate invalidated before ever forming a signal candle)."""
    conn = get_conn()
    conn.execute(
        "UPDATE intraday_daily_selection SET status = ?, status_updated_at = datetime('now') "
        "WHERE date = ? AND symbol = ?",
        (status, date, symbol),
    )
    conn.commit()
    conn.close()


def update_candidate_sector_gate(
    date: str, symbol: str, sector: str | None, sector_ratio: float | None, gate_pass: bool
) -> None:
    """Spec v2 §6 -- persists a candidate's resolved primary sector, that
    sector's own first-15m A/D ratio, and whether it cleared the strict
    2.0/0.5 gate. Called once at 09:30 (resolve_sector_gates()), looked
    up (not recomputed) later if/when that candidate's breakout triggers."""
    conn = get_conn()
    conn.execute(
        "UPDATE intraday_daily_selection SET sector = ?, sector_ratio = ?, "
        "sector_gate_pass = ? WHERE date = ? AND symbol = ?",
        (sector, sector_ratio, int(gate_pass), date, symbol),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Signals -- Spec.md §3
# ---------------------------------------------------------------------------


def create_signal(
    date: str,
    symbol: str,
    signal_time: str,
    signal_high: float,
    signal_low: float,
    signal_atr: float,
) -> int:
    # Defense-in-depth float() cast, on top of the callers already casting
    # their own candle-derived values: a raw numpy.int64 (unlike
    # numpy.float64) silently serializes to a BLOB instead of a REAL via
    # sqlite3's bind parameters rather than erroring -- hit live
    # (2026-10-01, BAJAJ-AUTO: that day's OHLCV all happened to be whole
    # numbers, fetched as an int64 dtype column) and corrupted
    # signal_high/signal_low until the next read crashed the dashboard.
    # float() on a plain Python float is a no-op, so this is free for
    # every normal (already-float) call.
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO intraday_signals (date, symbol, signal_time, signal_high, "
        "signal_low, signal_atr) VALUES (?, ?, ?, ?, ?, ?)",
        (date, symbol, signal_time, float(signal_high), float(signal_low), float(signal_atr)),
    )
    signal_id = cur.lastrowid
    conn.commit()
    conn.close()
    return signal_id


def update_signal_status(signal_id: int, status: str) -> None:
    """status: 'active' | 'expired' | 'triggered' | 'invalidated'."""
    conn = get_conn()
    conn.execute(
        "UPDATE intraday_signals SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (status, signal_id),
    )
    conn.commit()
    conn.close()


def get_active_signal(date: str, symbol: str) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM intraday_signals WHERE date = ? AND symbol = ? AND status = 'active' "
        "ORDER BY id DESC LIMIT 1",
        (date, symbol),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_signals(date: str) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql(
        "SELECT symbol, signal_time, signal_high, signal_low, signal_atr, status "
        "FROM intraday_signals WHERE date = ? ORDER BY id",
        conn,
        params=(date,),
    )
    conn.close()
    return df


# ---------------------------------------------------------------------------
# Positions / legs -- Spec.md §4-§5
# ---------------------------------------------------------------------------


def record_new_position(
    date: str,
    symbol: str,
    direction: str,
    entry_time: str,
    entry_price: float,
    stop_price: float,
    target_price: float,
    qty: int,
    mode: str,
    signal_time: str | None = None,
    order_id: str | None = None,
) -> int:
    """mode: 'paper' | 'live'. Returns the new position's row id -- pass
    it to close_position_leg() for each exit leg."""
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO intraday_positions (date, symbol, direction, signal_time, "
        "entry_time, entry_price, stop_price, target_price, qty, qty_remaining, "
        "status, mode, order_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)",
        (
            date,
            symbol,
            direction,
            signal_time,
            entry_time,
            entry_price,
            stop_price,
            target_price,
            qty,
            qty,
            mode,
            order_id,
        ),
    )
    position_id = cur.lastrowid
    conn.commit()
    conn.close()
    return position_id


def close_position_leg(
    position_id: int,
    leg_type: str,
    qty: int,
    exit_price: float,
    exit_time: str,
    gross_pnl: float,
    costs: float,
    net_pnl: float,
    order_id: str | None = None,
) -> None:
    """Records one exit leg and decrements the parent position's
    qty_remaining -- flips status to 'closed' once it reaches 0.
    leg_type: 'target' | 'ema5_trail_exit' | 'ema10_trail_exit' | 'stop' |
    'squareoff' | 'eod_data_end'."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO intraday_legs (position_id, leg_type, qty, exit_price, exit_time, "
        "gross_pnl, costs, net_pnl, order_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (position_id, leg_type, qty, exit_price, exit_time, gross_pnl, costs, net_pnl, order_id),
    )
    row = conn.execute(
        "SELECT qty_remaining FROM intraday_positions WHERE id = ?", (position_id,)
    ).fetchone()
    new_remaining = max(0, row["qty_remaining"] - qty)
    new_status = "closed" if new_remaining == 0 else "open"
    conn.execute(
        "UPDATE intraday_positions SET qty_remaining = ?, status = ? WHERE id = ?",
        (new_remaining, new_status, position_id),
    )
    conn.commit()
    conn.close()


def mark_target_touched(position_id: int, touch_time: str, trail_ema: int) -> None:
    """v5.2: the 1:2R target was first touched and the first-half booking
    is deferred -- record when, and which EMA (5 or 10) to trail."""
    conn = get_conn()
    conn.execute(
        "UPDATE intraday_positions SET target_touch_time = ?, trail_ema = ? WHERE id = ?",
        (touch_time, trail_ema, position_id),
    )
    conn.commit()
    conn.close()


def get_position(position_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM intraday_positions WHERE id = ?", (position_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_open_positions(date: str | None = None, mode: str | None = None) -> pd.DataFrame:
    conn = get_conn()
    where, params = ["status = 'open'"], []
    if date:
        where.append("date = ?")
        params.append(date)
    if mode:
        where.append("mode = ?")
        params.append(mode)
    df = pd.read_sql(
        f"SELECT * FROM intraday_positions WHERE {' AND '.join(where)} ORDER BY id",
        conn,
        params=params,
    )
    conn.close()
    return df


def get_positions(date: str | None = None, mode: str | None = None) -> pd.DataFrame:
    """All positions (open + closed), optionally filtered -- for the
    Tradebook page."""
    conn = get_conn()
    where, params = [], []
    if date:
        where.append("date = ?")
        params.append(date)
    if mode:
        where.append("mode = ?")
        params.append(mode)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    df = pd.read_sql(f"SELECT * FROM intraday_positions {clause} ORDER BY id", conn, params=params)
    conn.close()
    return df


def get_legs(
    position_id: int | None = None, date: str | None = None, mode: str | None = None
) -> pd.DataFrame:
    """All legs, optionally for one position, or joined/filtered by the
    parent position's date/mode (for the Tradebook page's day view)."""
    conn = get_conn()
    if position_id is not None:
        df = pd.read_sql(
            "SELECT * FROM intraday_legs WHERE position_id = ? ORDER BY id",
            conn,
            params=(position_id,),
        )
        conn.close()
        return df
    where, params = [], []
    if date:
        where.append("p.date = ?")
        params.append(date)
    if mode:
        where.append("p.mode = ?")
        params.append(mode)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    df = pd.read_sql(
        f"SELECT l.*, p.date, p.symbol, p.direction, p.entry_price, p.entry_time, "
        f"p.qty AS position_qty, p.mode AS position_mode FROM intraday_legs l "
        f"JOIN intraday_positions p ON p.id = l.position_id {clause} ORDER BY l.id",
        conn,
        params=params,
    )
    conn.close()
    return df


# ---------------------------------------------------------------------------
# Capital -- Spec.md §7, tracked separately per mode
# ---------------------------------------------------------------------------


def ensure_capital_seeded(mode: str, starting_capital: float) -> None:
    """First-run only for this mode: seeds starting_capital ==
    current_capital. No-ops if a row for this mode already exists --
    safe to call on every engine start."""
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM intraday_capital_state WHERE mode = ?", (mode,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO intraday_capital_state (mode, starting_capital, current_capital) "
            "VALUES (?, ?, ?)",
            (mode, starting_capital, starting_capital),
        )
        conn.commit()
    conn.close()


def get_capital(mode: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM intraday_capital_state WHERE mode = ?", (mode,)).fetchone()
    conn.close()
    return dict(row) if row else None


def apply_day_pnl(mode: str, day_pnl: float) -> float:
    """Compounds one day's net P&L into this mode's current_capital
    (Spec.md §7: "next_day_capital = today_capital + today's_total_net_
    P&L"). Returns the new current_capital. Raises if ensure_capital_
    seeded() was never called for this mode."""
    conn = get_conn()
    row = conn.execute(
        "SELECT current_capital FROM intraday_capital_state WHERE mode = ?", (mode,)
    ).fetchone()
    if row is None:
        conn.close()
        raise ValueError(
            f"intraday_capital_state has no row for mode={mode!r} -- "
            f"call ensure_capital_seeded() first"
        )
    new_capital = row["current_capital"] + day_pnl
    conn.execute(
        "UPDATE intraday_capital_state SET current_capital = ?, updated_at = datetime('now') "
        "WHERE mode = ?",
        (new_capital, mode),
    )
    conn.commit()
    conn.close()
    return new_capital
