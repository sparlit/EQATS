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


"""
Live NSE market snapshot — indices + top gainers/losers, from free sources.

Index levels come from yfinance (reliable). Constituent gainers/losers come from
NSE's equity-stockIndices API (session-warmed, same pattern as FII/DII). Both
degrade gracefully so the dashboard never hard-fails.
"""

import requests
import yfinance as yf
from loguru import logger

NSE_BASE = "https://www.nseindia.com"
NSE_VARIATIONS_API = "https://www.nseindia.com/api/live-analysis-variations"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/market-data/live-equity-market",
}

INDICES = {
    "NIFTY 50": "^NSEI",
    "BANK NIFTY": "^NSEBANK",
    "SENSEX": "^BSESN",
    "NIFTY MIDCAP": "^NSEMDCP50",
    "INDIA VIX": "^INDIAVIX",
}


def fetch_indices() -> list[dict]:
    """Return [{name, last, change, pct}] for headline indices via yfinance."""
    out = []
    for name, ticker in INDICES.items():
        try:
            df = yf.Ticker(ticker).history(period="5d", interval="1d")
            if df.empty or len(df) < 2:
                continue
            closes = df["Close"].dropna()
            last = float(closes.iloc[-1])
            prev = float(closes.iloc[-2])
            chg = last - prev
            out.append(
                {
                    "name": name,
                    "last": round(last, 2),
                    "change": round(chg, 2),
                    "pct": round(chg / prev * 100, 2) if prev else 0.0,
                }
            )
        except Exception as exc:
            logger.debug("Index fetch failed {}: {}", name, exc)
    return out


# Nifty 50 constituents (yfinance fallback when NSE blocks the datacenter IP)
NIFTY50 = [
    "RELIANCE",
    "HDFCBANK",
    "ICICIBANK",
    "INFY",
    "TCS",
    "ITC",
    "LT",
    "AXISBANK",
    "SBIN",
    "BHARTIARTL",
    "KOTAKBANK",
    "HINDUNILVR",
    "BAJFINANCE",
    "ASIANPAINT",
    "MARUTI",
    "SUNPHARMA",
    "TITAN",
    "ULTRACEMCO",
    "NESTLEIND",
    "WIPRO",
    "ONGC",
    "NTPC",
    "POWERGRID",
    "M&M",
    "TATAMOTORS",
    "TATASTEEL",
    "JSWSTEEL",
    "ADANIENT",
    "ADANIPORTS",
    "COALINDIA",
    "HCLTECH",
    "TECHM",
    "BAJAJFINSV",
    "GRASIM",
    "HDFCLIFE",
    "SBILIFE",
    "DRREDDY",
    "CIPLA",
    "BRITANNIA",
    "EICHERMOT",
    "HEROMOTOCO",
    "BAJAJ-AUTO",
    "INDUSINDBK",
    "APOLLOHOSP",
    "TATACONSUM",
    "BPCL",
    "HINDALCO",
    "SHRIRAMFIN",
    "LTIM",
]


def _yf_gainers_losers(top_n: int) -> dict:
    """Fallback: derive Nifty-50 gainers/losers via a single batched yfinance call."""
    try:
        import yfinance as yf

        tickers = [s + ".NS" for s in NIFTY50]
        data = yf.download(
            tickers, period="2d", interval="1d", group_by="ticker", auto_adjust=True, progress=False, threads=True
        )
        rows = []
        for s, t in zip(NIFTY50, tickers, strict=False):
            try:
                df = data[t].dropna()
                if len(df) < 2:
                    continue
                last, prev = float(df["Close"].iloc[-1]), float(df["Close"].iloc[-2])
                rows.append(
                    {
                        "symbol": s,
                        "ltp": round(last, 2),
                        "change": round(last - prev, 2),
                        "pct": round((last - prev) / prev * 100, 2),
                    }
                )
            except Exception:
                continue
        if not rows:
            return {"available": False, "note": "yfinance fallback returned no data"}
        rows.sort(key=lambda x: x["pct"], reverse=True)
        return {
            "available": True,
            "category": "NIFTY50",
            "source": "yfinance",
            "gainers": rows[:top_n],
            "losers": list(reversed(rows[-top_n:])),
        }
    except Exception as exc:
        logger.warning("yfinance gainers/losers fallback failed: {}", exc)
        return {"available": False, "note": f"unavailable ({type(exc).__name__})"}


def _nse_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(_HEADERS)
    s.get(NSE_BASE, timeout=10)
    s.get(f"{NSE_BASE}/market-data/live-equity-market", timeout=10)
    return s


def _parse_variation(rows: list, top_n: int) -> list[dict]:
    out = []
    for row in rows[:top_n]:
        out.append(
            {
                "symbol": row.get("symbol", ""),
                "ltp": round(float(row.get("ltp", 0) or 0), 2),
                "change": round(float(row.get("net_price", 0) or 0), 2),
                "pct": round(float(row.get("perChange", 0) or 0), 2),
            }
        )
    return out


def fetch_gainers_losers(category: str = "NIFTY", top_n: int = 5) -> dict:
    """
    Return {'gainers': [...], 'losers': [...]} for an NSE category
    ('NIFTY', 'BANKNIFTY', 'allSec'). Each stock: {symbol, ltp, change, pct}.
    Falls back to {available: False}.
    """
    try:
        s = _nse_session()
        g = s.get(f"{NSE_VARIATIONS_API}?index=gainers", timeout=12)
        l = s.get(f"{NSE_VARIATIONS_API}?index=losers", timeout=12)
        g.raise_for_status()
        l.raise_for_status()
        gj, lj = g.json(), l.json()

        def _cat(payload):
            # gainers nests by index category; losers returns top-level 'data'
            block = payload.get(category)
            if isinstance(block, dict) and block.get("data"):
                return block["data"]
            if isinstance(payload.get("data"), list) and payload["data"]:
                return payload["data"]
            alt = payload.get("allSec")
            return alt.get("data", []) if isinstance(alt, dict) else []

        gainers = _parse_variation(_cat(gj), top_n)
        losers = _parse_variation(_cat(lj), top_n)
        if not gainers and not losers:
            logger.info("NSE variations empty — using yfinance fallback")
            return _yf_gainers_losers(top_n)
        return {"available": True, "category": category, "gainers": gainers, "losers": losers}
    except Exception as exc:
        logger.warning("NSE gainers/losers blocked ({}); using yfinance fallback", type(exc).__name__)
        return _yf_gainers_losers(top_n)
