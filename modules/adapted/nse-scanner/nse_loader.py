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
nse_loader.py — SQLite Database Loader (v2 — Rolling 180-day window)
=====================================================================
WHAT CHANGED FROM v1:
  NEW: delete_oldest_day()  — deletes the oldest day from DB
  NEW: get_loaded_date_range() — returns (oldest_date, newest_date, count)
  NEW: trim_to_180_days()   — keeps exactly 180 trading days, deletes rest

Rolling window logic:
  1. Load today's data  → DB has 181 days
  2. trim_to_180_days() → DB back to exactly 180 days
  3. Oldest day is automatically removed

Everything else (init_database, load_day, show_status, CLI) unchanged.

Database: nse_scanner.db
Tables:
    daily_prices   -- OHLCV + delivery per stock per day  (CORE)
    blacklist      -- Regulatory flagged stocks per day
    index_perf     -- Daily index performance
    volatility     -- Annual volatility per stock (optional)
    week52         -- 52-week high/low per stock  (optional)
    pe_ratios      -- P/E ratio per stock         (optional)
    load_log       -- Tracks which dates loaded successfully

Usage:
    python nse_loader.py --date 05-03-2026       # Load one day
    python nse_loader.py --all                    # Load all downloaded days
    python nse_loader.py --last 90               # Load last 90 trading days
    python nse_loader.py --status                # Show what is loaded
    python nse_loader.py --trim                  # Trim to 180 days now
"""

import argparse
import contextlib
import glob
import logging
import os
import shutil
import sqlite3
import sys
from datetime import date, datetime, timedelta

import pandas as pd

try:
    from nse_parser import parse_all
except ImportError:
    print("ERROR: nse_parser.py not found.")
    sys.exit(1)

SAVE_ROOT = "nse_data"
DB_PATH = "nse_scanner.db"
LOG_DIR = "logs"
KEEP_DAYS = 180  # Rolling window size

DELETE_AFTER_LOAD = [
    "CMVOLT_*.CSV",
    "CMVOLT_*.csv",
    "MTO_*.DAT",
    "FCM_INTRM_BC*.DAT",
    "C_VAR1_*.DAT",
    "*.gz",
    "BhavCopy_*.zip",
    "Margintrdg_*.zip",
    "sme*.csv",
    "MF_VAR_*.csv",
    "MA*.csv",
    "CSQR_M_*.csv",
]

MIN_ROWS = {
    "bhavdata": 1000,
    "blacklist": 10,
    "ind_close": 100,
    "volatility": 100,
    "week52": 100,
    "pe": 100,
}

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "loader.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# DATABASE HELPERS
# ═══════════════════════════════════════════════════════════════════════════


def get_db(path=DB_PATH):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=10000")
    return conn


def init_database(path=DB_PATH):
    conn = get_db(path)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS daily_prices (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol        TEXT    NOT NULL,
        date          DATE    NOT NULL,
        prev_close    REAL, open REAL, high REAL, low REAL,
        last_price    REAL, close REAL NOT NULL,
        avg_price     REAL, volume INTEGER,
        turnover_lacs REAL, trades INTEGER,
        delivery_qty  INTEGER, delivery_pct REAL,
        UNIQUE(symbol, date))""")

    c.execute("""CREATE TABLE IF NOT EXISTS blacklist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL, date DATE NOT NULL,
        UNIQUE(symbol, date))""")

    c.execute("""CREATE TABLE IF NOT EXISTS index_perf (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        index_name TEXT NOT NULL, date DATE NOT NULL,
        open REAL, high REAL, low REAL, close REAL,
        change_pct REAL, volume INTEGER,
        pe REAL, pb REAL, div_yield REAL,
        UNIQUE(index_name, date))""")

    c.execute("""CREATE TABLE IF NOT EXISTS volatility (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL, date DATE NOT NULL,
        daily_vol REAL, annual_vol REAL,
        UNIQUE(symbol, date))""")

    c.execute("""CREATE TABLE IF NOT EXISTS week52 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL, date DATE NOT NULL,
        week52_high REAL, week52_low REAL,
        UNIQUE(symbol, date))""")

    c.execute("""CREATE TABLE IF NOT EXISTS pe_ratios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL, date DATE NOT NULL,
        pe_ratio REAL,
        UNIQUE(symbol, date))""")

    c.execute("""CREATE TABLE IF NOT EXISTS load_log (
        date DATE PRIMARY KEY, loaded_at TEXT,
        prices_rows INTEGER DEFAULT 0,
        blacklist_rows INTEGER DEFAULT 0,
        index_rows INTEGER DEFAULT 0,
        vol_rows INTEGER DEFAULT 0,
        week52_rows INTEGER DEFAULT 0,
        pe_rows INTEGER DEFAULT 0,
        status TEXT DEFAULT 'ok', notes TEXT)""")

    c.execute("CREATE INDEX IF NOT EXISTS idx_prices_symbol ON daily_prices(symbol)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_prices_date   ON daily_prices(date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_bl_date       ON blacklist(date)")

    conn.commit()
    conn.close()
    log.info(f"Database ready: {path}")


