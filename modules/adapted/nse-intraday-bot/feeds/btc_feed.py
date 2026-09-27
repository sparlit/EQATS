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
Bitcoin (BTCUSDT) data feed via yfinance.
Symbol: BTC-USD  (available 24/7, no auth needed)
"""
import pandas as pd
import yfinance as yf

SYMBOL = "BTC-USD"


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


def get_btc_data() -> dict:
    """Download Weekly / 4H / 1H / 15min DataFrames for BTC."""
    df_1h = _clean(yf.download(SYMBOL, period="30d", interval="1h", progress=False, auto_adjust=True))
    df_15m = _clean(yf.download(SYMBOL, period="7d", interval="15m", progress=False, auto_adjust=True))
    df_weekly = _clean(yf.download(SYMBOL, period="1y", interval="1wk", progress=False, auto_adjust=True))
    df_4h = _resample_4h(df_1h)

    price = float(df_15m["close"].iloc[-1]) if not df_15m.empty else None
    return {
        "df_weekly": df_weekly,
        "df_4h": df_4h,
        "df_1h": df_1h,
        "df_15m": df_15m,
        "price": price,
    }


def get_prev_day_high_low() -> tuple:
    try:
        df = _clean(yf.download(SYMBOL, period="5d", interval="1d", progress=False, auto_adjust=True))
        if len(df) < 2:
            return None, None
        prev = df.iloc[-2]
        return float(prev["high"]), float(prev["low"])
    except Exception:
        return None, None


def get_cme_gap() -> dict:
    """
    Approximate CME Bitcoin futures gap by scanning daily BTC-USD candles
    for gaps > 0.5% between consecutive closes/opens (Mon open vs Fri close).
    CME gaps fill ~95% of the time — an unfilled gap below is a price magnet.
    """
    try:
        df = _clean(yf.download(SYMBOL, period="30d", interval="1d", progress=False, auto_adjust=True))
        if df.empty or len(df) < 4:
            return {"nearest_gap_below": None, "nearest_gap_above": None}

        price = float(df["close"].iloc[-1])
        gaps_below = []
        gaps_above = []

        for i in range(len(df) - 2, max(0, len(df) - 20), -1):
            prev_c = float(df["close"].iloc[i])
            next_o = float(df["open"].iloc[i + 1])
            gap_pct = abs(next_o - prev_c) / prev_c
            if gap_pct > 0.005:  # > 0.5 % is a meaningful gap
                mid = (prev_c + next_o) / 2
                (gaps_below if mid < price else gaps_above).append(mid)

        return {
            "nearest_gap_below": round(max(gaps_below), 2) if gaps_below else None,
            "nearest_gap_above": round(min(gaps_above), 2) if gaps_above else None,
        }
    except Exception:
        return {"nearest_gap_below": None, "nearest_gap_above": None}
