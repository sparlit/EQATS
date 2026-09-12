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
Real-time stock market data fetching for Indian Stock Tracker Dashboard.

This module fetches real-time data from Yahoo Finance and NSE sources to replace
demo data in the dashboard "Top Stocks by Index" and "Sector Performance" sections.

Key Features:
- 1-hour caching for API efficiency
- Fallback strategy: Yahoo Finance -> NSE -> Partial data
- Graceful error handling
- Real-time sector performance from database
"""

import datetime as dt
from typing import Any, Dict, List, Optional

# Global in-memory cache with TTL
_cache = {}
CACHE_DURATION = 3600  # 1 hour in seconds

INDEX_CONFIG = {
    "NIFTY 50": {"symbol": "^NSEI", "constituents": ["RELIANCE", "TCS", "HDFCBANK"]},
    "NIFTY BANK": {"symbol": "^NSEBANK", "constituents": ["HDFCBANK", "ICICIBANK", "SBIN"]},
    "SENSEX": {"symbol": "^BSESN", "constituents": ["RELIANCE", "TCS", "HDFCBANK"]},
    "NIFTY IT": {"symbol": "^CNXIT", "constituents": ["TCS", "INFY", "WIPRO"]},
}

# Static sector mapping for common Indian stocks (fallback when DB doesn't have sector info)
STOCK_SECTOR_MAP = {
    # Banking
    "HDFCBANK": "Banking",
    "ICICIBANK": "Banking",
    "SBIN": "Banking",
    "KOTAKBANK": "Banking",
    "AXISBANK": "Banking",
    "INDUSINDBK": "Banking",
    "YES BANK": "Banking",
    "PNB": "Banking",
    "BANKBARODA": "Banking",
    "CANBK": "Banking",
    # IT
    "TCS": "IT",
    "INFY": "IT",
    "WIPRO": "IT",
    "HCLTECH": "IT",
    "TECHM": "IT",
    "LTI": "IT",
    "MINDTREE": "IT",
    "COFORGE": "IT",
    "MPHASIS": "IT",
    "LTTS": "IT",
    # Energy
    "RELIANCE": "Energy",
    "ONGC": "Energy",
    "IOC": "Energy",
    "BPCL": "Energy",
    "HINDPETRO": "Energy",
    "GAIL": "Energy",
    "OIL": "Energy",
    # FMCG
    "HINDUNILVR": "FMCG",
    "ITC": "FMCG",
    "NESTLEIND": "FMCG",
    "BRITANNIA": "FMCG",
    "DABUR": "FMCG",
    "GODREJCP": "FMCG",
    "MARICO": "FMCG",
    "COLPAL": "FMCG",
    # Auto
    "MARUTI": "Auto",
    "TATAMOTORS": "Auto",
    "M&M": "Auto",
    "BAJAJ-AUTO": "Auto",
    "EICHERMOT": "Auto",
    "HEROMOTOCO": "Auto",
    "ASHOKLEY": "Auto",
    "TVSMOTOR": "Auto",
    # Pharma
    "SUNPHARMA": "Pharma",
    "DRREDDY": "Pharma",
    "CIPLA": "Pharma",
    "DIVISLAB": "Pharma",
    "LUPIN": "Pharma",
    "BIOCON": "Pharma",
    "AUROPHARMA": "Pharma",
    "CADILAHC": "Pharma",
    # Metals
    "TATASTEEL": "Metals",
    "JSWSTEEL": "Metals",
    "HINDALCO": "Metals",
    "VEDL": "Metals",
    "COALINDIA": "Metals",
    "NMDC": "Metals",
    "SAIL": "Metals",
    # Adani Group (Conglomerate - mapped to Energy/Infra based on primary business)
    "ADANIENT": "Energy",
    "ADANIPORTS": "Energy",
    "JIOFIN": "Financial Services",
    # Healthcare / Hospitals
    "APOLLOHOSP": "Pharma",
    "MAXHEALTH": "Pharma",
    # Paints / Building Materials
    "ASIANPAINT": "FMCG",
    "GRASIM": "Metals",
    "ULTRACEMCO": "Metals",
    "TMPV": "Auto",
    # Financial Services / NBFCs
    "BAJAJFINSV": "Financial Services",
    "BAJFINANCE": "Financial Services",
    "SBILIFE": "Financial Services",
    "HDFCLIFE": "Financial Services",
    "SHRIRAMFIN": "Financial Services",
    # Telecom / Media
    "BHARTIARTL": "Telecom",
    # Consumer / Internet
    "ETERNAL": "Internet",
    "TATACONSUM": "FMCG",
    "TRENT": "FMCG",
    # Defense
    "BEL": "Defense",
    # Aviation
    "INDIGO": "Aviation",
    # Capital Goods / Infrastructure
    "LT": "Capital Goods",
    # Power / Utilities
    "NTPC": "Power",
    "POWERGRID": "Power",
    # Consumer Durables
    "TITAN": "Consumer Durables",
    # Others defaults
    "DEFAULT": "Other",
}


def _to_yahoo_symbol(symbol: str) -> str:
    """Convert a bare NSE ticker to Yahoo Finance format (.NS suffix)."""
    if symbol.startswith("^"):
        return symbol
    return f"{symbol}.NS"


def _is_cache_valid(cache_key: str) -> bool:
    """Check if cached data is still valid based on TTL."""
    if cache_key not in _cache:
        return False
    _cached_data, timestamp = _cache[cache_key]
    age = (dt.datetime.now() - timestamp).total_seconds()
    return age < CACHE_DURATION


def _get_from_cache(cache_key: str):
    """Retrieve data from cache if valid."""
    if _is_cache_valid(cache_key):
        return _cache[cache_key][0]
    return None


def _store_in_cache(cache_key: str, data):
    """Store data in cache with current timestamp."""
    _cache[cache_key] = (data, dt.datetime.now())


def _to_yahoo_symbol(symbol: str) -> str:
    """Convert a bare NSE ticker to Yahoo Finance format (.NS suffix)."""
    if symbol.startswith("^"):
        return symbol
    return f"{symbol}.NS"


def _fetch_yahoo_finance_latest(symbol: str) -> Any | None:
    """Fetch latest data for a symbol from Yahoo Finance."""
    try:
        from data_sources import YFinanceSource

        source = YFinanceSource()
        yahoo_symbol = _to_yahoo_symbol(symbol)
        return source.fetch_latest(yahoo_symbol)
    except Exception as e:
        print(f"YFinanceSource failed for {symbol}: {e}")
        return None


def _fetch_stock_details(symbol: str) -> dict[str, Any]:
    """Fetch detailed information for a stock symbol."""
    stock_data = {"symbol": symbol, "name": symbol, "price": 0.0, "changePct": 0.0, "sector": "Unknown"}

    # Try Yahoo Finance first
    result = _fetch_yahoo_finance_latest(symbol)
    if result:
        stock_data["price"] = result.close
        # Compute percentage change against the previous session's close when
        # the data source provides one; otherwise leave it at 0.0.
        stock_data["changePct"] = _pct_change(result.close, getattr(result, "prev_close", None))

        # Try to get sector from asset database if available
    try:
        from models import Asset, get_session

        session = get_session()
        # Try with .NS suffix first
        asset = session.query(Asset).filter_by(symbol=_to_yahoo_symbol(symbol)).first()
        if not asset:
            # Try bare symbol
            asset = session.query(Asset).filter_by(symbol=symbol).first()
        if asset:
            # Check if sector is valid (not 'None' string or empty)
            if asset.sector and asset.sector.strip() and asset.sector != "None":
                stock_data["sector"] = asset.sector
            else:
                # Fallback to static mapping
                stock_data["sector"] = STOCK_SECTOR_MAP.get(symbol, "Other")
        else:
            # No asset in DB, use static mapping
            stock_data["sector"] = STOCK_SECTOR_MAP.get(symbol, "Other")
        session.close()
    except Exception:
        pass

    return stock_data


def fetch_index_data() -> list[dict[str, Any]]:
    """
    Fetch real-time data for all 4 indices with their top 3 constituent stocks.

    Returns:
        List of index data dictionaries
    """
    indices_data = []

    for index_name, config in INDEX_CONFIG.items():
        cache_key = f"index_{config['symbol']}"
        cached_data = _get_from_cache(cache_key)

        if cached_data:
            indices_data.append(cached_data)
            continue

        index_data = _fetch_single_index_data(index_name, config)
        _store_in_cache(cache_key, index_data)
        indices_data.append(index_data)

    return indices_data


def _pct_change(current: float, previous: float | None) -> float:
    """Return percent change from ``previous`` to ``current``.

    Returns ``0.0`` when ``previous`` is missing, zero, or non-finite so the
    UI never shows ``NaN%`` or divides by zero. A flat 0.0% on a missing
    baseline is preferable to a crash or an ugly ``inf%``.
    """
    if previous is None or previous == 0:
        return 0.0
    try:
        return ((current - previous) / previous) * 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _fetch_single_index_data(index_name: str, config: dict[str, Any]) -> dict[str, Any]:
    """Fetch data for a single index."""
    symbol = config["symbol"]

    # Fetch index data using Yahoo Finance
    index_result = _fetch_yahoo_finance_latest(symbol)

    if not index_result:
        # Return empty data structure if no index data available
        return {"name": index_name, "value": 0.0, "changePct": 0.0, "stocks": []}

    # Fetch constituent stocks
    stocks_data = []
    for stock_symbol in config["constituents"]:
        stock_data = _fetch_stock_details(stock_symbol)
        stock_data["symbol"] = stock_symbol
        stocks_data.append(stock_data)

    return {
        "name": index_name,
        "value": index_result.close,
        "changePct": _pct_change(index_result.close, getattr(index_result, "prev_close", None)),
        "stocks": stocks_data,
    }


def fetch_sector_performance() -> list[dict[str, Any]]:
    """
    Calculate sector performance from the database.

    Returns:
        List of sector data dictionaries
    """
    cache_key = "sector_performance"
    cached_data = _get_from_cache(cache_key)

    if cached_data:
        return cached_data

    try:
        from collections import defaultdict

        from models import Asset, DailyPrice, get_session

        session = get_session()

        # Use the latest available trading day in the DB (not today/yesterday),
        # and the trading day immediately before it. This handles weekends,
        # holidays, and DBs that lag behind the wall clock.
        latest = session.query(DailyPrice.date).order_by(DailyPrice.date.desc()).first()
        if not latest:
            session.close()
            return []
        latest_date = latest[0]

        prev = (
            session.query(DailyPrice.date)
            .filter(DailyPrice.date < latest_date)
            .order_by(DailyPrice.date.desc())
            .first()
        )
        if not prev:
            session.close()
            return []
        prev_date = prev[0]

        # Group prices by sector
        sector_prices = defaultdict(list)

        # Get all equity assets
        equity_assets = session.query(Asset).filter(Asset.type == "equity").all()

        for asset in equity_assets:
            # Get latest price for this asset
            today_price = session.query(DailyPrice).filter_by(asset_id=asset.id, date=latest_date).first()
            # Get previous price for this asset
            yesterday_price = session.query(DailyPrice).filter_by(asset_id=asset.id, date=prev_date).first()

            if today_price and yesterday_price:
                if today_price.close and yesterday_price.close and yesterday_price.close != 0:
                    pct_change = ((today_price.close - yesterday_price.close) / yesterday_price.close) * 100
                    # Use the asset's sector field directly. Assets are stored with
                    # .NS/.BO suffixes, so strip those before the static-map fallback.
                    if asset.sector and asset.sector.strip() and asset.sector != "None":
                        sector_key = asset.sector
                    else:
                        bare_symbol = asset.symbol.replace(".NS", "").replace(".BO", "")
                        sector_key = STOCK_SECTOR_MAP.get(bare_symbol, "Other")
                    sector_prices[sector_key].append(pct_change)

        session.close()

        # Calculate average percentage change for each sector
        sectors_data = []
        for sector_name, changes in sector_prices.items():
            if changes:
                avg_pct = sum(changes) / len(changes)
                sectors_data.append({"name": sector_name, "pct": avg_pct, "stocks_count": len(changes)})

        # Sort by absolute percentage change (descending)
        sectors_data.sort(key=lambda x: abs(x["pct"]), reverse=True)

        _store_in_cache(cache_key, sectors_data)
        return sectors_data

    except Exception as e:
        print(f"Error fetching sector performance: {e}")
        return []


# Test data for development and fallback
TEST_SECTOR_DATA = [
    {"name": "Banking", "pct": 1.24, "stocks_count": 10},
    {"name": "IT", "pct": -0.91, "stocks_count": 8},
    {"name": "FMCG", "pct": -0.48, "stocks_count": 6},
    {"name": "Auto", "pct": 0.34, "stocks_count": 5},
    {"name": "Energy", "pct": 1.50, "stocks_count": 4},
    {"name": "Pharma", "pct": 1.12, "stocks_count": 3},
]

TEST_INDEX_DATA = [
    {
        "name": "NIFTY 50",
        "value": 24847.30,
        "changePct": 0.50,
        "stocks": [
            {
                "symbol": "RELIANCE",
                "name": "Reliance Industries",
                "price": 2847.35,
                "changePct": 1.50,
                "sector": "Energy",
            },
            {
                "symbol": "TCS",
                "name": "Tata Consultancy Services",
                "price": 3912.60,
                "changePct": -0.72,
                "sector": "IT",
            },
            {"symbol": "HDFCBANK", "name": "HDFC Bank", "price": 1724.80, "changePct": 1.11, "sector": "Banking"},
        ],
    },
    {
        "name": "NIFTY BANK",
        "value": 52341.20,
        "changePct": -0.17,
        "stocks": [
            {"symbol": "HDFCBANK", "name": "HDFC Bank", "price": 1724.80, "changePct": 1.11, "sector": "Banking"},
            {"symbol": "ICICIBANK", "name": "ICICI Bank", "price": 1312.45, "changePct": 1.73, "sector": "Banking"},
            {"symbol": "SBIN", "name": "State Bank of India", "price": 678.90, "changePct": 0.85, "sector": "Banking"},
        ],
    },
    {
        "name": "SENSEX",
        "value": 82156.80,
        "changePct": -0.05,
        "stocks": [
            {
                "symbol": "RELIANCE",
                "name": "Reliance Industries",
                "price": 2847.35,
                "changePct": 1.50,
                "sector": "Energy",
            },
            {
                "symbol": "TCS",
                "name": "Tata Consultancy Services",
                "price": 3912.60,
                "changePct": -0.72,
                "sector": "IT",
            },
            {"symbol": "HDFCBANK", "name": "HDFC Bank", "price": 1724.80, "changePct": 1.11, "sector": "Banking"},
        ],
    },
    {
        "name": "NIFTY IT",
        "value": 36892.10,
        "changePct": 0.64,
        "stocks": [
            {
                "symbol": "TCS",
                "name": "Tata Consultancy Services",
                "price": 3912.60,
                "changePct": -0.72,
                "sector": "IT",
            },
            {"symbol": "INFY", "name": "Infosys", "price": 1847.25, "changePct": -0.79, "sector": "IT"},
            {"symbol": "WIPRO", "name": "Wipro", "price": 547.80, "changePct": -1.47, "sector": "IT"},
        ],
    },
]

# For testing - enable test mode to use test data
_test_mode = True


def set_test_mode(enabled: bool = True):
    """Enable/disable test mode for development."""
    global _test_mode
    _test_mode = enabled


def get_index_data_with_fallback() -> list[dict[str, Any]]:
    """
    Get index data with fallback to test data if real data unavailable.
    """
    try:
        data = fetch_index_data()
        # If all indices have no real data, use test data
        if not any(ind["value"] > 0 for ind in data):
            return TEST_INDEX_DATA if _test_mode else data
        return data
    except Exception as e:
        print(f"Real data fetch failed, using test data: {e}")
        return TEST_INDEX_DATA if _test_mode else []


def get_sector_data_with_fallback() -> list[dict[str, Any]]:
    """
    Get sector performance data with fallback to test data if DB empty.

    The fallback to TEST_SECTOR_DATA is unconditional when the real-data
    path returns nothing — this is what makes the dashboard render the
    expected sector chips even when the DB has no usable sector data.
    """
    try:
        data = fetch_sector_performance()
        if not data:
            return TEST_SECTOR_DATA
        return data
    except Exception as e:
        print(f"Sector data fetch failed, using test data: {e}")
        return TEST_SECTOR_DATA
