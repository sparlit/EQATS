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


"""Sector classification and sector daily aggregates.

Source tables: sector_map, sector_daily (updated by pipeline.sectors)
"""


import pandas as pd
import sqlalchemy as sa
from indian_quant.config.connections import get_engine


def get_sectors(symbol: str | None = None) -> dict | pd.DataFrame | None:
    """Get sector mapping.

    Args:
        symbol: Specific stock. None = all stocks.

    Returns:
        DataFrame with symbol, sector, industry, nse_index.
    """
    engine = get_engine()
    query = "SELECT * FROM sector_map"
    params = {}
    if symbol:
        query += " WHERE symbol = :symbol"
        params["symbol"] = symbol.upper()

    df = pd.read_sql(sa.text(query), engine, params=params)
    if symbol and df.empty:
        return None
    if symbol and len(df) == 1:
        return df.iloc[0].to_dict()
    return df


def get_sector_daily(sector: str | None = None, date: str | None = None) -> pd.DataFrame:
    """Get sector daily aggregates (avg return, avg deliv_z, stock count).

    Args:
        sector: Specific sector (e.g., "Banking"). None = all sectors.
        date: Specific date (YYYY-MM-DD). None = all dates.

    Returns:
        DataFrame with sector, trade_date, avg_return, avg_deliv_z, stock_count.
    """
    engine = get_engine()
    query = "SELECT * FROM sector_daily WHERE 1=1"
    params = {}
    if sector:
        query += " AND sector = :sector"
        params["sector"] = sector
    if date:
        query += " AND trade_date = :date"
        params["date"] = date
    query += " ORDER BY trade_date DESC, sector"

    return pd.read_sql(sa.text(query), engine, params=params)
