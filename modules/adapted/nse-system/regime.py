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
Market Regime Filter — Top-down gatekeeper.
v2 (2026-09-12): 5-level spectrum via regime_spectrum.py.
RegimeState remains backwards-compatible — is_bullish still present.
"""
import datetime as dt
from dataclasses import dataclass

import pandas as pd
import yfinance as yf
from regime_spectrum import ALLOWS_AW, ALLOWS_NORMAL_SWING, SIZE_MULT, classify


@dataclass
class RegimeState:
    # backwards-compatible fields
    is_bullish: bool
    index_close: float
    ema10: float
    symbol: str = ""
    breadth_above_20ema: float = None
    # spectrum additions
    level: str = "NEUTRAL"
    ema20: float = 0.0
    ema10_slope_pct: float = 0.0
    size_mult: float = 1.0
    allows_swing: bool = True
    allows_aw: bool = True


class MarketRegime:
    INDEX_CANDIDATES = ["^CNXSMALLCAP", "^CNXSC", "NIFTY_SMALLCAP_100.NS", "^NSEI"]
    EMA_PERIOD = 10
    EMA20_PERIOD = 20

    @classmethod
    def _fetch(cls, days_back):
        end = dt.date.today()
        start = end - dt.timedelta(days=days_back)
        for sym in cls.INDEX_CANDIDATES:
            try:
                df = yf.Ticker(sym).history(
                    start=start.isoformat(), end=end.isoformat(), auto_adjust=True
                )
                if df is not None and len(df) > 30:
                    return df, sym
            except Exception:
                continue
        return None, None

    @classmethod
    def compute(cls, days_back: int = 120) -> RegimeState:
        df, used = cls._fetch(days_back)
        if df is None:
            raise ValueError("No benchmark data found for any candidate")
        print(f"   benchmark used: {used}")
        df["EMA10"] = df["Close"].ewm(span=cls.EMA_PERIOD, adjust=False).mean()
        df["EMA20"] = df["Close"].ewm(span=cls.EMA20_PERIOD, adjust=False).mean()
        last = df.iloc[-1]
        prev10 = df["EMA10"].iloc[-6] if len(df) > 6 else df["EMA10"].iloc[0]
        slope_pct = ((last["EMA10"] / prev10) - 1) * 100 if prev10 else 0.0
        level = classify(
            close=float(last["Close"]),
            ema10=float(last["EMA10"]),
            ema20=float(last["EMA20"]),
            ema10_slope_pct=slope_pct,
        )
        is_bullish = level in ("STRONG_BULL", "BULL")
        return RegimeState(
            is_bullish=is_bullish,
            index_close=round(float(last["Close"]), 2),
            ema10=round(float(last["EMA10"]), 2),
            ema20=round(float(last["EMA20"]), 2),
            symbol=used,
            level=level,
            ema10_slope_pct=round(slope_pct, 3),
            size_mult=SIZE_MULT.get(level, 1.0),
            allows_swing=ALLOWS_NORMAL_SWING.get(level, True),
            allows_aw=ALLOWS_AW.get(level, True),
        )

    @classmethod
    def check_series(cls, df: pd.DataFrame) -> pd.Series:
        """Boolean Series aligned with df index (for backtest)."""
        ema = df["Close"].ewm(span=cls.EMA_PERIOD, adjust=False).mean()
        return df["Close"] > ema
