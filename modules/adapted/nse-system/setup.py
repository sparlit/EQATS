"""
Hiren Gabani Master Pullback — OFFICIAL v3 + shape score.
6-point checklist + mother-candle trigger + PDL stop + 5% rule
+ 3-session recency + pullback orderliness grade (0-100).
"""
from dataclasses import dataclass, field
from typing import List
import numpy as np
import pandas as pd

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
    reasons: List[str] = field(default_factory=list)

class SetupDetector:
    IMPULSE_LOOKBACK = 90
    IMPULSE_MIN_PCT = 0.25
    IMPULSE_MAX_PCT = 0.50
    PB_LOOKBACK = 25
    PB_MIN_PCT = 0.12
    PB_MAX_PCT = 0.20
    PB_MIN_DAYS = 6
    PB_MAX_DAYS = 15
    CRASH_WINDOW = 3
    CRASH_MAX_PCT = 0.15
    EMA10 = 10
    EMA20 = 20
    EMA_TOUCH_MULT = 0.03
    VOL_SMA_DAYS = 20
    TIGHT_ATR_MULT = 0.9
    TIGHT_MAX_RUN_BACK = 4
    TIGHT_MIN = 2
    MAX_STOP_PCT = 0.05
    TARGET_R_MULTIPLE = 2.0
    MAX_SHIFT = 2

    @classmethod
    def detect(cls, df: pd.DataFrame, symbol: str) -> Setup:
        for shift in range(cls.MAX_SHIFT + 1):
            n = len(df) - shift
            if n < cls.IMPULSE_LOOKBACK + cls.PB_LOOKBACK + 10:
                continue
            res = cls._eval(df.iloc[:n], symbol)
            if res is not None:
                return res
        return Setup(symbol, False, "", 0, 0, 0, 0, 0, 0, 0, 0, "",
                     ["no completed pattern in last 3 sessions"])

    @classmethod
    def _eval(cls, df: pd.DataFrame, symbol: str):
        c = df["Close"].values.astype(float)
        h = df["High"].values.astype(float)
        l = df["Low"].values.astype(float)
        v = df["Volume"].values.astype(float)

        ema10 = pd.Series(c).ewm(span=cls.EMA10, adjust=False).mean().values
        ema20 = pd.Series(c).ewm(span=cls.EMA20, adjust=False).mean().values
        vol_sma20 = pd.Series(v).rolling(cls.VOL_SMA_DAYS).mean().values

        trs = []
        for i in range(1, len(c)):
            trs.append(max(h[i] - l[i], abs(h[i] - c[i - 1]),
                           abs(l[i] - c[i - 1])))
        atr14 = float(np.mean(trs[-14:])) if len(trs) >= 14 else None

        # --- 1. Impulse 25-50%, clean above 10 EMA ---
        impulse_end_idx = -cls.PB_LOOKBACK
        seg = h[impulse_end_idx - cls.IMPULSE_LOOKBACK:impulse_end_idx]
        swing_high = float(np.max(seg))
        swing_high_idx = (int(np.argmax(seg)) + impulse_end_idx
                          - cls.IMPULSE_LOOKBACK)
        swing_low_before = float(np.min(
            l[max(0, swing_high_idx - 40):swing_high_idx + 1]))
        impulse_pct = (swing_high - swing_low_before) / swing_low_before
        if not (cls.IMPULSE_MIN_PCT <= impulse_pct <= cls.IMPULSE_MAX_PCT):
            return None
        ic = c[swing_high_idx:impulse_end_idx + 1]
        ie = ema10[swing_high_idx:impulse_end_idx + 1]
        if int(np.sum(ic < ie)) > max(2, int(0.25 * len(ic))):
            return None

        # --- 2. Pullback 12-20% ---
        pb_window = h[impulse_end_idx:]
        recent_high = float(np.max(pb_window))
        current_low = float(l[-1])
        pb_depth = (recent_high - current_low) / recent_high
        if not (cls.PB_MIN_PCT <= pb_depth <= cls.PB_MAX_PCT):
            return None

        # --- 3. Orderly 6-15d, no hard crash ---
        pb_days = len(pb_window) - 1 - int(np.argmax(pb_window))
        if not (cls.PB_MIN_DAYS <= pb_days <= cls.PB_MAX_DAYS):
            return None
        for i in range(-cls.CRASH_WINDOW, 0):
            base = h[i - cls.CRASH_WINDOW + 1]
            if base and (base - l[i]) / base >= cls.CRASH_MAX_PCT:
                return None

        # --- Shape score: orderliness of the pullback (0-100) ---
        pseg = c[swing_high_idx:]
        shape = 0
        if len(pseg) > 4:
            rts = np.diff(pseg) / np.maximum(pseg[:-1], 1e-9)
            max_drop = float(np.min(rts))
            vol = float(np.std(rts))
            s_drop = max(0.0, min(1.0, 1 - abs(max_drop) / 0.08))
            s_vol = max(0.0, min(1.0, 1 - vol / 0.03))
            shape = int(100 * (0.5 * s_drop + 0.5 * s_vol))

        # --- 4. Tighten at 10/20 EMA ---
        near10 = abs(current_low - ema10[-1]) / ema10[-1] <= cls.EMA_TOUCH_MULT
        near20 = abs(current_low - ema20[-1]) / ema20[-1] <= cls.EMA_TOUCH_MULT
        in_zone = (current_low <= ema10[-1] * 1.02 and
                   current_low >= ema20[-1] * 0.98)
        if not (near10 or near20 or in_zone):
            return None
        ema_proximity = "EMA10" if near10 else ("EMA20" if near20
                                                else "ZONE")

        # --- 5. Volume dry-up ---
        vol_now = vol_sma20[-1]
        avg3 = float(np.mean(v[-3:]))
        if np.isnan(vol_now) or not (avg3 < 0.8 * vol_now or
                                     v[-1] < 0.7 * vol_now):
            return None

        # --- 6. Mother candle: tight cluster OR inside bar ---
        def is_tight(i):
            inside = h[i] < h[i - 1] and l[i] > l[i - 1]
            narrow = (atr14 is not None and
                      (h[i] - l[i]) <= cls.TIGHT_ATR_MULT * atr14)
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

        # --- Phase 3: trigger, PDL stop, 5% rule ---
        entry_price = mother_bar_high
        stop_loss = float(l[-1])
        if stop_loss >= entry_price:
            return None
        risk_pct = (entry_price - stop_loss) / entry_price
        if risk_pct > cls.MAX_STOP_PCT:
            return None

        risk = entry_price - stop_loss
        return Setup(
            symbol=symbol, triggered=True,
            signal_date=str(df.index[-1].date()),
            entry_price=round(entry_price, 2),
            stop_loss=round(stop_loss, 2),
            target_price=round(entry_price +
                               cls.TARGET_R_MULTIPLE * risk, 2),
            risk_reward=cls.TARGET_R_MULTIPLE,
            pullback_depth=round(pb_depth, 3),
            pullback_days=int(pb_days),
            mother_bar_high=round(mother_bar_high, 2),
            mother_bar_low=round(mother_bar_low, 2),
            impulse_pct=round(impulse_pct, 3),
            ema_proximity=ema_proximity,
            shape_score=shape,
            reasons=["OFFICIAL v3: pattern within last 3 sessions, "
                     "SL=PDL, risk<=5%"])