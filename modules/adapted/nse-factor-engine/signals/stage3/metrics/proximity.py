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
Stage 3 — Metric: 52-Week High Proximity

Inputs : prices (full), T, T_252
Returns: dataframe with columns [symbol, proximity_52w_high]
"""

import pandas as pd


def compute(prices: pd.DataFrame, T, T_252) -> pd.DataFrame:
    close_T = prices[prices["date"] == T][["symbol", "close"]].rename(columns={"close": "close_T"})
    full_win = prices[(prices["date"] >= T_252) & (prices["date"] <= T)]
    high_52w = (
        full_win.groupby("symbol")["high"].max().reset_index().rename(columns={"high": "high_52w"})
    )
    prox_df = close_T.merge(high_52w, on="symbol", how="left")
    prox_df["proximity_52w_high"] = prox_df["close_T"] / prox_df["high_52w"]
    return prox_df[["symbol", "proximity_52w_high"]]
