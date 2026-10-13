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
Stage 3 — Metric: Weinstein Stage 2 Breakout

Classifies each stock as Stage 2 (True) or not (False). All THREE conditions
must be True:
  1. Weekly close > 30-week moving average
  2. 30-week MA slope is positive (MA this week > MA last week)
  3. 150-day SMA > 200-day SMA (daily SMAs on daily close, evaluated at T)

Inputs : prices (full price history), T
Returns: dataframe with columns [symbol, weinstein_stage2]
"""

import pandas as pd


def compute(prices: pd.DataFrame, T) -> pd.DataFrame:
    px = prices[prices["date"] <= T][["symbol", "date", "close"]].copy()
    px = px.sort_values(["symbol", "date"])

    # ── Conditions 1 & 2: weekly 30-week MA ──────────────────────────────────
    # Weekly close = last close of each calendar week per symbol
    px["week"] = px["date"].dt.to_period("W")
    weekly = px.groupby(["symbol", "week"])["close"].last().reset_index()
    weekly = weekly.sort_values(["symbol", "week"])

    # 30-week MA
    weekly["ma30w"] = weekly.groupby("symbol")["close"].transform(
        lambda x: x.rolling(30, min_periods=20).mean()
    )
    weekly["ma30w_prev"] = weekly.groupby("symbol")["ma30w"].transform(lambda x: x.shift(1))

    weekly["ma_slope_pos"] = weekly["ma30w"] > weekly["ma30w_prev"]
    weekly["price_above_ma"] = weekly["close"] > weekly["ma30w"]

    latest_weekly = (
        weekly.sort_values("week")
        .groupby("symbol")
        .last()
        .reset_index()[["symbol", "ma_slope_pos", "price_above_ma"]]
    )

    # ── Condition 3: 150-day SMA > 200-day SMA (daily, at T) ──────────────────
    px["sma150"] = px.groupby("symbol")["close"].transform(
        lambda x: x.rolling(150, min_periods=100).mean()
    )
    px["sma200"] = px.groupby("symbol")["close"].transform(
        lambda x: x.rolling(200, min_periods=130).mean()
    )

    latest_daily = (
        px.sort_values("date")
        .groupby("symbol")
        .last()
        .reset_index()[["symbol", "sma150", "sma200"]]
    )
    latest_daily["sma150_gt_sma200"] = latest_daily["sma150"] > latest_daily["sma200"]

    # ── Combine all three ────────────────────────────────────────────────────
    out = latest_weekly.merge(latest_daily[["symbol", "sma150_gt_sma200"]], on="symbol", how="left")
    out["weinstein_stage2"] = out["ma_slope_pos"] & out["price_above_ma"] & out["sma150_gt_sma200"]

    return out[["symbol", "weinstein_stage2"]]
