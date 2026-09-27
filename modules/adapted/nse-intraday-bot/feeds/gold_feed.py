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
Gold (XAUUSD) data feed via yfinance.
Symbol: GC=F  (CMX Gold Futures continuous contract)
"""
import datetime

import pandas as pd
import yfinance as yf

SYMBOL = "GC=F"


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower().strip() for c in df.columns]
    df = df[~df.index.duplicated(keep="last")].dropna()
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_convert("Asia/Kolkata")
    else:
        df.index = df.index.tz_localize("UTC").tz_convert("Asia/Kolkata")
    df.index = df.index.tz_localize(None)
    return df


def _resample_4h(df_1h: pd.DataFrame) -> pd.DataFrame:
    if df_1h.empty:
        return pd.DataFrame()
    return (
        df_1h.resample("4h")
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        .dropna()
    )


def get_gold_data() -> dict:
    """Download and return 4H / 1H / 15min DataFrames for Gold."""
    df_1h = _clean(yf.download(SYMBOL, period="30d", interval="1h", progress=False, auto_adjust=True))
    df_15m = _clean(yf.download(SYMBOL, period="7d", interval="15m", progress=False, auto_adjust=True))
    df_4h = _resample_4h(df_1h)

    price = float(df_15m["close"].iloc[-1]) if not df_15m.empty else None
    return {
        "df_4h": df_4h,
        "df_1h": df_1h,
        "df_15m": df_15m,
        "price": price,
    }


def get_prev_day_high_low() -> tuple:
    """Previous-day high / low for PDH/PDL reference."""
    try:
        df = _clean(yf.download(SYMBOL, period="5d", interval="1d", progress=False, auto_adjust=True))
        if len(df) < 2:
            return None, None
        prev = df.iloc[-2]
        return float(prev["high"]), float(prev["low"])
    except Exception:
        return None, None


def get_asian_session_range(df_1h: pd.DataFrame) -> dict:
    """
    Asian session (00:00–05:29 IST) price range.
    This becomes London session S/R reference for Gold.
    """
    if df_1h.empty:
        return {"high": None, "low": None}
    dates = sorted(set(df_1h.index.date), reverse=True)
    for d in dates:
        day = df_1h[df_1h.index.date == d]
        asian = day.between_time("00:00", "05:29")
        if not asian.empty:
            return {
                "high": round(float(asian["high"].max()), 2),
                "low": round(float(asian["low"].min()), 2),
            }
    return {"high": None, "low": None}


def get_daily_data() -> pd.DataFrame:
    """
    Download daily OHLCV for Gold (GC=F) — last 60 trading days.
    Used by gold_strategy for HTF bias detection (PDH/PDL, daily BOS/CHOCH).
    Returns DataFrame indexed in IST with lowercase columns.
    """
    try:
        return _clean(yf.download(SYMBOL, period="270d", interval="1d", progress=False, auto_adjust=True))
    except Exception as e:
        print(f"[GOLD FEED] get_daily_data error: {e}")
        return pd.DataFrame()


def get_m5_data() -> pd.DataFrame:
    """
    Download 5-minute OHLCV for Gold (GC=F) — last 2 days.
    Used by gold_strategy for M5 confirmation entry (refined entry candle).
    Returns DataFrame indexed in IST with lowercase columns.
    """
    try:
        return _clean(yf.download(SYMBOL, period="2d", interval="5m", progress=False, auto_adjust=True))
    except Exception as e:
        print(f"[GOLD FEED] get_m5_data error: {e}")
        return pd.DataFrame()
