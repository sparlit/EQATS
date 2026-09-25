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


import datetime as dt
import json
import sys
import time

import db
import requests

URL = "https://scanner.tradingview.com/india/scan"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

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


def fetch_batch(tickers):
    body = {"symbols": {"tickers": tickers}, "columns": COLUMNS}
    r = requests.post(URL, headers=HEADERS, json=body, timeout=30)
    r.raise_for_status()
    return r.json().get("data", [])


def run():
    conn = db.get_conn()
    symbols = [r[0] for r in conn.execute("SELECT symbol FROM stocks WHERE active=1 ORDER BY symbol")]
    now = "tv:" + dt.datetime.now().isoformat()
    saved = 0
    for b in range(0, len(symbols), 100):
        batch = symbols[b : b + 100]
        try:
            data = fetch_batch(["NSE:" + s for s in batch])
        except Exception as e:
            print(f"batch {b // 100 + 1} failed: {e}")
            time.sleep(5)
            continue
        for item in data:
            sym = item["s"].replace("NSE:", "")
            d = item["d"]
            m = dict(zip(COLUMNS, d, strict=False))
            mcap = m.get("market_cap_basic")
            de = m.get("debt_to_equity_fq")
            conn.execute("DELETE FROM fundamentals WHERE symbol=?", (sym,))
            conn.execute(
                "INSERT INTO fundamentals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    sym,
                    m.get("name"),
                    None,
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
                    None,
                    m.get("dividend_yield_recent"),
                    None,
                    now,
                ),
            )
            saved += 1
        print(f"batch {b // 100 + 1}: saved {saved} so far")
        time.sleep(1)

    print(f"Total fundamentals saved: {saved}")
    print("SAMPLE FOR VERIFICATION:")
    for sym in ["RELIANCE", "TCS", "HDFCBANK"]:
        r = conn.execute("SELECT * FROM fundamentals WHERE symbol=?", (sym,)).fetchone()
        if r:
            print(
                json.dumps(
                    dict(zip([c[0] for c in conn.execute("PRAGMA table_info(fundamentals)")], r, strict=False)),
                    indent=1,
                    default=str,
                )
            )
    conn.commit()
    conn.close()


if len(sys.argv) > 1 and sys.argv[1] == "run":
    run()
