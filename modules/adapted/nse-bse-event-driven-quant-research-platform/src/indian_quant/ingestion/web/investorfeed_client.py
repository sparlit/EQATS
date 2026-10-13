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


"""InvestorFeed.in data client.

Fetches market cap, P/E, P/B, ROE, sector from investorfeed.in API.
API endpoint: GET /api/profiles?limit=N&offset=N

Returns ~5,114 companies with attributes:
  - mcap (market cap in Cr)
  - pe_ratio
  - pb (price-to-book)
  - roe (return on equity %)
  - sector
  - subsector
"""


import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

BASE_URL = "https://investorfeed.in/api"
PROFILES_URL = f"{BASE_URL}/profiles"

# Cache TTL: 24 hours (market cap changes daily)
CACHE_TTL = 86400
CACHE_DIR = Path("data/cache/investorfeed")


class InvestorFeedClient:
    """Client for InvestorFeed.in API.

    Fetches all company profiles with market cap, P/E, P/B, ROE, sector.
    Supports caching to avoid repeated API calls.
    """

    def __init__(self, cache_dir: Path | str | None = None, use_cache: bool = True):
        self.cache_dir = Path(cache_dir) if cache_dir else CACHE_DIR
        self.use_cache = use_cache
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_path(self) -> Path:
        return self.cache_dir / "profiles.json"

    def _is_cache_valid(self) -> bool:
        cache_path = self._get_cache_path()
        if not cache_path.exists():
            return False
        age = time.time() - cache_path.stat().st_mtime
        return age < CACHE_TTL

    def _load_cache(self) -> dict[str, dict]:
        cache_path = self._get_cache_path()
        if not cache_path.exists():
            return {}
        with open(cache_path) as f:
            data = json.load(f)
        log.info("Loaded %d profiles from cache", len(data))
        return data

    def _save_cache(self, profiles: dict[str, dict]) -> None:
        cache_path = self._get_cache_path()
        with open(cache_path, "w") as f:
            json.dump(profiles, f, indent=2, default=str)
        log.info("Saved %d profiles to cache", len(profiles))

    def fetch_all_profiles(self, batch_size: int = 10000) -> dict[str, dict]:
        """Fetch all company profiles from InvestorFeed API.

        Returns dict keyed by symbol:
        {
            "RELIANCE": {
                "symbol": "RELIANCE",
                "title": "Reliance Industries Ltd",
                "bse_id": "500325",
                "isin": "INE002A01018",
                "mcap_cr": 180000.0,
                "pe_ratio": 28.5,
                "pb": 2.1,
                "roe": 9.8,
                "sector": "Oil & Gas",
                "subsector": "Refining",
                "profile_slug": "reliance-industries-ltd-xxx",
            }
        }
        """
        if self.use_cache and self._is_cache_valid():
            return self._load_cache()

        log.info("Fetching all profiles from InvestorFeed API...")
        all_profiles: dict[str, dict] = {}
        offset = 0
        total = 0

        with httpx.Client(timeout=60) as client:
            while True:
                resp = client.get(
                    PROFILES_URL,
                    params={"limit": batch_size, "offset": offset},
                )
                resp.raise_for_status()
                data = resp.json()

                if not data:
                    break

                for item in data:
                    meta = item.get("meta_attributes", {})
                    attrs = item.get("attributes", {})
                    symbol = meta.get("symbol", "")

                    if not symbol:
                        continue

                    profile = {
                        "symbol": symbol,
                        "title": item.get("title", ""),
                        "bse_id": meta.get("company_bse_id", ""),
                        "isin": meta.get("isin", ""),
                        "mcap_cr": attrs.get("mcap"),
                        "pe_ratio": attrs.get("pe_ratio"),
                        "pb": attrs.get("pb"),
                        "roe": attrs.get("roe"),
                        "sector": attrs.get("sector", ""),
                        "subsector": attrs.get("subsector", ""),
                        "profile_slug": item.get("profile_slug", ""),
                        "if_id": item.get("id"),
                    }
                    all_profiles[symbol] = profile

                total += len(data)
                log.info("Fetched %d profiles (offset=%d)", total, offset)

                if len(data) < batch_size:
                    break
                offset += batch_size

        log.info("Total profiles fetched: %d", len(all_profiles))

        if self.use_cache and all_profiles:
            self._save_cache(all_profiles)

        return all_profiles

    def get_market_cap_batch(self, symbols: list[str] | None = None) -> dict[str, dict]:
        """Get market cap data for symbols.

        Args:
            symbols: List of symbols to fetch. None = all.

        Returns:
            Dict keyed by symbol with market cap data.
        """
        profiles = self.fetch_all_profiles()

        if symbols is None:
            return profiles

        # Filter to requested symbols
        result = {}
        for sym in symbols:
            sym_upper = sym.upper()
            if sym_upper in profiles:
                result[sym_upper] = profiles[sym_upper]
        return result

    def get_single_profile(self, symbol: str) -> dict | None:
        """Get profile for a single symbol."""
        profiles = self.fetch_all_profiles()
        return profiles.get(symbol.upper())

    def discover_api_endpoints(self) -> dict[str, Any]:
        """Discover and document available API endpoints."""
        endpoints = {
            "profiles": {
                "url": PROFILES_URL,
                "params": {"limit": "int", "offset": "int", "symbol": "str"},
                "description": "List all company profiles with market cap, P/E, P/B, ROE, sector",
                "total_items": 5114,
            },
            "feeds_public_posts": {
                "url": f"{BASE_URL}/feeds/public/posts",
                "params": {"limit": "int", "offset": "int"},
                "description": "Public feed with company announcements",
            },
            "feeds_public_config": {
                "url": f"{BASE_URL}/feeds/public/config",
                "description": "Feed configuration",
            },
            "filters_config": {
                "url": f"{BASE_URL}/filters/config",
                "description": "Available filters for feed",
            },
        }
        return endpoints
