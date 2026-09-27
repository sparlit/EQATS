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
Stock universe for the trading engine.
Top 20 liquid NSE stocks — NIFTY50 large-caps + high-volume F&O names.
Selected by: F&O availability, avg daily turnover, tight bid-ask spreads.
"""

# symbol → yfinance ticker
UNIVERSE: dict[str, str] = {
    # Banking & Finance (most liquid, highest F&O OI)
    "HDFCBANK": "HDFCBANK.NS",
    "ICICIBANK": "ICICIBANK.NS",
    "SBIN": "SBIN.NS",
    "AXISBANK": "AXISBANK.NS",
    "KOTAKBANK": "KOTAKBANK.NS",
    "BAJFINANCE": "BAJFINANCE.NS",
    # IT (high volume, trend-friendly)
    "TCS": "TCS.NS",
    "INFY": "INFY.NS",
    "HCLTECH": "HCLTECH.NS",
    "WIPRO": "WIPRO.NS",
    # Large-cap diversified
    "RELIANCE": "RELIANCE.NS",
    "LT": "LT.NS",
    "BHARTIARTL": "BHARTIARTL.NS",
    # Auto & Metal (volatile, good for breakouts)
    "TATAMOTORS": "TATAMOTORS.NS",
    "TATASTEEL": "TATASTEEL.NS",
    "JSWSTEEL": "JSWSTEEL.NS",
    # Energy & Infra
    "ONGC": "ONGC.NS",
    "NTPC": "NTPC.NS",
    "POWERGRID": "POWERGRID.NS",
    # Pharma
    "SUNPHARMA": "SUNPHARMA.NS",
}

# Sector mapping — used for sector-strength scoring in Phase 2
SECTORS: dict[str, list[str]] = {
    "BANKING": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK"],
    "FINANCE": ["BAJFINANCE"],
    "IT": ["TCS", "INFY", "HCLTECH", "WIPRO"],
    "ENERGY": ["RELIANCE", "ONGC", "NTPC", "POWERGRID"],
    "AUTO": ["TATAMOTORS"],
    "METALS": ["TATASTEEL", "JSWSTEEL"],
    "INFRA": ["LT"],
    "TELECOM": ["BHARTIARTL"],
    "PHARMA": ["SUNPHARMA"],
}

# Reverse map: symbol → sector (derived from SECTORS above)
SYMBOL_SECTOR: dict[str, str] = {sym: sector for sector, symbols in SECTORS.items() for sym in symbols}

# Scoring weights for daily stock ranking (Phase 2)
# Must sum to 1.0
RANKING_WEIGHTS: dict[str, float] = {
    "relative_volume": 0.25,  # today's volume vs 20-day avg
    "atr_volatility": 0.20,  # ATR/price — how much it moves
    "gap": 0.20,  # open vs prev close
    "sector_strength": 0.15,  # how strong the sector is today
    "trend_strength": 0.20,  # ADX-based trend score
}


# ── Scan universe (stocks-in-play engine) ─────────────────────────────────────
# Zarattini/Barbon/Aziz (SSRN 4729284): the ORB edge lives almost entirely in
# "stocks in play" — the day's highest relative-volume names. Profit therefore
# requires scanning a WIDE universe each morning and trading only the few names
# that are in play, not asking fixed mega-caps "what fits today?".
# ~100 liquid NSE F&O names. Unknown/renamed symbols fail gracefully at fetch.

SCAN_UNIVERSE: list[str] = [
    # NIFTY 50 core
    "ADANIENT",
    "ADANIPORTS",
    "APOLLOHOSP",
    "ASIANPAINT",
    "AXISBANK",
    "BAJAJ-AUTO",
    "BAJFINANCE",
    "BAJAJFINSV",
    "BPCL",
    "BHARTIARTL",
    "CIPLA",
    "COALINDIA",
    "DRREDDY",
    "EICHERMOT",
    "GRASIM",
    "HCLTECH",
    "HDFCBANK",
    "HDFCLIFE",
    "HEROMOTOCO",
    "HINDALCO",
    "ICICIBANK",
    "ITC",
    "INDUSINDBK",
    "INFY",
    "JSWSTEEL",
    "KOTAKBANK",
    "LT",
    "M&M",
    "MARUTI",
    "NTPC",
    "ONGC",
    "POWERGRID",
    "RELIANCE",
    "SBILIFE",
    "SBIN",
    "SUNPHARMA",
    "TCS",
    "TATACONSUM",
    "TATAMOTORS",
    "TATASTEEL",
    "TECHM",
    "TITAN",
    "ULTRACEMCO",
    "WIPRO",
    "ETERNAL",
    "JIOFIN",
    # High-beta / midcap F&O movers (where "in play" days actually happen)
    "ADANIPOWER",
    "ADANIGREEN",
    "DLF",
    "VEDL",
    "JINDALSTEL",
    "SAIL",
    "NMDC",
    "PNB",
    "BANKBARODA",
    "CANBK",
    "IDFCFIRSTB",
    "FEDERALBNK",
    "AUBANK",
    "INDHOTEL",
    "IRCTC",
    "INDIGO",
    "HAL",
    "BEL",
    "BHEL",
    "IRFC",
    "RVNL",
    "PFC",
    "RECLTD",
    "NHPC",
    "GAIL",
    "IOC",
    "HINDPETRO",
    "AMBUJACEM",
    "DABUR",
    "MARICO",
    "HAVELLS",
    "POLYCAB",
    "SIEMENS",
    "ABB",
    "CGPOWER",
    "MOTHERSON",
    "BHARATFORG",
    "ASHOKLEY",
    "TVSMOTOR",
    "EXIDEIND",
    "APOLLOTYRE",
    "VOLTAS",
    "LICHSGFIN",
    "CHOLAFIN",
    "MANAPPURAM",
    "SBICARD",
    "PAYTM",
    "ZYDUSLIFE",
    "LUPIN",
    "AUROPHARMA",
    "BIOCON",
    "GLENMARK",
    "MPHASIS",
    "COFORGE",
    "PERSISTENT",
    "LTIM",
    "TATAPOWER",
    "JSWENERGY",
    "SUZLON",
    "KPITTECH",
    "DIXON",
    "TRENT",
    "ABFRL",
    "UPL",
    "SRF",
    "TATACHEM",
    "JUBLFOOD",
    "DELHIVERY",
    "CONCOR",
    "IDEA",
    "INDUSTOWER",
    "HFCL",
    "MAZDOCK",
    "COCHINSHIP",
    "BEML",
    "OIL",
    "IGL",
    "TATAELXSI",
]


def get_ticker(symbol: str) -> str:
    """Return yfinance ticker. Falls back to symbol itself for non-universe stocks (e.g. IOC.NS from search)."""
    return UNIVERSE.get(symbol.upper(), symbol)


def all_tickers() -> list[str]:
    return list(UNIVERSE.values())


def all_symbols() -> list[str]:
    return list(UNIVERSE.keys())
