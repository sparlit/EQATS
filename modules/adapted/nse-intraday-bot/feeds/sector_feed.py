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
NSE Sector Momentum Feed.
Maps F&O stocks to their NSE sector index (Yahoo Finance ticker).
Checks if the sector is in an uptrend (above 20 EMA) and whether
the stock is outperforming its sector over the last 5 trading days.
"""
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

# ── Stock → Sector index (Yahoo Finance) ─────────────────────────
SECTOR_MAP: dict[str, str] = {
    # ── Banking ──────────────────────────────────────────────────
    "HDFCBANK": "^NSEBANK",
    "ICICIBANK": "^NSEBANK",
    "SBIN": "^NSEBANK",
    "AXISBANK": "^NSEBANK",
    "KOTAKBANK": "^NSEBANK",
    "INDUSINDBK": "^NSEBANK",
    "BANDHANBNK": "^NSEBANK",
    "FEDERALBNK": "^NSEBANK",
    "CANBK": "^NSEBANK",
    "PNB": "^NSEBANK",
    "BANKBARODA": "^NSEBANK",
    "IDFCFIRSTB": "^NSEBANK",
    "YESBANK": "^NSEBANK",
    "RBLBANK": "^NSEBANK",
    "AUBANK": "^NSEBANK",
    "KARURVYSYA": "^NSEBANK",
    "DCBBANK": "^NSEBANK",
    "TMVHFL": "^NSEBANK",
    # ── IT / Technology ──────────────────────────────────────────
    "TCS": "^CNXIT",
    "INFY": "^CNXIT",
    "WIPRO": "^CNXIT",
    "HCLTECH": "^CNXIT",
    "TECHM": "^CNXIT",
    "MPHASIS": "^CNXIT",
    "LTIM": "^CNXIT",
    "PERSISTENT": "^CNXIT",
    "COFORGE": "^CNXIT",
    "OFSS": "^CNXIT",
    "KPITTECH": "^CNXIT",
    "TATAELXSI": "^CNXIT",
    "CYIENT": "^CNXIT",
    "HEXAWARE": "^CNXIT",
    # ── Auto & Auto-ancillary ────────────────────────────────────
    "MARUTI": "^CNXAUTO",
    "TATAMOTORS": "^CNXAUTO",
    "BAJAJ-AUTO": "^CNXAUTO",
    "HEROMOTOCO": "^CNXAUTO",
    "EICHERMOT": "^CNXAUTO",
    "MOTHERSON": "^CNXAUTO",
    "BALKRISIND": "^CNXAUTO",
    "EXIDEIND": "^CNXAUTO",
    "MRF": "^CNXAUTO",
    "APOLLOTYRE": "^CNXAUTO",
    "BHARATFORG": "^CNXAUTO",
    "BOSCHLTD": "^CNXAUTO",
    "MINDA": "^CNXAUTO",
    "SONA BLW": "^CNXAUTO",
    # ── Pharma & Healthcare ──────────────────────────────────────
    "SUNPHARMA": "^CNXPHARMA",
    "DRREDDY": "^CNXPHARMA",
    "CIPLA": "^CNXPHARMA",
    "DIVISLAB": "^CNXPHARMA",
    "APOLLOHOSP": "^CNXPHARMA",
    "BIOCON": "^CNXPHARMA",
    "TORNTPHARM": "^CNXPHARMA",
    "ALKEM": "^CNXPHARMA",
    "LALPATHLAB": "^CNXPHARMA",
    "METROPOLIS": "^CNXPHARMA",
    "ABBOTINDIA": "^CNXPHARMA",
    "AUROPHARMA": "^CNXPHARMA",
    "IPCALAB": "^CNXPHARMA",
    "GLENMARK": "^CNXPHARMA",
    "ZYDUSLIFE": "^CNXPHARMA",
    "NATCOPHARM": "^CNXPHARMA",
    # ── FMCG ─────────────────────────────────────────────────────
    "HINDUNILVR": "^CNXFMCG",
    "ITC": "^CNXFMCG",
    "NESTLEIND": "^CNXFMCG",
    "BRITANNIA": "^CNXFMCG",
    "TATACONSUM": "^CNXFMCG",
    "DABUR": "^CNXFMCG",
    "MARICO": "^CNXFMCG",
    "COLPAL": "^CNXFMCG",
    "GODREJCP": "^CNXFMCG",
    "EMAMILTD": "^CNXFMCG",
    "PGHH": "^CNXFMCG",
    "VBL": "^CNXFMCG",
    "RADICO": "^CNXFMCG",
    # ── Metals & Mining ──────────────────────────────────────────
    "TATASTEEL": "^CNXMETAL",
    "JSWSTEEL": "^CNXMETAL",
    "HINDALCO": "^CNXMETAL",
    "VEDL": "^CNXMETAL",
    "SAIL": "^CNXMETAL",
    "NMDC": "^CNXMETAL",
    "NATIONALUM": "^CNXMETAL",
    "COALINDIA": "^CNXMETAL",
    "JINDALSTEL": "^CNXMETAL",
    "APLAPOLLO": "^CNXMETAL",
    "RATNAMANI": "^CNXMETAL",
    # ── Energy / Oil & Gas ───────────────────────────────────────
    "ONGC": "^CNXENERGY",
    "BPCL": "^CNXENERGY",
    "IOC": "^CNXENERGY",
    "NTPC": "^CNXENERGY",
    "POWERGRID": "^CNXENERGY",
    "RELIANCE": "^CNXENERGY",
    "ADANIGREEN": "^CNXENERGY",
    "TATAPOWER": "^CNXENERGY",
    "ADANIPORTS": "^CNXENERGY",
    "CESC": "^CNXENERGY",
    "TORNTPOWER": "^CNXENERGY",
    "GAIL": "^CNXENERGY",
    "IGL": "^CNXENERGY",
    "MGL": "^CNXENERGY",
    # ── Capital Goods / Infra ────────────────────────────────────
    "LT": "^CNXINFRA",
    "HAL": "^CNXINFRA",
    "BEL": "^CNXINFRA",
    "BHEL": "^CNXINFRA",
    "RVNL": "^CNXINFRA",
    "ABB": "^CNXINFRA",
    "SIEMENS": "^CNXINFRA",
    "HAVELLS": "^CNXINFRA",
    "POLYCAB": "^CNXINFRA",
    "KEI": "^CNXINFRA",
    "SUZLON": "^CNXINFRA",
    "CUMMINSIND": "^CNXINFRA",
    "GRINDWELL": "^CNXINFRA",
    # ── Finance / NBFC ───────────────────────────────────────────
    "BAJFINANCE": "^CNXFINANCE",
    "BAJAJFINSV": "^CNXFINANCE",
    "MUTHOOTFIN": "^CNXFINANCE",
    "CHOLAFIN": "^CNXFINANCE",
    "HDFCLIFE": "^CNXFINANCE",
    "SBILIFE": "^CNXFINANCE",
    "ICICIGI": "^CNXFINANCE",
    "HDFCAMC": "^CNXFINANCE",
    "ABCAPITAL": "^CNXFINANCE",
    "LICHSGFIN": "^CNXFINANCE",
    "POONAWALLA": "^CNXFINANCE",
    "ANGELONE": "^CNXFINANCE",
    "CDSL": "^CNXFINANCE",
    "BSE": "^CNXFINANCE",
    # ── Realty ───────────────────────────────────────────────────
    "DLF": "^CNXREALTY",
    "GODREJPROP": "^CNXREALTY",
    "OBEROIRLTY": "^CNXREALTY",
    "PRESTIGE": "^CNXREALTY",
    "PHOENIXLTD": "^CNXREALTY",
    "SOBHA": "^CNXREALTY",
    "MAHLIFE": "^CNXREALTY",
    # ── Consumer Discretionary ───────────────────────────────────
    "DMART": "^NSEI",
    "NYKAA": "^NSEI",
    "ZOMATO": "^NSEI",
    "IRCTC": "^NSEI",
    "TRENT": "^NSEI",
    "PAYTM": "^NSEI",
    "NAUKRI": "^NSEI",
    "JUBLFOOD": "^NSEI",
    "DEVYANI": "^NSEI",
    "CAMPUS": "^NSEI",
}

FALLBACK_INDEX = "^NSEI"  # Nifty 50 for unmapped stocks
ALL_SECTOR_TICKERS = [*list(set(SECTOR_MAP.values())), FALLBACK_INDEX]


def prefetch_sectors() -> dict:
    """
    Download 60 days of daily data for all sector indices at once.
    Returns {ticker: pd.DataFrame} cache.
    Call once per run, then pass to check_sector_momentum().
    """
    cache = {}
    tickers = [*list(set(SECTOR_MAP.values())), FALLBACK_INDEX]
    for ticker in set(tickers):
        try:
            df = yf.download(ticker, period="60d", interval="1d", progress=False, auto_adjust=True)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.columns = [c.lower() for c in df.columns]
            if len(df) >= 22:
                cache[ticker] = df
        except Exception as e:
            print(f"[SECTOR] Failed to load {ticker}: {e}")
    print(f"[SECTOR] Pre-fetched {len(cache)}/{len(set(tickers))} sector indices")
    return cache


def check_sector_momentum(symbol: str, df_stock: pd.DataFrame, sector_cache: dict) -> dict:
    """
    Layer 4 check for one stock.
    Returns dict with pass/fail and detail metrics.
    """
    empty = {
        "pass": False,
        "sector_ticker": None,
        "sector_above_ema": False,
        "outperforming": False,
        "stock_5d_pct": 0.0,
        "sector_5d_pct": 0.0,
        "sector_name": "Unknown",
    }

    sector_ticker = SECTOR_MAP.get(symbol.upper(), FALLBACK_INDEX)
    sector_df = sector_cache.get(sector_ticker)

    if sector_df is None or len(sector_df) < 22:
        # Try fallback
        sector_df = sector_cache.get(FALLBACK_INDEX)
        if sector_df is None:
            return empty

    sector_close = sector_df["close"]
    ema20 = sector_close.ewm(span=20, adjust=False).mean()
    above_ema = float(sector_close.iloc[-1]) > float(ema20.iloc[-1])

    # 5-day performance
    outperforming = False
    stock_5d = 0.0
    sector_5d = 0.0

    if len(sector_close) >= 6 and len(df_stock) >= 6:
        sector_5d = round((float(sector_close.iloc[-1]) / float(sector_close.iloc[-6]) - 1) * 100, 2)
        stock_5d = round((float(df_stock["close"].iloc[-1]) / float(df_stock["close"].iloc[-6]) - 1) * 100, 2)
        outperforming = stock_5d > sector_5d

    # Sector name for display
    name_map = {
        "^NSEBANK": "Nifty Bank",
        "^CNXIT": "Nifty IT",
        "^CNXAUTO": "Nifty Auto",
        "^CNXPHARMA": "Nifty Pharma",
        "^CNXFMCG": "Nifty FMCG",
        "^CNXMETAL": "Nifty Metal",
        "^CNXENERGY": "Nifty Energy",
        "^CNXINFRA": "Nifty Infra",
        "^CNXFINANCE": "Nifty Finance",
        "^CNXREALTY": "Nifty Realty",
        "^NSEI": "Nifty 50",
    }

    return {
        "pass": above_ema and outperforming,
        "sector_ticker": sector_ticker,
        "sector_name": name_map.get(sector_ticker, sector_ticker),
        "sector_above_ema": above_ema,
        "outperforming": outperforming,
        "stock_5d_pct": stock_5d,
        "sector_5d_pct": sector_5d,
    }
