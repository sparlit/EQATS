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
Screener v2 — official Phase 1.
Stage-2 baseline + liquidity + >=1 momentum trigger + impulse volume proof.
IPOs (<200 sessions) routed to a separate watchlist, never rejected.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class ScreenerResult:
    symbol: str
    passed: bool
    close: float
    ema200: float
    ema200_rising: bool
    mom_1m: float
    mom_3m: float
    near_52wk_high: bool
    volume_explosive: bool
    ipo_watch: bool = False
    reason: str = ""


class Screener:
    EMA200 = 200
    MIN_HISTORY = 220
    MOM_1M_MIN = 0.20
    MOM_3M_MIN = 0.30
    HIGH_52WK_MIN_RATIO = 0.75
    VOL_EXPLOSION_MULT = 2.5
    VOL_LOOKBACK = 60
    LIQ_DAYS = 20
    MIN_AVG_TURNOVER = 2e7  # ₹2 cr average daily turnover

    @classmethod
    def evaluate(cls, df: pd.DataFrame, symbol: str) -> ScreenerResult:
        if len(df) < cls.MIN_HISTORY:
            return ScreenerResult(
                symbol, False, None, None, False, 0, 0, False, False, True, "IPO watchlist (<200 sessions, manual)"
            )
        if len(df) < max(cls.EMA200, 252) + 20:
            return ScreenerResult(symbol, False, None, None, False, 0, 0, False, False, False, "insufficient history")
        c = df["Close"].values
        h = df["High"].values
        v = df["Volume"].values

        ema200 = pd.Series(c).ewm(span=cls.EMA200, adjust=False).mean().values
        close = c[-1]
        mandatory = (close > ema200[-1]) and (ema200[-1] > ema200[-21])

        avg_vol20 = float(np.mean(v[-cls.LIQ_DAYS :]))
        liquid = (avg_vol20 * close) >= cls.MIN_AVG_TURNOVER

        mom_1m = (c[-1] - c[-22]) / c[-22]
        mom_3m = (c[-1] - c[-64]) / c[-64]
        near = close >= cls.HIGH_52WK_MIN_RATIO * np.max(h[-252:])
        momentum_hit = mom_1m >= cls.MOM_1M_MIN or mom_3m >= cls.MOM_3M_MIN or near

        vol_sma = pd.Series(v).rolling(50).mean().values
        vol_ok = any(
            (not np.isnan(vol_sma[i])) and v[i] > cls.VOL_EXPLOSION_MULT * vol_sma[i]
            for i in range(-cls.VOL_LOOKBACK, 0)
        )

        passed = mandatory and liquid and momentum_hit and vol_ok
        if passed:
            reason = "PASS"
        else:
            bad = []
            if not mandatory:
                bad.append("not Stage-2")
            if not liquid:
                bad.append("low liquidity")
            if not momentum_hit:
                bad.append("no momentum trigger")
            if not vol_ok:
                bad.append("no volume explosion")
            reason = "; ".join(bad)

        return ScreenerResult(
            symbol=symbol,
            passed=passed,
            close=round(float(close), 2),
            ema200=round(float(ema200[-1]), 2),
            ema200_rising=bool(ema200[-1] > ema200[-21]),
            mom_1m=round(float(mom_1m), 3),
            mom_3m=round(float(mom_3m), 3),
            near_52wk_high=bool(near),
            volume_explosive=bool(vol_ok),
            ipo_watch=False,
            reason=reason,
        )
