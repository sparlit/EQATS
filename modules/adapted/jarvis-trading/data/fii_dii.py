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
FII/DII institutional flow data — from NSE's official provisional figures.

NSE publishes daily provisional FII/FPI and DII cash-market activity (buy, sell,
net) after market close at:
    https://www.nseindia.com/reports/fii-dii
backed by the JSON endpoint /api/fiidiiTradeReact.

NSE's API requires a warmed-up session (cookies from the homepage) and a browser
User-Agent. Datacenter IPs (e.g. CI runners) are sometimes blocked — on failure
this returns a structured 'unavailable' dict so the briefing degrades gracefully
rather than fabricating numbers.
"""

import requests
from loguru import logger

NSE_BASE = "https://www.nseindia.com"
NSE_FII_DII_API = "https://www.nseindia.com/api/fiidiiTradeReact"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/reports/fii-dii",
    "Connection": "keep-alive",
}


def _to_float(val: object) -> float:
    try:
        return round(float(str(val).replace(",", "").strip()), 2)
    except (TypeError, ValueError):
        return 0.0


def fetch_fii_dii(timeout: int = 12) -> dict:
    """
    Return latest provisional FII/DII cash-market flows (₹ crore).

    Shape on success:
      {
        "available": True,
        "date": "30-May-2026",
        "fii": {"buy":.., "sell":.., "net":..},
        "dii": {"buy":.., "sell":.., "net":..},
        "net_combined": <fii.net + dii.net>,
        "source": "NSE provisional",
      }
    On failure: {"available": False, "note": "...reason..."}
    """
    try:
        s = requests.Session()
        s.headers.update(_HEADERS)
        # Warm up to obtain cookies (NSE rejects cold API calls)
        s.get(NSE_BASE, timeout=timeout)
        s.get(f"{NSE_BASE}/reports/fii-dii", timeout=timeout)
        r = s.get(NSE_FII_DII_API, timeout=timeout)
        r.raise_for_status()
        rows = r.json()
        if not isinstance(rows, list) or not rows:
            return {"available": False, "note": "NSE returned no FII/DII rows"}

        out: dict = {"available": True, "source": "NSE provisional", "date": None, "fii": None, "dii": None}
        for row in rows:
            cat = str(row.get("category", "")).upper()
            block = {
                "buy": _to_float(row.get("buyValue")),
                "sell": _to_float(row.get("sellValue")),
                "net": _to_float(row.get("netValue")),
            }
            out["date"] = row.get("date", out["date"])
            if "FII" in cat or "FPI" in cat:
                out["fii"] = block
            elif "DII" in cat:
                out["dii"] = block

        if not out["fii"] and not out["dii"]:
            return {"available": False, "note": "NSE FII/DII categories not found in response"}

        fii_net = out["fii"]["net"] if out["fii"] else 0.0
        dii_net = out["dii"]["net"] if out["dii"] else 0.0
        out["net_combined"] = round(fii_net + dii_net, 2)
        logger.info("FII/DII fetched ({}): FII net {} | DII net {}", out["date"], fii_net, dii_net)
        return out

    except Exception as exc:
        logger.warning("FII/DII direct fetch failed ({}); trying cache", type(exc).__name__)
        try:
            from data.nse_cache import read_cache

            cached = read_cache().get("fii_dii")
            if cached and cached.get("available"):
                return {**cached, "source": "NSE provisional (cached)"}
        except Exception:
            pass
        return {"available": False, "note": f"NSE FII/DII unavailable ({type(exc).__name__}) — confirm manually"}
