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


"""Portfolio and per-stock risk metrics.

Source tables: portfolio_risk, stock_risk (updated by pipeline.risk)
"""


import pandas as pd
import sqlalchemy as sa
from indian_quant.config.connections import get_engine


def get_portfolio_risk() -> dict | None:
    """Get latest portfolio-level risk metrics.

    Returns dict with:
        snapshot_date, total_value, var_95, var_99, cvar_95,
        portfolio_beta, max_drawdown, sharpe_ratio, concentration_hhi,
        n_positions, n_sectors, top_sector_pct
    """
    engine = get_engine()
    result = engine.execute(sa.text("SELECT * FROM portfolio_risk ORDER BY snapshot_date DESC LIMIT 1"))
    row = result.mappings().first()
    return dict(row) if row else None


def get_stock_risk(symbol: str | None = None) -> dict | pd.DataFrame | None:
    """Get per-stock risk metrics.

    Args:
        symbol: Specific stock. None = all stocks.

    Returns:
        DataFrame with symbol, beta, vol_30d, vol_annual, var_95,
        max_drawdown_1y, correlation_nifty, avg_daily_volume, impact_cost.
    """
    engine = get_engine()
    query = "SELECT * FROM stock_risk"
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
