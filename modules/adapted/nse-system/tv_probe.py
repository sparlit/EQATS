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


import requests

URL = "https://scanner.tradingview.com/india/scan"
CANDIDATES = [
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
    "gross_margin_fq",
    "revenue_growth_fy",
    "net_income_growth_fy",
    "dividend_yield_recent",
    "operating_cash_flow_fq",
    "free_cash_flow_fq",
    "total_debt_fq",
    "book_value_per_share_fq",
    "price_to_sales_ttm",
    "ev_to_ebitda_fq",
    "sector",
    "industry",
]

body = {"symbols": {"tickers": ["NSE:RELIANCE"]}, "columns": CANDIDATES}
r = requests.post(URL, headers={"User-Agent": "Mozilla/5.0"}, json=body, timeout=30)
print("status:", r.status_code)
if r.status_code != 200:
    print(r.text[:2000])
else:
    data = r.json().get("data", [])
    if data:
        vals = dict(zip(CANDIDATES, data[0]["d"], strict=False))
        print("HAS VALUE:")
        for k, v in vals.items():
            if v is not None:
                print(f"  {k} = {v}")
        print("NULL:", [k for k, v in vals.items() if v is None])
