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


import json
import os
import time
from datetime import UTC, datetime

import yfinance as yf

TICKERS = [
    "RELIANCE.NS",
    "TCS.NS",
    "INFY.NS",
    "HDFCBANK.NS",
    "ICICIBANK.NS",
    "BHARTIARTL.NS",
    "ITC.NS",
    "LT.NS",
    "SBIN.NS",
    "HINDUNILVR.NS",
    "MARUTI.NS",
    "SUNPHARMA.NS",
    "TMPV.NS",
    "ASIANPAINT.NS",
    "AXISBANK.NS",
]

PRICES_PATH = "/Volumes/stock_research/landing/raw_landing/prices"
FUNDAMENTALS_PATH = "/Volumes/stock_research/landing/raw_landing/fundamentals"

FUNDAMENTALS_FIELDS = [
    "shortName",
    "sector",
    "industry",
    "marketCap",
    "trailingPE",
    "forwardPE",
    "trailingEps",
    "dividendYield",
    "fiftyTwoWeekHigh",
    "fiftyTwoWeekLow",
    "currency",
]


def fetch_ticker(ticker: str, run_date: str):
    tk = yf.Ticker(ticker)

    hist = tk.history(period="1y", interval="1d")
    price_records = [
        {
            "ticker": ticker,
            "date": idx.strftime("%Y-%m-%d"),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": int(row["Volume"]),
        }
        for idx, row in hist.iterrows()
    ]

    info = tk.info
    fundamentals = {"ticker": ticker, "as_of": run_date}
    for field in FUNDAMENTALS_FIELDS:
        fundamentals[field] = info.get(field)

    return price_records, fundamentals


def main():
    os.makedirs(PRICES_PATH, exist_ok=True)
    os.makedirs(FUNDAMENTALS_PATH, exist_ok=True)

    run_date = datetime.now(UTC).strftime("%Y-%m-%d")

    for ticker in TICKERS:
        try:
            price_records, fundamentals = fetch_ticker(ticker, run_date)
        except Exception as e:
            print(f"FAILED {ticker}: {e}")
            continue

        safe_ticker = ticker.replace(".", "_")

        price_path = f"{PRICES_PATH}/{safe_ticker}_{run_date}.json"
        with open(price_path, "w") as f:
            json.dump(price_records, f)
        print(f"wrote {len(price_records)} rows -> {price_path}")

        fund_path = f"{FUNDAMENTALS_PATH}/{safe_ticker}_{run_date}.json"
        with open(fund_path, "w") as f:
            json.dump(fundamentals, f)
        print(f"wrote fundamentals -> {fund_path}")

        time.sleep(1)  # be polite to Yahoo's unofficial endpoint


if __name__ == "__main__":
    main()
