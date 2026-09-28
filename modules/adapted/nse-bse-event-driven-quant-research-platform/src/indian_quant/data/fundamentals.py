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


"""Fundamental data access — PE, ROE, debt ratios, company profiles.

Source tables: key_ratios, company_profile (updated by pipeline.fundamentals)
"""


import pandas as pd
import sqlalchemy as sa

from indian_quant.config.connections import get_engine


def get_fundamentals(symbol: str | None = None) -> dict | pd.DataFrame:
    """Get fundamental data from PostgreSQL.

    Args:
        symbol: Specific stock (e.g., "RELIANCE"). None = all stocks.

    Returns:
        dict for single symbol, DataFrame for all.
    """
    engine = get_engine()
    query = "SELECT * FROM key_ratios"
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


def get_company_profile(symbol: str | None = None) -> dict | pd.DataFrame | None:
    """Get company name, sector, industry, description.

    Args:
        symbol: Specific stock. None = all stocks.

    Returns:
        dict for single symbol, DataFrame for all, None if not found.
    """
    engine = get_engine()
    query = "SELECT * FROM company_profile"
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


def get_market_cap(symbol: str | None = None) -> dict | pd.DataFrame | None:
    """Get market cap data from key_ratios.

    Args:
        symbol: Specific stock. None = all stocks.

    Returns:
        dict with symbol, market_cap, pe_trailing, etc.
    """
    engine = get_engine()
    query = "SELECT symbol, market_cap, pe_trailing, price_to_book FROM key_ratios WHERE market_cap IS NOT NULL"
    params = {}
    if symbol:
        query += " AND symbol = :symbol"
        params["symbol"] = symbol.upper()
    query += " ORDER BY market_cap DESC"

    df = pd.read_sql(sa.text(query), engine, params=params)
    if symbol and df.empty:
        return None
    if symbol and len(df) == 1:
        return df.iloc[0].to_dict()
    return df