# ═══════════════════════════════════════════════════════════════════════════
# ROLLING WINDOW — NEW FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════


def get_loaded_date_range(path=DB_PATH):
    """
    Returns (oldest_date_str, newest_date_str, total_days) from daily_prices.
    Returns (None, None, 0) if DB is empty.
    """
    if not os.path.exists(path):
        return None, None, 0
    try:
        conn = get_db(path)
        row = conn.execute("""
            SELECT MIN(date), MAX(date), COUNT(DISTINCT date)
            FROM daily_prices
        """).fetchone()
        conn.close()
        if row and row[0]:
            return row[0], row[1], row[2]
        return None, None, 0
    except Exception as e:
        log.exception(f"get_loaded_date_range error: {e}")
        return None, None, 0


def delete_oldest_day(path=DB_PATH, dry_run=False):
    """
    Deletes the single oldest date from all tables.
    Returns the date that was deleted, or None if DB empty.
    """
    oldest, _newest, _count = get_loaded_date_range(path)
    if not oldest:
        log.info("delete_oldest_day: DB empty, nothing to delete")
        return None

    if dry_run:
        log.info(f"[DRY RUN] Would delete oldest day: {oldest}")
        print(f"  [DRY RUN] Would delete: {oldest}")
        return oldest

    try:
        conn = get_db(path)
        tables = ["daily_prices", "blacklist", "index_perf", "volatility", "week52", "pe_ratios", "load_log"]
        total_deleted = 0
        for table in tables:
            try:
                cur = conn.execute(f"DELETE FROM {table} WHERE date = ?", [oldest])
                total_deleted += cur.rowcount
            except Exception:
                pass  # table may not have that date — that's fine
        conn.commit()
        conn.close()
        log.info(f"Deleted oldest day: {oldest} ({total_deleted} rows across all tables)")
        print(f"  🗑️  Deleted oldest day: {oldest} ({total_deleted} rows)")
        return oldest
    except Exception as e:
        log.exception(f"delete_oldest_day error: {e}")
        return None


def trim_to_180_days(keep_days=KEEP_DAYS, path=DB_PATH, dry_run=False):
    """
    Keeps exactly `keep_days` of trading data in the DB.
    Deletes oldest days one by one until count == keep_days.

    Returns: number of days deleted
    """
    oldest, newest, count = get_loaded_date_range(path)

    print(f"\n  {'─' * 50}")
    print("  ROLLING WINDOW TRIM")
    print(f"  Current DB: {count} days  ({oldest} → {newest})")
    print(f"  Target    : {keep_days} days")

    if count <= keep_days:
        print(f"  ✅ Already within {keep_days} days — no trim needed")
        print(f"  {'─' * 50}\n")
        return 0

    days_to_delete = count - keep_days
    deleted = 0

    for _ in range(days_to_delete):
        d = delete_oldest_day(path=path, dry_run=dry_run)
        if d:
            deleted += 1
        else:
            break

    oldest_after, newest_after, count_after = get_loaded_date_range(path)
    print(f"  After trim: {count_after} days  ({oldest_after} → {newest_after})")
    print(f"  ✅ Deleted {deleted} old day(s)")
    print(f"  {'─' * 50}\n")

    log.info(f"trim_to_180_days: deleted {deleted} days, DB now {count_after} days ({oldest_after} → {newest_after})")
    return deleted


