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
NSE Bulk & Block Deal scraper.
Fetches institutional BUY orders from NSE official API.
Sources:
  https://www.nseindia.com/api/bulk-deals
  https://www.nseindia.com/api/block-deals

Returns dict: {SYMBOL: [list of deal dicts]} — only BUY by institutions.
"""
import json
import os
import time
from datetime import datetime, timedelta, timezone

import requests

# ── Institutional name keywords ──────────────────────────────────
INST_KEYWORDS = [
    "MUTUAL FUND",
    " MF",
    "FII",
    "FPI",
    "FOREIGN",
    "GOLDMAN",
    "MORGAN STANLEY",
    "NIPPON",
    "SBI MF",
    "HDFC MF",
    "HDFC MUTUAL",
    "BIRLA",
    "KOTAK MF",
    "KOTAK MUTUAL",
    "DSP",
    "ICICI MF",
    "ICICI MUTUAL",
    "UTI ",
    "AXIS MF",
    "AXIS MUTUAL",
    "FRANKLIN",
    "INVESCO",
    "MIRAE",
    "MOTILAL",
    "ADITYA BIRLA",
    "TATA MF",
    "TATA MUTUAL",
    "CANARA",
    "UNION MF",
    "LIC ",
    "INSURANCE",
    "PENSION",
    "PROVIDENT",
    "ENDOWMENT",
    "TRUST",
    "EDELWEISS",
    "SUNDARAM MF",
    "NAVI MF",
    "PGIM",
    "WHITEOAK",
    "QUANT MF",
    "360 ONE",
    "BAJAJ FINSERV MF",
    "BANK OF INDIA MF",
    "JM FINANCIAL",
    "SHRIRAM MF",
    "ITI MF",
]

_CACHE_FILE = "bulk_deals_cache.json"


def _is_institutional(name: str) -> bool:
    if not name:
        return False
    n = name.upper()
    return any(kw.upper() in n for kw in INST_KEYWORDS)


def _ist_date_str() -> str:
    ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    return ist.strftime("%Y-%m-%d")


def _nse_session() -> requests.Session:
    """Create browser-like session to pass NSE CORS check."""
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com/",
            "Connection": "keep-alive",
        }
    )
    try:
        s.get("https://www.nseindia.com/", timeout=10)
        time.sleep(0.8)
    except Exception:
        pass
    return s


def _normalize_deal(deal: dict, source: str) -> dict | None:
    """Normalize different field name variants from NSE JSON."""
    # Symbol
    symbol = (
        (deal.get("symbol") or deal.get("Symbol") or deal.get("SYMBOL") or "")
        .upper()
        .strip()
        .replace(" ", "")
        .replace("-EQ", "")
    )

    # Client name
    client = (
        deal.get("clientName") or deal.get("client_name") or deal.get("ClientName") or deal.get("CLIENTNAME") or ""
    ).strip()

    # Buy/Sell
    bs = (
        (deal.get("buySell") or deal.get("buy_sell") or deal.get("BuySell") or deal.get("BUYSELL") or "")
        .strip()
        .upper()
    )

    # Quantity
    qty = deal.get("quantity") or deal.get("Quantity") or deal.get("QUANTITY") or deal.get("qty") or 0

    # Price
    price = deal.get("price") or deal.get("Price") or deal.get("PRICE") or deal.get("wgtAvgPrice") or 0

    # Date
    trade_date = deal.get("tradeDate") or deal.get("trade_date") or deal.get("TRADEDATE") or _ist_date_str()

    if not symbol or bs != "BUY" or not _is_institutional(client):
        return None

    return {
        "symbol": symbol,
        "client": client,
        "qty": int(qty) if qty else 0,
        "price": float(price) if price else 0.0,
        "trade_date": str(trade_date),
        "source": source,
    }


def _fetch_from_nse(session: requests.Session, source: str) -> list:
    """Fetch one endpoint (bulk or block) and return list of normalized dicts."""
    url_map = {
        "bulk": "https://www.nseindia.com/api/bulk-deals",
        "block": "https://www.nseindia.com/api/block-deals",
    }
    url = url_map[source]
    try:
        r = session.get(url, timeout=12)
        if r.status_code != 200:
            print(f"[BULK DEALS] {source} HTTP {r.status_code}")
            return []
        raw = r.json()
        rows = raw.get("data", raw) if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            return []
        deals = []
        for row in rows:
            d = _normalize_deal(row, source)
            if d:
                deals.append(d)
        print(f"[BULK DEALS] {source}: {len(deals)} institutional BUY deals")
        return deals
    except Exception as e:
        print(f"[BULK DEALS] {source} error: {e}")
        return []


def get_bulk_block_buys(force_refresh: bool = False) -> dict:
    """
    Fetch today's NSE bulk + block deals.
    Caches result for the day in bulk_deals_cache.json.
    Returns {SYMBOL: [list of deal dicts]}.
    """
    today = _ist_date_str()

    # ── Load cache if same day ────────────────────────────────────
    if not force_refresh and os.path.exists(_CACHE_FILE):
        try:
            with open(_CACHE_FILE, encoding="utf-8") as f:
                cache = json.load(f)
            if cache.get("date") == today:
                print(f"[BULK DEALS] Using cached data ({len(cache['deals'])} deals)")
                return _build_index(cache["deals"])
        except Exception:
            pass

    print("[BULK DEALS] Fetching fresh data from NSE...")
    session = _nse_session()
    all_deals = []
    all_deals.extend(_fetch_from_nse(session, "bulk"))
    time.sleep(1.0)
    all_deals.extend(_fetch_from_nse(session, "block"))

    # ── Save cache ────────────────────────────────────────────────
    try:
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"date": today, "deals": all_deals}, f, indent=2)
    except Exception as e:
        print(f"[BULK DEALS] Cache write failed: {e}")

    return _build_index(all_deals)


def _build_index(deals: list) -> dict:
    """Group deals by symbol."""
    idx: dict[str, list] = {}
    for d in deals:
        sym = d["symbol"]
        idx.setdefault(sym, []).append(d)
    return idx


def has_institutional_buy(symbol: str, bulk_index: dict, days: int = 3) -> dict:
    """
    Check if symbol has institutional BUY in last `days` trading days.
    Returns {"pass": bool, "deals": list, "latest_date": str}.
    """
    sym = symbol.upper().strip()
    deals = bulk_index.get(sym, [])
    if not deals:
        return {"pass": False, "deals": [], "latest_date": None, "buyers": []}

    buyers = list({d["client"] for d in deals})
    latest = max((d.get("trade_date", "") for d in deals), default="")
    total_qty = sum(d.get("qty", 0) for d in deals)

    return {
        "pass": True,
        "deals": deals,
        "latest_date": latest,
        "buyers": buyers[:3],  # top 3 buyer names
        "total_qty": total_qty,
    }
