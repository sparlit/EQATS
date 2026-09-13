from __future__ import annotations

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


"""Point-in-time feature calculation over the shared Old NSE price history."""

import numpy as np
import pandas as pd


def _rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gains = delta.clip(lower=0).ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    losses = (-delta.clip(upper=0)).ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    return 100 - (100 / (1 + gains / losses.replace(0, np.nan)))


def _atr(frame: pd.DataFrame, length: int = 14) -> pd.Series:
    prev_close = frame["close"].shift(1)
    ranges = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - prev_close).abs(),
            (frame["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1).ewm(alpha=1 / length, adjust=False, min_periods=length).mean()


def _adx(frame: pd.DataFrame, length: int = 14) -> pd.Series:
    up = frame["high"].diff()
    down = -frame["low"].diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    atr = _atr(frame, length)
    plus_di = 100 * plus_dm.ewm(alpha=1 / length, adjust=False, min_periods=length).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / length, adjust=False, min_periods=length).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()


def latest_features(prices: pd.DataFrame) -> pd.DataFrame:
    """Build one latest, no-look-ahead feature row per eligible symbol.

    All rolling extrema used for a trigger exclude the current session, which
    prevents a same-candle breakout from comparing against itself.
    """
    rows: list[dict[str, object]] = []
    required = {"symbol", "trade_date", "open", "high", "low", "close", "volume"}
    if not required.issubset(prices.columns):
        return pd.DataFrame()
    for symbol, raw in prices.groupby("symbol", sort=True):
        frame = raw.sort_values("trade_date").copy()
        if len(frame) < 2:
            continue
        for column in ("open", "high", "low", "close", "volume", "delivery_pct", "turnover_lacs"):
            if column in frame:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
        close = frame["close"]
        volume = frame["volume"]
        last = frame.iloc[-1]
        sma20 = close.rolling(20, min_periods=20).mean()
        sma50 = close.rolling(50, min_periods=50).mean()
        sma150 = close.rolling(150, min_periods=150).mean()
        sma200 = close.rolling(200, min_periods=200).mean()
        ema20 = close.ewm(span=20, adjust=False, min_periods=20).mean()
        prior_20_high = frame["high"].shift(1).rolling(20, min_periods=20).max()
        prior_10_low = frame["low"].shift(1).rolling(10, min_periods=10).min()
        prior_126_high = frame["high"].shift(1).rolling(126, min_periods=126).max()
        prior_252_high = frame["high"].shift(1).rolling(252, min_periods=252).max()
        prior_252_low = frame["low"].shift(1).rolling(252, min_periods=252).min()
        atr = _atr(frame)
        bb_mid = close.rolling(20, min_periods=20).mean()
        bb_width = 4 * close.rolling(20, min_periods=20).std() / bb_mid
        delivery = frame.get("delivery_pct", pd.Series(np.nan, index=frame.index))
        data = {
            "symbol": str(symbol),
            "as_of_date": pd.Timestamp(last["trade_date"]).date().isoformat(),
            "history_sessions": len(frame),
            "close": float(last["close"]),
            "high": float(last["high"]),
            "low": float(last["low"]),
            "volume": float(last["volume"]),
            "sma20": sma20.iloc[-1],
            "ema20": ema20.iloc[-1],
            "sma50": sma50.iloc[-1],
            "sma150": sma150.iloc[-1],
            "sma200": sma200.iloc[-1],
            "sma200_20d_ago": sma200.iloc[-21] if len(frame) >= 220 else np.nan,
            "volume_sma20": volume.rolling(20, min_periods=20).mean().iloc[-1],
            "volume_sma50": volume.rolling(50, min_periods=50).mean().iloc[-1],
            "rsi14": _rsi(close).iloc[-1],
            "atr": atr.iloc[-1],
            "atr_pct": (atr.iloc[-1] / last["close"]) * 100,
            "adx14": _adx(frame).iloc[-1],
            "bb_width": bb_width.iloc[-1],
            "bb_width_change": bb_width.pct_change(5).iloc[-1],
            "return_1m": close.iloc[-1] / close.iloc[-23] - 1 if len(frame) >= 23 else np.nan,
            "return_3m": close.iloc[-1] / close.iloc[-64] - 1 if len(frame) >= 64 else np.nan,
            "return_6m": close.iloc[-1] / close.iloc[-127] - 1 if len(frame) >= 127 else np.nan,
            "return_12m": close.iloc[-1] / close.iloc[-253] - 1 if len(frame) >= 253 else np.nan,
            "previous_20d_high": prior_20_high.iloc[-1],
            "previous_10d_low": prior_10_low.iloc[-1],
            "previous_126d_high": prior_126_high.iloc[-1],
            "previous_252d_high": prior_252_high.iloc[-1],
            "previous_252d_low": prior_252_low.iloc[-1],
            "delivery_pct": delivery.iloc[-1],
            "delivery_median60": delivery.rolling(60, min_periods=20).median().iloc[-1],
            "turnover_lacs": frame.get("turnover_lacs", pd.Series(np.nan, index=frame.index)).iloc[-1],
        }
        rows.append(data)
    return pd.DataFrame(rows)