# ═══════════════════════════════════════════════════════════════════════════
# VALIDATION
# ═══════════════════════════════════════════════════════════════════════════


def validate(name, data, trade_date):
    """Returns (is_valid, reason_string)."""
    if data is None:
        return False, "file not found or parse error"

    count = len(data) if not isinstance(data, set) else len(data)

    if isinstance(data, set):
        return (count >= MIN_ROWS.get(name, 1)), f"{count} symbols"

    if not isinstance(data, pd.DataFrame) or data.empty:
        return False, "empty"

    if count < MIN_ROWS.get(name, 1):
        return False, f"only {count} rows (min {MIN_ROWS.get(name, 1)})"

    needs = {
        "bhavdata": ["symbol", "close", "date"],
        "ind_close": ["index_name", "close"],
        "volatility": ["symbol", "annual_vol"],
        "week52": ["symbol", "week52_high"],
        "pe": ["symbol", "pe_ratio"],
    }
    if name in needs:
        missing = [c for c in needs[name] if c not in data.columns]
        if missing:
            return False, f"missing columns: {missing}"

    if "close" in data.columns and data["close"].isna().mean() > 0.5:
        return False, "more than 50% null close prices"

    return True, f"{count} rows OK"


# ═══════════════════════════════════════════════════════════════════════════
# LOADERS
# ═══════════════════════════════════════════════════════════════════════════


def _dedup(conn, table, key_cols):
    keys = ", ".join(key_cols)
    conn.execute(f"""
        DELETE FROM {table} WHERE id NOT IN (
            SELECT MIN(id) FROM {table} GROUP BY {keys})""")
    conn.commit()


def load_prices(conn, df, trade_date):
    df = df.copy()
    df["date"] = trade_date.isoformat()
    cols = [
        c
        for c in [
            "symbol",
            "date",
            "prev_close",
            "open",
            "high",
            "low",
            "last_price",
            "close",
            "avg_price",
            "volume",
            "turnover_lacs",
            "trades",
            "delivery_qty",
            "delivery_pct",
        ]
        if c in df.columns
    ]
    before = conn.execute("SELECT COUNT(*) FROM daily_prices").fetchone()[0]
    df[cols].to_sql("daily_prices", conn, if_exists="append", index=False, chunksize=500)
    _dedup(conn, "daily_prices", ["symbol", "date"])
    after = conn.execute("SELECT COUNT(*) FROM daily_prices").fetchone()[0]
    return after - before


def load_blacklist(conn, symbols, trade_date):
    rows = [(s, trade_date.isoformat()) for s in symbols]
    c = conn.cursor()
    c.executemany("INSERT OR IGNORE INTO blacklist(symbol,date) VALUES(?,?)", rows)
    conn.commit()
    return c.rowcount


def load_index(conn, df, trade_date):
    df = df.copy()

    if "date" not in df.columns or df["date"].isna().all():
        df["date"] = trade_date.isoformat()
    else:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date.astype(str)

    cols = [
        c
        for c in ["index_name", "date", "open", "high", "low", "close", "change_pct", "volume", "pe", "pb", "div_yield"]
        if c in df.columns
    ]

    if not cols or "index_name" not in cols or "date" not in cols:
        return 0

    # Remove duplicates contained inside the CSV itself.
    data = df[cols].drop_duplicates(subset=["index_name", "date"], keep="last")

    # SQLite requires None instead of pandas NaN/NaT.
    data = data.astype(object).where(pd.notna(data), None)

    quoted_cols = ", ".join(f'"{col}"' for col in cols)
    placeholders = ", ".join("?" for _ in cols)

    sql = f"INSERT OR IGNORE INTO index_perf ({quoted_cols}) VALUES ({placeholders})"

    before = conn.total_changes

    conn.executemany(sql, data.itertuples(index=False, name=None))
    conn.commit()

    return conn.total_changes - before


