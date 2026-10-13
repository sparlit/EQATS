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


"""Canonical feature definitions shared by ML training and prediction.

Keep these calculations in one place: a score produced by the batch and
deep-dive paths must mean the same thing as a score produced during training.
"""
import numpy as np
import pandas as pd

MOMENTUM_OFFSETS = {"ret_1m": 21, "ret_3m": 63, "ret_6m": 126, "ret_12m": 252}
FEATURE_COLUMNS = [
    "ret_1m",
    "ret_3m",
    "ret_6m",
    "ret_12m",
    "vol_3m",
    "dist_high",
    "dist_low",
    "above_ma50",
    "above_ma200",
]
VOLATILITY_WINDOW = 63


def feature_frame(group):
    """Return legacy ML features with the exact canonical definitions."""
    g = group.sort_values("date").copy()
    c = pd.to_numeric(g["close"], errors="coerce")
    for name, offset in MOMENTUM_OFFSETS.items():
        g[name] = c / c.shift(offset) - 1.0
    # Volatility is the rolling standard deviation of log returns, not the
    # standard deviation of simple returns.
    g["vol_3m"] = np.log(c).diff().rolling(VOLATILITY_WINDOW).std()
    g["dist_high"] = c / c.rolling(252).max()
    g["dist_low"] = c / c.rolling(252).min()
    g["ma50"] = c.rolling(50).mean()
    g["ma200"] = c.rolling(200).mean()
    g["above_ma50"] = (c > g["ma50"]).astype(int)
    g["above_ma200"] = (c > g["ma200"]).astype(int)
    return g


def latest_features(closes):
    """Build one prediction row from chronological close values."""
    c = np.asarray(closes, dtype=float)
    if len(c) < 252:
        return None
    # Use the frame implementation so training and inference cannot drift.
    dates = pd.date_range("2000-01-01", periods=len(c), freq="D")
    row = feature_frame(pd.DataFrame({"date": dates, "close": c})).iloc[-1]
    values = row[FEATURE_COLUMNS].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        return None
    return values.tolist()
