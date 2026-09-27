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


"""OHLCV bar data from parquet files.

Source: data/normalized/bars_1d/{exchange}/{symbol}.parquet
        data/normalized/delivery/{exchange}/{symbol}.parquet
"""


from pathlib import Path

import pandas as pd

_DATA_ROOT = Path(__file__).resolve().parents[4] / "data" / "normalized"


def get_bars(
    symbol: str,
    exchange: str = "NSE",
    timeframe: str = "1d",
    days: int | None = None,
) -> pd.DataFrame:
    """Get historical bars from normalized parquet.

    Args:
        symbol: Stock symbol (e.g., "RELIANCE").
        exchange: "NSE" or "BSE".
        timeframe: "1d", "5m", "15m", etc.
        days: Last N days. None = all available.

    Returns:
        DataFrame with date, open, high, low, close, volume.
    """
    path = _DATA_ROOT / "bars_1d" / exchange / f"{symbol.upper()}.parquet"
    if not path.exists():
        msg = f"No bar data for {symbol} on {exchange}: {path}"
        raise FileNotFoundError(msg)

    df = pd.read_parquet(path)
    if days and len(df) > days:
        df = df.tail(days)
    return df


def get_delivery(symbol: str, exchange: str = "NSE") -> pd.DataFrame:
    """Get delivery data from normalized parquet.

    Args:
        symbol: Stock symbol.
        exchange: "NSE" or "BSE".

    Returns:
        DataFrame with date, close, volume, deliv_qty, deliv_pct, etc.
    """
    path = _DATA_ROOT / "delivery" / exchange / f"{symbol.upper()}.parquet"
    if not path.exists():
        msg = f"No delivery data for {symbol} on {exchange}: {path}"
        raise FileNotFoundError(msg)

    return pd.read_parquet(path)