def load_vol(conn, df, trade_date):
    df = df.copy()
    df["date"] = trade_date.isoformat()
    cols = [c for c in ["symbol", "date", "daily_vol", "annual_vol"] if c in df.columns]
    before = conn.execute("SELECT COUNT(*) FROM volatility").fetchone()[0]
    df[cols].to_sql("volatility", conn, if_exists="append", index=False, chunksize=500)
    _dedup(conn, "volatility", ["symbol", "date"])
    after = conn.execute("SELECT COUNT(*) FROM volatility").fetchone()[0]
    return after - before


def load_w52(conn, df, trade_date):
    df = df.copy()
    df["date"] = trade_date.isoformat()
    cols = [c for c in ["symbol", "date", "week52_high", "week52_low"] if c in df.columns]
    # NSE's 52-week file can publish the same symbol more than once on a
    # trading day.  The database correctly has a unique (symbol, date) key,
    # so remove source duplicates before insertion rather than failing the
    # complete daily load.
    df = df.drop_duplicates(subset=["symbol", "date"], keep="last")
    before = conn.execute("SELECT COUNT(*) FROM week52").fetchone()[0]
    df[cols].to_sql("week52", conn, if_exists="append", index=False, chunksize=500)
    _dedup(conn, "week52", ["symbol", "date"])
    after = conn.execute("SELECT COUNT(*) FROM week52").fetchone()[0]
    return after - before


def load_pe(conn, df, trade_date):
    df = df.copy()
    df["date"] = trade_date.isoformat()
    cols = [c for c in ["symbol", "date", "pe_ratio"] if c in df.columns]
    before = conn.execute("SELECT COUNT(*) FROM pe_ratios").fetchone()[0]
    df[cols].to_sql("pe_ratios", conn, if_exists="append", index=False, chunksize=500)
    _dedup(conn, "pe_ratios", ["symbol", "date"])
    after = conn.execute("SELECT COUNT(*) FROM pe_ratios").fetchone()[0]
    return after - before


# ═══════════════════════════════════════════════════════════════════════════
# CLEANUP (CSV files after load)
# ═══════════════════════════════════════════════════════════════════════════


def cleanup_day(day_folder, dry_run=False):
    deleted = []
    for pattern in DELETE_AFTER_LOAD:
        for f in glob.glob(os.path.join(day_folder, pattern)):
            size_kb = os.path.getsize(f) / 1024
            if dry_run:
                print(f"   WOULD DELETE: {os.path.basename(f)}  ({size_kb:.0f} KB)")
            else:
                os.remove(f)
                deleted.append(f)
                log.info(f"Cleaned: {os.path.basename(f)} ({size_kb:.0f} KB)")
    return deleted


# ═══════════════════════════════════════════════════════════════════════════
# CORE: LOAD ONE DAY
# ═══════════════════════════════════════════════════════════════════════════


