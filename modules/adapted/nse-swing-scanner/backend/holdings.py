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
holdings.py
Promoter / FII / DII shareholding percentages from Screener.in.

Resolution chain:
  1. https://www.screener.in/company/{SYMBOL}/consolidated/
  2. https://www.screener.in/company/{SYMBOL}/  (standalone fallback)

We scrape with a polite delay and use the on-disk cache aggressively
(shareholding changes quarterly, so a 90-day cache is reasonable).

Screener does not have an official public API; this is best-effort HTML
parsing. If their page structure changes, callers should see
"source_failed" or "missing" statuses and the scanner will flag rows
without holdings data rather than silently pass them.
"""

import re
import time
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup
from cache import read_cache, write_cache
from settings import HOLDINGS_CACHE_TTL_SECONDS
from source_status import make_status

SCREENER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.screener.in/",
}


def _scrape_screener(symbol: str, consolidated: bool = True, timeout: int = 15) -> BeautifulSoup | None:
    if consolidated:
        url = f"https://www.screener.in/company/{symbol.upper()}/consolidated/"
    else:
        url = f"https://www.screener.in/company/{symbol.upper()}/"
    try:
        resp = requests.get(url, headers=SCREENER_HEADERS, timeout=timeout)
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    try:
        return BeautifulSoup(resp.text, "html.parser")
    except Exception:
        return None


def _parse_shareholding_table(soup: BeautifulSoup) -> dict[str, dict] | None:
    """
    Screener's Shareholding Pattern section is a table with rows for Promoters,
    FIIs, DIIs, Government, Public, etc. The latest quarter is the first column.
    """
    # Find the section anchor
    section = soup.find(id="shareholding")
    if section is None:
        return None
    table = section.find("table", class_="data-table")
    if table is None:
        # Fallback: any table after the anchor
        table = section.find("table")
    if table is None:
        return None

    headers: list[str] = []
    thead = table.find("thead")
    if thead is not None:
        first_row = thead.find("tr")
        if first_row is not None:
            for th in first_row.find_all("th"):
                headers.append(th.get_text(strip=True))

    # If no thead, infer latest quarter as the first td of the first tbody row
    rows = table.find("tbody")
    if rows is None:
        return None

    result: dict[str, dict] = {}
    for tr in rows.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all("td")]
        if not cells:
            continue
        # First cell is the label, rest are quarter columns
        label = cells[0].lower()
        if not label or "no. of shareholders" in label or label == "shareholders":
            continue
        # We need the most recent quarter — that's the rightmost (or first if no headers).
        # Screener columns are ordered oldest -> newest left to right.
        if len(cells) >= 2:
            # Get the latest quarter value
            latest_text = cells[-1]
            m = re.search(r"-?[\d\.]+", latest_text)
            if m:
                val = float(m.group(0))
            else:
                continue
            # Try to also pick the second-to-last to be a sanity check
            if len(cells) >= 3:
                prev_text = cells[-2]
                mp = re.search(r"-?[\d\.]+", prev_text)
                prev_val = float(mp.group(0)) if mp else None
            else:
                prev_val = None
            result[label] = {
                "latest_pct": val,
                "prev_pct": prev_val,
            }
    return result or None


def _best_pct(parsed: dict[str, dict], key_match: str) -> float | None:
    """Pick the best-matching row in a parsed shareholding dict."""
    for label, vals in parsed.items():
        if key_match in label:
            return vals.get("latest_pct")
    return None


def fetch_holdings(symbol: str, *, sleep_between: float = 0.2) -> dict:
    """
    Returns a source_status dict for a single symbol.
    """
    cache_key = f"holdings:{symbol.upper()}"
    cached = read_cache(cache_key, max_age_seconds=HOLDINGS_CACHE_TTL_SECONDS)
    if cached is not None:
        return cached

    soup = _scrape_screener(symbol, consolidated=True)
    used_fallback = False
    if soup is None:
        soup = _scrape_screener(symbol, consolidated=False)
        used_fallback = True

    if soup is None:
        result = make_status(
            source="screener.in",
            status="source_failed",
            error="screener fetch failed",
        )
        write_cache(cache_key, result)
        return result

    parsed = _parse_shareholding_table(soup)
    if parsed is None:
        result = make_status(
            source=f"screener.in({'standalone' if used_fallback else 'consolidated'})",
            status="missing",
            error="shareholding table not found",
        )
        write_cache(cache_key, result)
        return result

    promoter = _best_pct(parsed, "promoter")
    fii = _best_pct(parsed, "fii")
    dii = _best_pct(parsed, "dii")

    if promoter is None and fii is None and dii is None:
        result = make_status(
            source=f"screener.in({'standalone' if used_fallback else 'consolidated'})",
            status="missing",
            error="no promoter/fii/dii rows parsed",
        )
        write_cache(cache_key, result)
        return result

    conviction = sum(v for v in (promoter, fii, dii) if v is not None)
    data = {
        "promoter_pct": promoter,
        "fii_pct": fii,
        "dii_pct": dii,
        "conviction_pct": conviction,
    }
    result = make_status(
        source=f"screener.in({'standalone' if used_fallback else 'consolidated'})",
        status="fallback_used" if used_fallback else "ok",
        data=data,
    )
    write_cache(cache_key, result)
    # Be polite; Screener is a free site.
    time.sleep(sleep_between)
    return result
