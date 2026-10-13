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
Stage 4 — Volume Confirmation
Capitalmind: recent volume relative to longer-term average.
Rising price on rising volume = valid momentum.

vol_ratio_21_252 = avg_volume(21d recent) / avg_volume(252d longer-term)
volume_price_pos_move_confirmed = True iff stpb_ret_21d > 0 AND vol_ratio_21_252 > 1.2
(stpb_ret_21d carried through into output alongside the flag, so the
price-leg result is visible next to the flag rather than hidden inside it
— a vol_ratio > 1.2 with a negative stpb_ret_21d is a real "high volume on
a decline" case, not a bug.)

NOTE: volume_price_pos_move_confirmed is a one-sided confirmation flag (bullish entries
only). False does not imply bearish — it just means rising-price +
rising-volume agreement was not met. Falling-price/falling-volume cases
are NOT separately characterized here; that is left to Stage 5.

Depends on stpb_ret_21d from metrics/stpb.py (same 21d window, so the
price leg of the confirmation check is internally consistent with the
volume leg).
"""
import pandas as pd


def compute(prices: pd.DataFrame, stpb_result: pd.DataFrame, T, all_dates) -> pd.DataFrame:
    """
    prices      : full prices.parquet
    stpb_result : output of metrics/stpb.compute() — needs symbol, stpb_ret_21d
    T           : robustly-resolved T
    all_dates   : sorted list of trading dates <= T

    Returns DataFrame: symbol, stpb_ret_21d, vol_ratio_21_252, volume_price_pos_move_confirmed
    """
    T_21 = all_dates[-22]
    T_252 = all_dates[-253]

    # 21d window: (T_21, T] -> 21 trading days
    window_21 = prices[(prices["date"] > T_21) & (prices["date"] <= T)]
    avg_vol_21 = window_21.groupby("symbol")["volume"].mean().rename("avg_vol_21").reset_index()

    # 252d window: (T_252, T] -> 252 trading days
    window_252 = prices[(prices["date"] > T_252) & (prices["date"] <= T)]
    avg_vol_252 = window_252.groupby("symbol")["volume"].mean().rename("avg_vol_252").reset_index()

    out = avg_vol_21.merge(avg_vol_252, on="symbol", how="outer")
    out["vol_ratio_21_252"] = out["avg_vol_21"] / out["avg_vol_252"]

    out = out.merge(stpb_result[["symbol", "stpb_ret_21d"]], on="symbol", how="left")
    out["volume_price_pos_move_confirmed"] = (out["stpb_ret_21d"] > 0) & (
        out["vol_ratio_21_252"] > 1.2
    )

    return out[["symbol", "stpb_ret_21d", "vol_ratio_21_252", "volume_price_pos_move_confirmed"]]
