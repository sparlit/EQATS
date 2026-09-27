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


"""Causal daily features shared in formula with the selected research profile."""
import numpy as np
import pandas as pd
from old_nse_hull.multi_horizon.features import _adx, _atr, _rsi


def feature_history(frame, calendar, action_dates=()):
    """Vectorized native formulas, verified against latest_features on prefixes."""
    d = frame.sort_values("trade_date").reset_index(drop=True).copy()
    c, v = d.close, d.volume
    f = d[["symbol", "open", "high", "low", "close", "volume"]].copy()
    f["as_of_date"] = d.trade_date
    f["history_sessions"] = np.arange(1, len(d) + 1)
    for n in [20, 50, 150, 200]:
        f[f"sma{n}"] = c.rolling(n).mean()
    f["ema20"] = c.ewm(span=20, adjust=False, min_periods=20).mean()
    f["sma200_20d_ago"] = f.sma200.shift(20)
    for n in [20, 50]:
        f[f"volume_sma{n}"] = v.rolling(n).mean()
    f["rsi14"] = _rsi(c)
    f["atr"] = _atr(d)
    f["atr_pct"] = f.atr / c * 100
    f["adx14"] = _adx(d)
    f["bb_width"] = 4 * c.rolling(20).std() / f.sma20
    f["bb_width_change"] = f.bb_width.pct_change(5)
    for label, n in [("1m", 22), ("3m", 63), ("6m", 126), ("12m", 252)]:
        f[f"return_{label}"] = c / c.shift(n) - 1
    for n in [20, 126, 252]:
        f[f"previous_{n}d_high"] = d.high.shift(1).rolling(n).max()
    for n in [10, 252]:
        f[f"previous_{n}d_low"] = d.low.shift(1).rolling(n).min()
    delivery = d.get("delivery_pct", pd.Series(np.nan, index=d.index))
    f["delivery_pct"] = delivery
    f["delivery_median60"] = delivery.rolling(60, min_periods=20).median()
    f["turnover_lacs"] = d.get("turnover_lacs", pd.Series(np.nan, index=d.index))
    f["prior_close"] = c.shift(1)
    f["gap_pct"] = (d.open / f.prior_close - 1) * 100
    f["session_index"] = d.trade_date.map({day: i for i, day in enumerate(calendar)})
    f["continuous_320"] = f.session_index.sub(f.session_index.shift(319)).eq(319)
    values = d[["open", "high", "low", "close", "volume"]]
    valid = (
        np.isfinite(values).all(axis=1)
        & d.low.gt(0)
        & v.ge(0)
        & d.low.le(d[["open", "close"]].min(axis=1))
        & d.high.ge(d[["open", "close"]].max(axis=1))
    )
    action_gap = f.gap_pct.abs().gt(25)
    for action_day in action_dates:
        positions = np.flatnonzero(d.trade_date.ge(action_day).to_numpy())
        if len(positions):
            action_gap.iloc[positions[0]] = True
    # Gaps/invalid bars known by each date only; future events do not veto earlier entries.
    f["quality_window_ok"] = f.continuous_320 & ((~valid) | action_gap).rolling(320, min_periods=320).sum().eq(0)
    f["action_review_now"] = action_gap | ~valid
    return f


def latest_context(prices):
    prices = prices.copy()
    prices["trade_date"] = pd.to_datetime(prices.trade_date).dt.strftime("%Y-%m-%d")
    calendar = sorted(prices.trade_date.unique())
    day = calendar[-1]
    rows = []
    for _symbol, frame in prices.groupby("symbol", sort=True):
        frame = frame.sort_values("trade_date").reset_index(drop=True)
        if frame.trade_date.iloc[-1] != day:
            continue
        f = feature_history(frame, calendar)
        fast = frame.close.ewm(span=14, adjust=False, min_periods=14).mean()
        slow = frame.close.ewm(span=21, adjust=False, min_periods=21).mean()
        cross = fast.gt(slow) & fast.shift(1).le(slow.shift(1))
        r = f.iloc[-1].to_dict()
        r["recent_cross"] = bool(cross.tail(5).any() and fast.iloc[-1] > slow.iloc[-1])
        r["prior_trend"] = bool(
            len(frame) > 1
            and len(calendar) > 1
            and frame.trade_date.iloc[-2] == calendar[-2]
            and fast.iloc[-2] > slow.iloc[-2]
        )
        rows.append(r)
    return pd.DataFrame(rows), calendar
