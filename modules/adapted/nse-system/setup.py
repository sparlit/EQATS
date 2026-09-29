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
Hiren Gabani Master Pullback — reads all thresholds from
strategy_config.SETUP. Change values there, not here.

v3.5 (2026-09-12): thresholds migrated to central config.
"""
from dataclasses import dataclass, field
from typing import List

import numpy as np
import pandas as pd
from strategy_config import SETUP as CFG


@dataclass
class Setup:
    symbol: str
    triggered: bool
    signal_date: str
    entry_price: float
    stop_loss: float
    target_price: float
    risk_reward: float
    pullback_depth: float
    pullback_days: int
    mother_bar_high: float
    mother_bar_low: float
    impulse_pct: float
    ema_proximity: str
    shape_score: int = 0
    reasons: list[str] = field(default_factory=list)


class SetupDetector:
    IMPULSE_LOOKBACK = CFG["IMPULSE_LOOKBACK"]
    IMPULSE_MIN_PCT = CFG["IMPULSE_MIN_PCT"]
    IMPULSE_MAX_PCT = CFG["IMPULSE_MAX_PCT"]
    EMA10_BREAK_TOL = CFG["EMA10_BREAK_TOL"]
    PB_LOOKBACK = CFG["PB_LOOKBACK"]
    PB_MIN_PCT = CFG["PB_MIN_PCT"]
    PB_MAX_PCT = CFG["PB_MAX_PCT"]
    PB_MIN_DAYS = CFG["PB_MIN_DAYS"]
    PB_MAX_DAYS = CFG["PB_MAX_DAYS"]
    CRASH_WINDOW = CFG["CRASH_WINDOW"]
    CRASH_MAX_PCT = CFG["CRASH_MAX_PCT"]
    EMA10 = CFG["EMA10"]
    EMA20 = CFG["EMA20"]
    EMA_TOUCH_MULT = CFG["EMA_TOUCH_MULT"]
    VOL_SMA_DAYS = CFG["VOL_SMA_DAYS"]
    TIGHT_ATR_MULT = CFG["TIGHT_ATR_MULT"]
    TIGHT_MAX_RUN_BACK = CFG["TIGHT_MAX_RUN_BACK"]
    TIGHT_MIN = CFG["TIGHT_MIN"]
    MAX_STOP_PCT = CFG["MAX_STOP_PCT"]
    TARGET_R_MULTIPLE = CFG["TARGET_R_MULTIPLE"]
    MAX_SHIFT = CFG["MAX_SHIFT"]

    @classmethod
    def detect(cls, df: pd.DataFrame, symbol: str) -> Setup:
        for shift in range(cls.MAX_SHIFT + 1):
            n = len(df) - shift
            if n < cls.IMPULSE_LOOKBACK + cls.PB_LOOKBACK + 10:
                continue
            res = cls._eval(df.iloc[:n], symbol)
            if res is not None:
                return res
        return Setup(symbol, False, "", 0, 0, 0, 0, 0, 0, 0, 0, "", 0, ["no completed pattern in last 3 sessions"])

    @classmethod
    def _eval(cls, df: pd.DataFrame, symbol: str):
        c = df["Close"].values.astype(float)
        h = df["High"].values.astype(float)
        l = df["Low"].values.astype(float)
        v = df["Volume"].values.astype(float)
        n = len(c)

        ema10 = pd.Series(c).ewm(span=cls.EMA10, adjust=False).mean().values
        ema20 = pd.Series(c).ewm(span=cls.EMA20, adjust=False).mean().values
        vol_sma20 = pd.Series(v).rolling(cls.VOL_SMA_DAYS).mean().values

        trs = []
        for i in range(1, n):
            trs.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
        atr14 = float(np.mean(trs[-14:])) if len(trs) >= 14 else None

        win_end = n - cls.PB_LOOKBACK
        win_start = win_end - cls.IMPULSE_LOOKBACK
        if win_start < 0:
            return None
        seg_h = h[win_start:win_end]
        sh_local = int(np.argmax(seg_h))
        swing_high = float(seg_h[sh_local])
        swing_high_idx = win_start + sh_local
        low_start = max(0, swing_high_idx - 40)
        swing_low_before = float(np.min(l[low_start : swing_high_idx + 1]))
        if swing_low_before <= 0:
            return None
        impulse_pct = (swing_high - swing_low_before) / swing_low_before
        if not (cls.IMPULSE_MIN_PCT <= impulse_pct <= cls.IMPULSE_MAX_PCT):
            return None
        ic = c[swing_high_idx : win_end + 1]
        ie = ema10[swing_high_idx : win_end + 1]
        if int(np.sum(ic < ie)) > max(2, int(cls.EMA10_BREAK_TOL * len(ic))):
            return None

        pb_window = h[win_end:]
        recent_high = float(np.max(pb_window))
        current_low = float(l[-1])
        pb_depth = (recent_high - current_low) / recent_high
        if not (cls.PB_MIN_PCT <= pb_depth <= cls.PB_MAX_PCT):
            return None

        pb_days = len(pb_window) - 1 - int(np.argmax(pb_window))
        if not (cls.PB_MIN_DAYS <= pb_days <= cls.PB_MAX_DAYS):
            return None
        for i in range(-cls.CRASH_WINDOW, 0):
            base = h[i - cls.CRASH_WINDOW + 1]
            if base and (base - l[i]) / base >= cls.CRASH_MAX_PCT:
                return None

        pseg = c[swing_high_idx:]
        shape = 0
        if len(pseg) > 4:
            rts = np.diff(pseg) / np.maximum(pseg[:-1], 1e-9)
            max_drop = float(np.min(rts))
            vol = float(np.std(rts))
            s_drop = max(0.0, min(1.0, 1 - abs(max_drop) / 0.08))
            s_vol = max(0.0, min(1.0, 1 - vol / 0.03))
            shape = int(100 * (0.5 * s_drop + 0.5 * s_vol))

        near10 = abs(current_low - ema10[-1]) / ema10[-1] <= cls.EMA_TOUCH_MULT
        near20 = abs(current_low - ema20[-1]) / ema20[-1] <= cls.EMA_TOUCH_MULT
        in_zone = current_low <= ema10[-1] * 1.02 and current_low >= ema20[-1] * 0.98
        if not (near10 or near20 or in_zone):
            return None
        ema_proximity = "EMA10" if near10 else ("EMA20" if near20 else "ZONE")

        vol_now = vol_sma20[-1]
        avg3 = float(np.mean(v[-3:]))
        if np.isnan(vol_now) or not (avg3 < 0.8 * vol_now or v[-1] < 0.7 * vol_now):
            return None

        def is_tight(i):
            inside = h[i] < h[i - 1] and l[i] > l[i - 1]
            narrow = atr14 is not None and (h[i] - l[i]) <= cls.TIGHT_ATR_MULT * atr14
            return inside or narrow

        inside_last = bool(h[-1] < h[-2] and l[-1] > l[-2])
        tight_run = 0
        i = -1
        while i >= -cls.TIGHT_MAX_RUN_BACK and is_tight(i):
            tight_run += 1
            i -= 1
        if inside_last:
            mother_idx = -2
        elif tight_run >= cls.TIGHT_MIN:
            mother_idx = i
        else:
            return None
        mother_bar_high = float(h[mother_idx])
        mother_bar_low = float(l[mother_idx])

        entry_price = mother_bar_high
        stop_loss = float(l[-1])
        if stop_loss >= entry_price:
            return None
        risk_pct = (entry_price - stop_loss) / entry_price
        if risk_pct > cls.MAX_STOP_PCT:
            return None

        risk = entry_price - stop_loss
        return Setup(
            symbol=symbol,
            triggered=True,
            signal_date=str(df.index[-1].date()),
            entry_price=round(entry_price, 2),
            stop_loss=round(stop_loss, 2),
            target_price=round(entry_price + cls.TARGET_R_MULTIPLE * risk, 2),
            risk_reward=cls.TARGET_R_MULTIPLE,
            pullback_depth=round(pb_depth, 3),
            pullback_days=int(pb_days),
            mother_bar_high=round(mother_bar_high, 2),
            mother_bar_low=round(mother_bar_low, 2),
            impulse_pct=round(impulse_pct, 3),
            ema_proximity=ema_proximity,
            shape_score=shape,
            reasons=["thresholds from strategy_config.SETUP"],
        )
