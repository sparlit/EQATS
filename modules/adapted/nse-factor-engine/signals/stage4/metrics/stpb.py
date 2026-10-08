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
Stage 4 — Short-Term Price Behaviour
Capitalmind: recent price action at point of entry.
Reduces probability of buying at peak before reversal.

Five sub-metrics, all describing the T-21->T (and T-7->T) window —
i.e. exactly the skip-month window that Stage 2/3 deliberately excluded.

NOTE: stpb_zscore_21d / stpb_zscore_7d are NOT statistical z-scores.
Numerator window (T-21->T or T-7->T) and denominator window (vol_231,
which is T-252->T-21) do not overlap. This is intentional — it measures
the recent move against the stock's PRIOR baseline volatility, not its
current volatility (using current-window vol would self-dampen exactly
the spike we want to detect). Do not assume ~N(0,1) or apply z-score
conventions (e.g. +/-3 clipping) to these columns downstream.
"""
import pandas as pd


def compute(prices: pd.DataFrame, signals: pd.DataFrame, T, all_dates) -> pd.DataFrame:
    """
    prices   : full prices.parquet (symbol, date, open, high, low, close, volume)
    signals  : stage2+3 final signals file, must contain symbol, vol_231
    T        : robustly-resolved T (date)
    all_dates: sorted list of trading dates <= T (from robust T resolution)

    Returns DataFrame: symbol, stpb_ret_21d, stpb_ret_7d,
                        stpb_zscore_21d, stpb_zscore_7d, stpb_ma_distance_21d
    """
    T_21 = all_dates[-22]
    T_7 = all_dates[-8]

    close_T = prices[prices["date"] == T][["symbol", "close"]].rename(columns={"close": "close_T"})
    close_T21 = prices[prices["date"] == T_21][["symbol", "close"]].rename(
        columns={"close": "close_T21"}
    )
    close_T7 = prices[prices["date"] == T_7][["symbol", "close"]].rename(
        columns={"close": "close_T7"}
    )

    out = close_T.merge(close_T21, on="symbol", how="outer")
    out = out.merge(close_T7, on="symbol", how="outer")

    out["stpb_ret_21d"] = (out["close_T"] - out["close_T21"]) / out["close_T21"]
    out["stpb_ret_7d"] = (out["close_T"] - out["close_T7"]) / out["close_T7"]

    # MA_21: trailing 21-trading-day simple moving average of close, ending at T
    # window is (T_21, T] i.e. T_21 EXCLUDED, T INCLUDED -> exactly 21 trading days
    window_21 = prices[(prices["date"] > T_21) & (prices["date"] <= T)]
    ma_21 = window_21.groupby("symbol")["close"].mean().rename("ma_21").reset_index()
    out = out.merge(ma_21, on="symbol", how="left")
    out["stpb_ma_distance_21d"] = (out["close_T"] - out["ma_21"]) / out["ma_21"]

    # vol_231 reused from Stage 2 final signals (matched-window baseline vol)
    out = out.merge(signals[["symbol", "vol_231"]], on="symbol", how="left")
    out["stpb_zscore_21d"] = out["stpb_ret_21d"] / out["vol_231"]
    out["stpb_zscore_7d"] = out["stpb_ret_7d"] / out["vol_231"]

    return out[
        [
            "symbol",
            "stpb_ret_21d",
            "stpb_ret_7d",
            "stpb_zscore_21d",
            "stpb_zscore_7d",
            "stpb_ma_distance_21d",
        ]
    ]
