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


"""Institutional flow data — FII/DII, shareholding, bulk deals, insider trades.

Source tables: fii_dii_daily, shareholding_history, bulk_deals,
               insider_trades, promoter_pledge
               (updated by pipeline.institutional)
"""


import pandas as pd
import sqlalchemy as sa

from indian_quant.config.connections import get_engine


def get_fii_dii(date: str | None = None) -> pd.DataFrame:
    """Get FII/DII daily flow data.

    Args:
        date: Specific date (YYYY-MM-DD). None = all dates.

    Returns:
        DataFrame with trade_date, fii_buy, fii_sell, fii_net, dii_buy, etc.
    """
    engine = get_engine()
    query = "SELECT * FROM fii_dii_daily"
    params = {}
    if date:
        query += " WHERE trade_date = :date"
        params["date"] = date
    query += " ORDER BY trade_date DESC"

    return pd.read_sql(sa.text(query), engine, params=params)


def get_shareholding(symbol: str | None = None) -> dict | pd.DataFrame | None:
    """Get shareholding pattern (promoter, FII, DII, public).

    Args:
        symbol: Specific stock. None = all stocks.

    Returns:
        DataFrame with symbol, quarter, promoter_pct, fii_pct, dii_pct, public_pct.
    """
    engine = get_engine()
    query = "SELECT * FROM shareholding_history"
    params = {}
    if symbol:
        query += " WHERE symbol = :symbol"
        params["symbol"] = symbol.upper()
    query += " ORDER BY symbol, quarter DESC"

    df = pd.read_sql(sa.text(query), engine, params=params)
    if symbol and df.empty:
        return None
    if symbol and len(df) == 1:
        return df.iloc[0].to_dict()
    return df


def get_bulk_deals(date: str | None = None) -> pd.DataFrame:
    """Get bulk deal transactions.

    Args:
        date: Specific date (YYYY-MM-DD). None = all dates.

    Returns:
        DataFrame with deal_date, symbol, client, deal_type, quantity, price, value.
    """
    engine = get_engine()
    query = "SELECT * FROM bulk_deals"
    params = {}
    if date:
        query += " WHERE deal_date = :date"
        params["date"] = date
    query += " ORDER BY deal_date DESC, symbol"

    return pd.read_sql(sa.text(query), engine, params=params)


def get_insider_trades(symbol: str | None = None) -> pd.DataFrame:
    """Get insider trading activity.

    Args:
        symbol: Specific stock. None = all stocks.

    Returns:
        DataFrame with symbol, trade_date, insider_name, transaction_type, shares_traded.
    """
    engine = get_engine()
    query = "SELECT * FROM insider_trades"
    params = {}
    if symbol:
        query += " WHERE symbol = :symbol"
        params["symbol"] = symbol.upper()
    query += " ORDER BY trade_date DESC"

    return pd.read_sql(sa.text(query), engine, params=params)


def get_promoter_pledge(symbol: str | None = None) -> dict | pd.DataFrame | None:
    """Get promoter pledge data.

    Args:
        symbol: Specific stock. None = all stocks.

    Returns:
        DataFrame with symbol, pledge_pct, risk_signal, qoq_change.
    """
    engine = get_engine()
    query = "SELECT * FROM promoter_pledge"
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
