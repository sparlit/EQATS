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
Fundamentals fetcher (canonical) — TradingView India scanner.
Free, no auth, batch fetch. Fills the `fundamentals` table.

v2 (2026-09-12): canonical fetcher, uses log_utils, retries with backoff,
batch commits, fills sector from stocks table.
"""
import datetime as dt
import sys
import time

import db
import requests
from log_utils import get_logger

log = get_logger("fundamentals")

URL = "https://scanner.tradingview.com/india/scan"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
BATCH_SIZE = 100

COLUMNS = [
    "name",
    "close",
    "market_cap_basic",
    "price_earnings_ttm",
    "price_to_book_fq",
    "return_on_equity_fq",
    "return_on_invested_capital_fq",
    "debt_to_equity_fq",
    "interest_coverage_fq",
    "operating_margin_fq",
    "net_margin_fq",
    "revenue_growth_fy",
    "net_income_growth_fy",
    "dividend_yield_recent",
]


def _fetch_batch(tickers, retries=3):
    body = {"symbols": {"tickers": tickers}, "columns": COLUMNS}
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.post(URL, headers=HEADERS, json=body, timeout=30)
            r.raise_for_status()
            return r.json().get("data", [])
        except Exception as e:
            last_err = e
            wait = 2 * (attempt + 1)
            log.warning(f"batch failed (attempt {attempt + 1}/{retries}): {e}; retrying in {wait}s")
            time.sleep(wait)
    log.error(f"batch failed permanently: {last_err}")
    return []


def _sector_map(conn):
    out = {}
    for s, sec in conn.execute("SELECT symbol, sector FROM stocks WHERE sector IS NOT NULL"):
        out[s] = sec
    return out


def _upsert(conn, row):
    conn.execute("INSERT OR REPLACE INTO fundamentals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)


def run(limit=None):
    conn = db.get_conn()
    symbols = [r[0] for r in conn.execute("SELECT symbol FROM stocks WHERE active=1 ORDER BY symbol")]
    if limit:
        symbols = symbols[:limit]
    total = len(symbols)
    log.info(f"fundamentals fetch: {total} symbols, batch={BATCH_SIZE}")

    sectors = _sector_map(conn)
    now = "tv:" + dt.datetime.now().isoformat()
    saved = 0
    ok_batches = 0
    failed_batches = 0

    for b in range(0, total, BATCH_SIZE):
        batch = symbols[b : b + BATCH_SIZE]
        tickers = ["NSE:" + s for s in batch]
        data = _fetch_batch(tickers)
        if not data:
            failed_batches += 1
            continue
        ok_batches += 1
        for item in data:
            sym = item["s"].replace("NSE:", "")
            d = item["d"]
            m = dict(zip(COLUMNS, d, strict=False))
            mcap = m.get("market_cap_basic")
            de = m.get("debt_to_equity_fq")
            _upsert(
                conn,
                (
                    sym,
                    m.get("name"),
                    sectors.get(sym),
                    m.get("close"),
                    None if mcap is None else mcap / 1e7,
                    m.get("price_earnings_ttm"),
                    m.get("price_to_book_fq"),
                    m.get("return_on_equity_fq"),
                    m.get("return_on_invested_capital_fq"),
                    None if de is None else de / 100.0,
                    m.get("interest_coverage_fq"),
                    m.get("operating_margin_fq"),
                    m.get("net_margin_fq"),
                    m.get("revenue_growth_fy"),
                    m.get("net_income_growth_fy"),
                    None,
                    None,
                    None,  # promoter, pledge, fii (not on TV)
                    m.get("dividend_yield_recent"),
                    None,  # cfo_positive (not on TV)
                    now,
                ),
            )
            saved += 1
        conn.commit()
        log.info(f"batch {b // BATCH_SIZE + 1}: saved {saved} so far")

    conn.close()
    log.info(f"fundamentals fetch complete: saved={saved} batches_ok={ok_batches} batches_failed={failed_batches}")
    return saved


def show(n=10):
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT symbol, name, pe, roce, debt_to_equity, dividend_yield "
        "FROM fundamentals WHERE uploaded_at LIKE 'tv:%' "
        "ORDER BY symbol LIMIT ?",
        (n,),
    ).fetchall()
    conn.close()
    log.info(f"sample rows from fundamentals ({len(rows)}):")
    for r in rows:
        log.info(f"  {r}")


def count():
    conn = db.get_conn()
    n = conn.execute("SELECT COUNT(*) FROM fundamentals WHERE uploaded_at LIKE 'tv:%'").fetchone()[0]
    conn.close()
    log.info(f"fundamentals rows tagged 'tv:': {n}")
    return n


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else None
        run(limit=n)
        count()
    elif cmd == "sample":
        run(limit=5)
        show()
    elif cmd == "show":
        show()
        count()
