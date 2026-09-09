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


import numpy as np
import pandas as pd
import yfinance as yf

SECTOR_UNIVERSE = {
    "Banking": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "PNB", "IDFCFIRSTB", "FEDERALBNK"],
}


def debug_advisor():
    candidate_symbols = SECTOR_UNIVERSE["Banking"]
    yf_tickers = [f"{s}.NS" for s in candidate_symbols]

    print(f"Fetching prices for {yf_tickers}...")
    try:
        price_df = yf.download(yf_tickers, period="5d", progress=False)["Close"]
        print(f"Price DF columns: {price_df.columns.tolist()}")
        print(f"Price DF head:\n{price_df.tail(1)}")

        current_prices = {}
        for sym in candidate_symbols:
            ticker_col = f"{sym}.NS"
            if ticker_col in price_df.columns:
                val = price_df[ticker_col].dropna()
                if not val.empty:
                    current_prices[sym] = float(val.iloc[-1])
            else:
                print(f"Ticker {ticker_col} NOT found in columns!")

        print(f"Processed prices: {current_prices}")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    debug_advisor()
