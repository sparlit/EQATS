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


# stock_universes.py

# A dictionary holding lists of stock ticker symbols categorized by market segment.
# Note: These are base symbols. The data screener will append '.NS' to fetch from the National Stock Exchange of India.
UNIVERSES = {
    "nifty_50": [
        "RELIANCE",
        "TCS",
        "HDFCBANK",
        "ICICIBANK",
        "INFY",
        "BHARTIARTL",
        "ITC",
        "SBIN",
        "LT",
        "HINDUNILVR",
        "BAJFINANCE",
        "MARUTI",
        "HCLTECH",
        "SUNPHARMA",
        "KOTAKBANK",
        "TITAN",
        "ONGC",
        "NTPC",
        "POWERGRID",
        "ADANIENT",
        "COALINDIA",
        "TATASTEEL",
        "ASIANPAINT",
        "M&M",
        "BAJAJFINSV",
        "NESTLEIND",
        "GRASIM",
        "TECHM",
        "WIPRO",
        "ULTRACEMCO",
        "JSWSTEEL",
        "ADANIPORTS",
        "INDUSINDBK",
        "CIPLA",
        "DRREDDY",
        "DIVISLAB",
        "EICHERMOT",
        "HINDALCO",
        "BPCL",
        "HEROMOTOCO",
        "BRITANNIA",
        "APOLLOHOSP",
        "SHREECEM",
    ],
    "largecap": [
        "PIDILITIND",
        "GODREJCP",
        "BAJAJ-AUTO",
        "HDFCLIFE",
        "SBIlife",
        "ZOMATO",
        "TVSMOTOR",
        "CHOLAFIN",
        "PNB",
        "GAIL",
        "VEDL",
        "AMBUJACEM",
        "DABUR",
        "SHRIRAMFIN",
        "DLF",
    ],
    "midcap": [
        "POLYCAB",
        "PERSISTENT",
        "COFORGE",
        "MAXHEALTH",
        "DIXON",
        "CUMMINSIND",
        "TRENT",
        "FEDERALBNK",
        "ASTRAL",
        "ASHOKLEY",
        "AUROPHARMA",
        "VOLTAS",
        "JUBLFOOD",
        "MRF",
        "PAGEIND",
        "MUTHOOTFIN",
        "IDFCFIRSTB",
        "LUPIN",
        "BOSCHLTD",
        "IDEA",
        "GMRINFRA",
    ],
    "smallcap": [
        "CDSL",
        "ANGELONE",
        "KAYNES",
        "ROUTE",
        "RADICO",
        "DATAPATTNS",
        "SONACOMS",
        "BSOFT",
        "KPITTECH",
        "MASTEK",
        "TANLA",
        "CENTURYTEX",
        "CYIENT",
        "JBCHEPHARM",
        "BLS",
        "SUZLON",
        "IRFC",
        "RVNL",
        "MAZDOCK",
        "IREDA",
    ],
}


def get_universe(category: str = "nifty_50") -> list:
    """
    Fetches the list of tickers for the requested category.
    Defaults to 'nifty_50' if an invalid category is passed.
    """
    return UNIVERSES.get(category.lower(), UNIVERSES["nifty_50"])