def load_day(trade_date, do_cleanup=False, force=False):
    fmt = trade_date.strftime("%Y/%m/%d")
    folder = os.path.join(SAVE_ROOT, fmt)
    result = {
        "date": trade_date,
        "status": "ok",
        "rows": {},
        "skipped": [],
        "errors": [],
    }

    print(f"\n{'=' * 56}")
    print(f"  Loading: {trade_date.strftime('%d-%b-%Y')}  ({trade_date.strftime('%A')})")
    print(f"{'=' * 56}")

    if not os.path.exists(folder):
        print(f"  SKIP  Folder not found: {folder}")
        result["status"] = "skip"
        return result

    conn = get_db()

    if not force:
        already = conn.execute(
            "SELECT date FROM load_log WHERE date=? AND status='ok'", [trade_date.isoformat()]
        ).fetchone()
        if already:
            print("  Already loaded — skipping (use --force to reload)")
            conn.close()
            result["status"] = "already_loaded"
            return result

    parsed = parse_all(folder, trade_date)
    notes = []
    log_row = {
        "date": trade_date.isoformat(),
        "loaded_at": datetime.now().isoformat(),
        "prices_rows": 0,
        "blacklist_rows": 0,
        "index_rows": 0,
        "vol_rows": 0,
        "week52_rows": 0,
        "pe_rows": 0,
        "status": "ok",
        "notes": "",
    }

    # 1 — Prices (REQUIRED)
    ok, reason = validate("bhavdata", parsed["bhavdata"], trade_date)
    if ok:
        n = load_prices(conn, parsed["bhavdata"], trade_date)
        log_row["prices_rows"] = n
        result["rows"]["prices"] = n
        print(f"  OK    daily_prices    : {n} rows inserted")
    else:
        msg = f"Prices FAILED: {reason}"
        print(f"  FAIL  daily_prices    : {reason}")
        result["errors"].append(msg)
        result["status"] = "partial"
        log_row["status"] = "partial"
        notes.append(msg)

    # 2 — Blacklist (REQUIRED)
    ok, reason = validate("blacklist", parsed["blacklist"], trade_date)
    if ok:
        n = load_blacklist(conn, parsed["blacklist"], trade_date)
        log_row["blacklist_rows"] = len(parsed["blacklist"])
        result["rows"]["blacklist"] = n
        print(f"  OK    blacklist       : {len(parsed['blacklist'])} symbols")
    else:
        print(f"  SKIP  blacklist       : {reason}")
        result["skipped"].append("blacklist")

    # 3 — Index (REQUIRED)
    ok, reason = validate("ind_close", parsed["ind_close"], trade_date)
    if ok:
        n = load_index(conn, parsed["ind_close"], trade_date)
        log_row["index_rows"] = n
        result["rows"]["index_perf"] = n
        print(f"  OK    index_perf      : {n} indices inserted")
    else:
        print(f"  SKIP  index_perf      : {reason}")
        result["skipped"].append("index_perf")

    # 4 — Volatility (OPTIONAL)
    ok, reason = validate("volatility", parsed["volatility"], trade_date)
    if ok:
        n = load_vol(conn, parsed["volatility"], trade_date)
        log_row["vol_rows"] = n
        result["rows"]["volatility"] = n
        print(f"  OK    volatility      : {n} rows")
    else:
        print("  SKIP  volatility      : not available")

    # 5 — 52W (OPTIONAL)
    ok, reason = validate("week52", parsed["week52"], trade_date)
    if ok:
        n = load_w52(conn, parsed["week52"], trade_date)
        log_row["week52_rows"] = n
        result["rows"]["week52"] = n
        print(f"  OK    week52          : {n} rows")
    else:
        print("  SKIP  week52          : not available")

    # 6 — PE (OPTIONAL)
    ok, reason = validate("pe", parsed["pe"], trade_date)
    if ok:
        n = load_pe(conn, parsed["pe"], trade_date)
        log_row["pe_rows"] = n
        result["rows"]["pe"] = n
        print(f"  OK    pe_ratios       : {n} rows")
    else:
        print("  SKIP  pe_ratios       : not available")

    log_row["notes"] = " | ".join(notes)
    conn.execute(
        """INSERT OR REPLACE INTO load_log
        (date,loaded_at,prices_rows,blacklist_rows,index_rows,
         vol_rows,week52_rows,pe_rows,status,notes)
        VALUES (:date,:loaded_at,:prices_rows,:blacklist_rows,:index_rows,
                :vol_rows,:week52_rows,:pe_rows,:status,:notes)""",
        log_row,
    )
    conn.commit()
    conn.close()

    if do_cleanup and result["status"] != "skip":
        deleted = cleanup_day(folder)
        if deleted:
            print(f"  Cleanup: deleted {len(deleted)} large files")

    total = sum(result["rows"].values())
    print(f"  Summary: {total} rows | status={result['status']}")
    log.info(f"Loaded {trade_date}: {total} rows, status={result['status']}")
    return result


# ═══════════════════════════════════════════════════════════════════════════
# STATUS
# ═══════════════════════════════════════════════════════════════════════════


