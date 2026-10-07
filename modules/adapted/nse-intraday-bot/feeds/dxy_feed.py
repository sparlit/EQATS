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
US Dollar Index (DXY) feed via yfinance.
Symbol: DX-Y.NYB  (NYSE Arca Dollar Index)
Used by Gold strategy for inverse-correlation confirmation.
"""
import pandas as pd
import yfinance as yf

SYMBOL = "DX-Y.NYB"


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower().strip() for c in df.columns]
    return df[~df.index.duplicated(keep="last")].dropna()


def get_dxy_data() -> dict:
    """
    Returns DXY bias: bullish / bearish based on EMA stack.
    Gold LONG requires DXY bearish; Gold SHORT requires DXY bullish.
    """
    try:
        df = _clean(
            yf.download(SYMBOL, period="10d", interval="1h", progress=False, auto_adjust=True)
        )
        if df.empty or len(df) < 22:
            return _neutral()

        close = df["close"].astype(float)
        ema9 = float(close.ewm(span=9, adjust=False).mean().iloc[-1])
        ema21 = float(close.ewm(span=21, adjust=False).mean().iloc[-1])
        last_c = float(close.iloc[-1])

        bullish = last_c > ema9 > ema21
        bearish = last_c < ema9 < ema21

        return {
            "close": round(last_c, 3),
            "ema9": round(ema9, 3),
            "ema21": round(ema21, 3),
            "bullish": bullish,
            "bearish": bearish,
            "error": None,
        }
    except Exception as e:
        return {**_neutral(), "error": str(e)}


def _neutral() -> dict:
    return {
        "close": None,
        "ema9": None,
        "ema21": None,
        "bullish": False,
        "bearish": False,
        "error": None,
    }
