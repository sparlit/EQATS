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
Only allows new long entries when benchmark close > EMA(close, 10).
Tries smallcap indices first; falls back to Nifty 50.
"""
from dataclasses import dataclass

import pandas as pd
import yfinance as yf


@dataclass
class RegimeState:
    is_bullish: bool
    index_close: float
    ema10: float
    symbol: str = ""
    breadth_above_20ema: float = None


class MarketRegime:
    INDEX_CANDIDATES = ["^CNXSMALLCAP", "^CNXSC", "NIFTY_SMALLCAP_100.NS", "^NSEI"]
    EMA_PERIOD = 10

    @classmethod
    def _fetch(cls, days_back):
        for sym in cls.INDEX_CANDIDATES:
            try:
                df = yf.Ticker(sym).history(period=f"{days_back}d", auto_adjust=True)
                if df is not None and len(df) > 30:
                    return df, sym
            except Exception:
                continue
        return None, None

    @classmethod
    def compute(cls, days_back: int = 120) -> RegimeState:
        df, used = cls._fetch(days_back)
        if df is None:
            msg = "No benchmark data found for any candidate"
            raise ValueError(msg)
        print(f"   benchmark used: {used}")
        df["EMA10"] = df["Close"].ewm(span=cls.EMA_PERIOD, adjust=False).mean()
        last = df.iloc[-1]
        is_bullish = bool(last["Close"] > last["EMA10"])
        return RegimeState(
            is_bullish=is_bullish,
            index_close=round(float(last["Close"]), 2),
            ema10=round(float(last["EMA10"]), 2),
            symbol=used,
        )

    @classmethod
    def check_series(cls, df: pd.DataFrame) -> pd.Series:
        """Boolean Series aligned with df index (for backtest)."""
        ema = df["Close"].ewm(span=cls.EMA_PERIOD, adjust=False).mean()
        return df["Close"] > ema