def show_status():
    if not os.path.exists(DB_PATH):
        print(f"\n  Database not found: {DB_PATH}")
        return

    conn = get_db()
    size = os.path.getsize(DB_PATH) / 1024 / 1024

    print(f"\n{'=' * 56}")
    print("  NSE Scanner Database Status")
    print(f"  File : {os.path.abspath(DB_PATH)}")
    print(f"  Size : {size:.1f} MB")
    print(f"{'=' * 56}")

    for table in ["daily_prices", "blacklist", "index_perf", "volatility", "week52", "pe_ratios"]:
        try:
            r = conn.execute(f"""
                SELECT COUNT(*) as rows, COUNT(DISTINCT date) as days,
                       MIN(date) as earliest, MAX(date) as latest
                FROM {table}""").fetchone()
            print(f"  {table:<20} rows={r[0]:>7,}  days={r[1]:>3}  range={r[2] or 'n/a'} → {r[3] or 'n/a'}")
        except Exception:
            print(f"  {table:<20} -- not found")

    # Rolling window summary
    oldest, newest, count = get_loaded_date_range()
    print(f"\n  Rolling window    : {count} days  ({oldest} → {newest})")
    print(f"  Target            : {KEEP_DAYS} days")
    if count > KEEP_DAYS:
        print(f"  ⚠️  {count - KEEP_DAYS} day(s) over limit — run --trim")
    else:
        print("  ✅ Within limit")

    ll = conn.execute("SELECT status, COUNT(*) FROM load_log GROUP BY status").fetchall()
    if ll:
        print("\n  load_log: " + "  ".join(f"{s}={n}" for s, n in ll))

    conn.close()
    print(f"{'=' * 56}")


# ═══════════════════════════════════════════════════════════════════════════
# DISCOVER ALL DAY FOLDERS
# ═══════════════════════════════════════════════════════════════════════════


def find_all_day_folders():
    days = []
    for f in glob.glob(os.path.join(SAVE_ROOT, "*", "*", "*", "sec_bhavdata_full_*.csv")):
        parts = f.replace("\\", "/").split("/")
        with contextlib.suppress(IndexError, ValueError):
            days.append(date(int(parts[1]), int(parts[2]), int(parts[3])))
    return sorted(set(days))


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════


def parse_date_arg(s):
    for fmt in ["%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"]:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    print(f"Invalid date: {s}. Use DD-MM-YYYY")
    sys.exit(1)


def main():
    p = argparse.ArgumentParser(description="NSE Loader — load files into SQLite + rolling window")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--date", type=str, help="Load one date DD-MM-YYYY")
    g.add_argument("--all", action="store_true", help="Load all downloaded dates")
    g.add_argument("--last", type=int, metavar="N", help="Load last N days")
    g.add_argument("--status", action="store_true", help="Show DB status + rolling window info")
    g.add_argument("--trim", action="store_true", help="Trim DB to 180 days now")

    p.add_argument("--cleanup", action="store_true", help="Delete large CSV files after loading")
    p.add_argument("--force", action="store_true", help="Reload already loaded dates")
    p.add_argument("--dry-run", action="store_true", help="Show what trim would delete without deleting")
    args = p.parse_args()

    init_database()

    if args.status:
        show_status()
        return

    if args.trim:
        trim_to_180_days(dry_run=args.dry_run)
        show_status()
        return

    if args.date:
        load_day(parse_date_arg(args.date), do_cleanup=args.cleanup, force=args.force)
        show_status()
        return

    if args.all:
        days = find_all_day_folders()
    else:
        _today, days, d = date.today(), [], date.today()
        while len(days) < args.last:
            d -= timedelta(days=1)
            folder = os.path.join(SAVE_ROOT, d.strftime("%Y/%m/%d"))
            if os.path.exists(folder):
                days.append(d)

    if not days:
        print(f"\n  No downloaded data found in {SAVE_ROOT}/")
        return

    print(f"\n  Loading {len(days)} trading days...")
    ok_n = skip_n = fail_n = 0

    for i, d in enumerate(days):
        r = load_day(d, do_cleanup=args.cleanup, force=args.force)
        if r["status"] == "ok":
            ok_n += 1
        elif r["status"] in ("skip", "already_loaded"):
            skip_n += 1
        else:
            fail_n += 1
        pct = (i + 1) / len(days) * 100
        print(f"  Progress: {i + 1}/{len(days)} ({pct:.0f}%) OK={ok_n} SKIP={skip_n} FAIL={fail_n}")

    print(f"\n  Done: OK={ok_n}  SKIP={skip_n}  FAIL={fail_n}")
    show_status()


if __name__ == "__main__":
    main()
