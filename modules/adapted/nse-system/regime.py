"""
Market Regime Filter — Top-down gatekeeper.
Only allows new long entries when benchmark close > EMA(close, 10).
Tries smallcap indices first; falls back to Nifty 50.
"""
from dataclasses import dataclass
import yfinance as yf
import pandas as pd

@dataclass
class RegimeState:
    is_bullish: bool
    index_close: float
    ema10: float
    symbol: str = ""
    breadth_above_20ema: float = None

class MarketRegime:
    INDEX_CANDIDATES = ["^CNXSMALLCAP", "^CNXSC",
                        "NIFTY_SMALLCAP_100.NS", "^NSEI"]
    EMA_PERIOD = 10

    @classmethod
    def _fetch(cls, days_back):
        for sym in cls.INDEX_CANDIDATES:
            try:
                df = yf.Ticker(sym).history(
                    period=f"{days_back}d", auto_adjust=True)
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
        df["EMA10"] = df["Close"].ewm(span=cls.EMA_PERIOD,
                                      adjust=False).mean()
        last = df.iloc[-1]
        is_bullish = bool(last["Close"] > last["EMA10"])
        return RegimeState(is_bullish=is_bullish,
                           index_close=round(float(last["Close"]), 2),
                           ema10=round(float(last["EMA10"]), 2),
                           symbol=used)

    @classmethod
    def check_series(cls, df: pd.DataFrame) -> pd.Series:
        """Boolean Series aligned with df index (for backtest)."""
        ema = df["Close"].ewm(span=cls.EMA_PERIOD, adjust=False).mean()
        return df["Close"] > ema