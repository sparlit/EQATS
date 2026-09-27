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


"""Concall.in scraper using Playwright for API interception.

Concall.in is a React SPA that fetches data via api.concall.in.
Direct API calls fail (500) because they require cookies/headers set by the frontend.
Solution: Navigate with Playwright, intercept API responses.

Available API endpoints (discovered via interception):
  GET /leap/fetch/concalls?page=0&size=15&sector=All&marketCap=All
    → Earnings calendar with company events

  GET /leap/fetch/getCompanyDetails?companyId={finCode}
    → Company details: name, BSE code, NSE symbol, ISIN, sector, industry, financials

  GET /leap/fetch/getFinancialRatios?finCode={finCode}
    → ROE, ROCE, debt ratios, margins (standalone + consolidated)

  GET /leap/fetch/peers?finCode={finCode}
    → Peer comparison data

  GET /leap/fetch/getAllSectorNames
    → List of all sectors
"""


import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

CONCALL_BASE = "https://concall.in"
CONCALL_CALENDAR = f"{CONCALL_BASE}/concall-calendar/concalls"
CACHE_DIR = Path("data/cache/concall")
CACHE_TTL = 86400  # 24 hours


class ConcallScraper:
    """Scrapes concall.in using Playwright for API interception.

    Usage:
        scraper = ConcallScraper()
        cal = await scraper.get_earnings_calendar()
        details = await scraper.get_company_details(287237)
        ratios = await scraper.get_financial_ratios(287237)
    """

    def __init__(self, headless: bool = True, use_cache: bool = True):
        self.headless = headless
        self.use_cache = use_cache
        self.cache_dir = CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._intercepted: dict[str, Any] = {}

    async def _intercept_api(self, page, response):
        """Capture API responses from concall.in."""
        url = response.url
        if "api.concall.in" in url and response.status == 200:
            try:
                body = await response.json()
                # Store by endpoint path
                path = url.split("api.concall.in")[-1].split("?")[0]
                self._intercepted[path] = {"url": url, "body": body}
            except Exception:
                pass

    async def _navigate_and_collect(self, url: str, wait: float = 3.0) -> dict[str, Any]:
        """Navigate to a page and collect API responses."""
        from playwright.async_api import async_playwright

        self._intercepted.clear()

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            page = await browser.new_page()
            page.on("response", lambda r: asyncio.ensure_future(self._intercept_api(page, r)))

            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(wait)

            await browser.close()

        return self._intercepted

    def _get_cache(self, key: str) -> dict | None:
        if not self.use_cache:
            return None
        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists():
            age = time.time() - cache_file.stat().st_mtime
            if age < CACHE_TTL:
                return json.loads(cache_file.read_text())
        return None

    def _save_cache(self, key: str, data: Any) -> None:
        if not self.use_cache:
            return
        cache_file = self.cache_dir / f"{key}.json"
        cache_file.write_text(json.dumps(data, indent=2, default=str))

    async def get_earnings_calendar(self, page: int = 0, size: int = 50, sector: str = "All") -> list[dict]:
        """Get earnings call calendar.

        Returns list of company events with:
          finCode, companyName, dateTime, title, type
        """
        cache_key = f"calendar_{sector}_{page}_{size}"
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        url = f"{CONCALL_CALENDAR}?page={page}&size={size}&sector={sector}&marketCap=All"
        api = await self._navigate_and_collect(url)

        events = []
        concalls_data = api.get("/leap/fetch/concalls", {}).get("body", {})
        for date_entry in concalls_data.get("content", []):
            for date_info in date_entry.get("eventsWithDate", []):
                dt = date_info.get("dateTime", "")
                for ev in date_info.get("eventList", []):
                    events.append(
                        {
                            "fin_code": ev.get("finCode"),
                            "company_name": ev.get("companyName", ""),
                            "date_time": ev.get("dateTime", dt),
                            "title": ev.get("title", ""),
                            "type": ev.get("type", ""),
                        }
                    )

        self._save_cache(cache_key, events)
        log.info("Fetched %d concall events", len(events))
        return events

    async def get_company_details(self, fin_code: int) -> dict | None:
        """Get company details from concall.in.

        Returns dict with:
          company_name, short_name, bse_code, nse_symbol, isin,
          sector, industry, standalone_key_details, consolidated_key_details,
          ttm_data, financial_statements, concall_events, resources
        """
        cache_key = f"company_{fin_code}"
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        # Navigate to company page to trigger API calls
        url = f"{CONCALL_BASE}/company/{fin_code}/analysis/financials"
        api = await self._navigate_and_collect(url, wait=4.0)

        # Extract company details
        details_data = api.get("/leap/fetch/getCompanyDetails", {}).get("body")
        ratios_data = api.get("/leap/fetch/getFinancialRatios", {}).get("body")
        peers_data = api.get("/leap/fetch/peers", {}).get("body")

        if not details_data:
            log.warning("No company details found for finCode=%d", fin_code)
            return None

        result = {
            "fin_code": fin_code,
            "company_name": details_data.get("companyName", ""),
            "short_name": details_data.get("companyShortName", ""),
            "bse_code": details_data.get("bseScripCode", ""),
            "nse_symbol": details_data.get("nseSymbol", ""),
            "isin": details_data.get("isin", ""),
            "sector": details_data.get("sector", ""),
            "industry": details_data.get("industry", ""),
            "standalone_key_details": details_data.get("standaloneKeyDetails", []),
            "consolidated_key_details": details_data.get("consolidatedKeyDetails", []),
            "standalone_result_summary": details_data.get("standaloneResultSummaryMap", {}),
            "consolidated_result_summary": details_data.get("consolidatedResultSummaryMap", {}),
            "ttm_standalone": details_data.get("ttmStandalone", {}),
            "ttm_consolidated": details_data.get("ttmConsolidated", {}),
            "financial_ratios": ratios_data,
            "peers": peers_data,
            "events": details_data.get("mapOfEvents", {}),
            "resources": details_data.get("resourceMap", {}),
        }

        self._save_cache(cache_key, result)
        log.info("Fetched company details for %s (finCode=%d)", result["company_name"], fin_code)
        return result

    async def get_financial_ratios(self, fin_code: int) -> dict | None:
        """Get financial ratios for a company.

        Returns dict with standaloneRatios and consolidatedRatios.
        Each ratio has: name, values (dateEnd, value, unit).
        """
        details = await self.get_company_details(fin_code)
        if details:
            return details.get("financial_ratios")
        return None

    async def get_peer_comparison(self, fin_code: int) -> dict | None:
        """Get peer comparison data."""
        details = await self.get_company_details(fin_code)
        if details:
            return details.get("peers")
        return None

    async def search_companies(self, query: str) -> list[dict]:
        """Search for companies by name or symbol.

        Navigates to concall.in and uses the search functionality.
        """
        from playwright.async_api import async_playwright

        results = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            page = await browser.new_page()

            await page.goto(CONCALL_BASE, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            # Try to find and use search input
            try:
                search_input = await page.query_selector(
                    'input[type="search"], input[placeholder*="search" i], input[placeholder*="company" i]'
                )
                if search_input:
                    await search_input.fill(query)
                    await asyncio.sleep(2)
                    # Get autocomplete results
                    await page.inner_text("body")
                    # Parse results from the page
            except Exception as e:
                log.debug("Search failed: %s", e)

            await browser.close()

        return results

    async def get_all_sectors(self) -> list[str]:
        """Get list of all sectors from concall.in."""
        cache_key = "sectors"
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        url = CONCALL_CALENDAR
        api = await self._navigate_and_collect(url)

        sectors_data = api.get("/leap/fetch/getAllSectorNames", {}).get("body", [])
        if isinstance(sectors_data, list):
            self._save_cache(cache_key, sectors_data)
            return sectors_data

        return []
