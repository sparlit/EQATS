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


"""BSE quarterly shareholding pattern ingestion.

Fetches promoter/FII/DII/public shareholding data from BSE India's API.
The API returns HTML which is parsed with BeautifulSoup.

BSE API endpoint:
    GET https://api.bseindia.com/BseIndiaAPI/api/shpSecSummery_New/w
    ?qtrid=&scripcode={BSE_SCRIP_CODE}

Args:
    scripcode: BSE numeric scrip code (e.g., 500325 for RELIANCE)
    qtrid: Quarter ID (empty string = latest quarter)

Returns HTML containing shareholding summary table with columns:
    - Category of shareholders (Promoter, FII, DII, Public)
    - Number of shares / % holding (current + previous quarter)

BSE's CDN may block datacenter IPs. Falls back to returning None on failure.
"""


import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BSE_API_URL = "https://api.bseindia.com/BseIndiaAPI/api/shpSecSummery_New/w"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.bseindia.com/",
    "Origin": "https://www.bseindia.com",
}

# BSE shareholder category names -> our column mapping
CATEGORY_MAP = {
    "promoter": "promoter",
    "promoters": "promoter",
    "foreign institutional investors": "fii",
    "fii": "fii",
    "domestic institutional investors": "dii",
    "dii": "dii",
    "mutual funds": "dii",
    "insurance companies": "dii",
    "public": "public",
    "public shareholders": "public",
    "others": "public",
}


def fetch_shareholding_html(scripcode: str, timeout: float = 15.0) -> str | None:
    """Fetch raw HTML from BSE shareholding API."""
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(
                BSE_API_URL,
                params={"qtrid": "", "scripcode": scripcode},
                headers=HEADERS,
            )
            if resp.status_code != 200:
                logger.warning("BSE shareholding HTTP %d for %s", resp.status_code, scripcode)
                return None

            text = resp.text
            # Check for CDN block page
            if "access denied" in text.lower() or "blocked" in text.lower():
                logger.warning("BSE shareholding CDN block for %s", scripcode)
                return None

            return text
    except Exception as e:
        logger.warning("BSE shareholding fetch failed for %s: %s", scripcode, e)
        return None


def parse_shareholding_html(html: str) -> dict[str, Any] | None:
    """Parse BSE shareholding HTML into structured data.

    The BSE summary endpoint provides:
        - Promoter & Promoter Group %
        - Public %
        - Non Promoter-Non Public %
        - Quarter ending date

    FII/DII breakdown requires a different endpoint (not available in summary).
    We set fii_pct/dii_pct to NULL and rely on the promoter_pct for scoring.

    Returns dict with keys:
        quarter: str (e.g., "2024-Q3")
        promoter_pct: float
        fii_pct: float (None - not available from summary endpoint)
        dii_pct: float (None - not available from summary endpoint)
        public_pct: float
        promoter_chg: float (None - not available from summary endpoint)
        fii_chg: float (None)
        dii_chg: float (None)
    """
    try:
        soup = BeautifulSoup(html, "lxml")
        tables = soup.find_all("table")
        if not tables:
            return None

        result = {
            "quarter": "",
            "promoter_pct": None,
            "fii_pct": None,
            "dii_pct": None,
            "public_pct": None,
            "promoter_chg": None,
            "fii_chg": None,
            "dii_chg": None,
        }

        # Extract quarter from the page
        all_text = soup.get_text(" ")
        q_match = re.search(r"[Qq]uarter\s+ending\s*:?\s*(\w+\s+\d{4})", all_text)
        if q_match:
            raw = q_match.group(1).strip()
            # Convert "June 2026" -> "2026-Q2"
            month_map = {
                "january": "Q1",
                "february": "Q1",
                "march": "Q1",
                "april": "Q2",
                "may": "Q2",
                "june": "Q2",
                "july": "Q3",
                "august": "Q3",
                "september": "Q3",
                "october": "Q4",
                "november": "Q4",
                "december": "Q4",
            }
            parts = raw.lower().split()
            if len(parts) >= 2:
                month = parts[0]
                year = parts[-1]
                qtr = month_map.get(month, "")
                if qtr:
                    result["quarter"] = f"{year}-{qtr}"

        # Find the summary table (the one with "Category of shareholder")
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all("td")
                if len(cells) < 5:
                    continue

                cat_text = cells[0].get_text(strip=True).lower()
                # The percentage column is typically index 5 (Shareholding as a %)
                # Skip indices 1-4 (shareholder count, shares, DRs, total)
                pct_val = None
                for idx in range(5, min(len(cells), 8)):
                    txt = cells[idx].get_text(strip=True).replace(",", "").replace("%", "")
                    try:
                        val = float(txt)
                        if 0 <= val <= 100:
                            pct_val = val
                            break
                    except (ValueError, TypeError):
                        continue

                if pct_val is None:
                    continue

                if "promoter" in cat_text and "non promoter" not in cat_text:
                    result["promoter_pct"] = pct_val
                elif "public" in cat_text and "non promoter" not in cat_text:
                    result["public_pct"] = pct_val

        # Check if we got any data
        if result["promoter_pct"] is None and result["public_pct"] is None:
            return None

        return result

    except Exception as e:
        logger.warning("BSE shareholding parse failed: %s", e)
        return None


def fetch_shareholding(scripcode: str) -> dict[str, Any] | None:
    """Fetch and parse BSE shareholding pattern for a stock.

    Args:
        scripcode: BSE numeric scrip code (e.g., "500325")

    Returns:
        dict with quarter, promoter_pct, fii_pct, dii_pct, public_pct,
        promoter_chg, fii_chg, dii_chg — or None on failure.
    """
    html = fetch_shareholding_html(scripcode)
    if html is None:
        return None
    return parse_shareholding_html(html)


def fetch_shareholding_batch(
    scripcodes: list[str], delay: float = 0.5
) -> dict[str, dict[str, Any]]:
    """Fetch shareholding for multiple stocks with rate limiting.

    Args:
        scripcodes: List of BSE scrip codes
        delay: Seconds between requests (be nice to BSE)

    Returns:
        Dict mapping scripcode -> shareholding data
    """
    results = {}
    import time

    for i, code in enumerate(scripcodes):
        data = fetch_shareholding(code)
        if data is not None:
            results[code] = data
        if i < len(scripcodes) - 1:
            time.sleep(delay)

    return results
