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


"""Market cap classification for Indian equities.

SEBI definitions (2024):
    Large Cap:  Top 100 by market cap (≥ ₹20,000 Cr typical)
    Mid Cap:    Rank 101-250 (₹5,000 – ₹20,000 Cr)
    Small Cap:  Rank 251+ (< ₹5,000 Cr)
    Micro Cap:  < ₹500 Cr
    SME:        NSE SME segment stocks (segment="SME") — overrides value-based class

Uses router fallback cascade: FinStack → Indian Market MCP → Free MCP → InvestorFeed → yfinance.
"""


import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# SEBI-style thresholds (in ₹ Cr)
LARGE_CAP_MIN = 20_000
MID_CAP_MIN = 5_000
SMALL_CAP_MIN = 1_000
# Below SMALL_CAP_MIN = Micro Cap

MCAP_FILE = Path("data/universe/market_cap.json")


def load_mcap_cache() -> dict[str, dict]:
    """Load cached market cap data from disk."""
    if MCAP_FILE.exists():
        try:
            return json.loads(MCAP_FILE.read_text())
        except Exception:
            pass
    return {}


def save_mcap_cache(data: dict[str, dict]) -> None:
    """Persist market cap cache to disk."""
    MCAP_FILE.parent.mkdir(parents=True, exist_ok=True)
    MCAP_FILE.write_text(json.dumps(data, indent=1, default=str))


def refresh_cache_from_investorfeed() -> int:
    """Pre-populate market cap cache from InvestorFeed API.

    Fetches all ~5,100 company profiles and adds them to the disk cache.
    Returns number of companies added.
    """
    try:
        from indian_quant.ingestion.web.investorfeed_client import InvestorFeedClient

        client = InvestorFeedClient(use_cache=True)
        profiles = client.fetch_all_profiles()

        cache = load_mcap_cache()
        added = 0

        for symbol, profile in profiles.items():
            mcap_cr = profile.get("mcap_cr")
            if mcap_cr is not None:
                mcap_cr = float(mcap_cr)

            # Add under both NSE and BSE keys
            for exchange in ["NSE", "BSE"]:
                key = f"{exchange}|{symbol}"
                if key not in cache or cache[key].get("market_cap_cr") is None:
                    cache[key] = {
                        "market_cap_cr": mcap_cr,
                        "market_cap_class": classify_by_value(mcap_cr),
                    }
                    added += 1

        save_mcap_cache(cache)
        logger.info("Refreshed cache from InvestorFeed: %d companies added", added)
        return added
    except Exception as e:
        logger.error("Failed to refresh cache from InvestorFeed: %s", e)
        return 0


def classify_by_value(mcap_cr: float | None) -> str:
    """Classify market cap tier from value in ₹ Cr."""
    if mcap_cr is None:
        return "Unknown"
    if mcap_cr >= LARGE_CAP_MIN:
        return "Large Cap"
    if mcap_cr >= MID_CAP_MIN:
        return "Mid Cap"
    if mcap_cr >= SMALL_CAP_MIN:
        return "Small Cap"
    return "Micro Cap"


def apply_sme_override(mcap_class: str, segment: str | None = None) -> str:
    """Override market_cap_class for SME-segment stocks.

    SME stocks are a distinct market segment on NSE, not classified by
    market cap thresholds.  If segment is 'SME', return 'SME' regardless
    of the value-based classification.
    """
    if segment and segment.upper() == "SME":
        return "SME"
    return mcap_class


def get_market_cap(
    router: Any, symbol: str, exchange: str = "NSE", cache: dict[str, dict] | None = None
) -> dict[str, Any]:
    """Fetch market cap for a symbol via router, with optional disk cache.

    Cascade: cache → router → InvestorFeed API → Unknown.
    Returns dict with keys: market_cap_cr, market_cap_class.
    """
    key = f"{exchange}|{symbol}"

    # Check cache first
    if cache and key in cache:
        entry = cache[key]
        return {
            "market_cap_cr": entry.get("market_cap_cr"),
            "market_cap_class": entry.get("market_cap_class", "Unknown"),
        }

    # Fetch from router
    mcap = router.get_market_cap(symbol)
    mcap_cr = None
    if mcap is not None:
        # Convert raw market cap (in ₹) to ₹ Cr
        if isinstance(mcap, (int, float)):
            mcap_cr = round(mcap / 1e7, 2)  # 1 Cr = 1e7
        elif isinstance(mcap, dict):
            raw = mcap.get("market_cap") or mcap.get("marketCap")
            if raw:
                mcap_cr = round(float(raw) / 1e7, 2)

    # Fallback: InvestorFeed API (covers ~5,100 companies)
    if mcap_cr is None:
        mcap_cr = _get_market_cap_from_investorfeed(symbol)

    result = {
        "market_cap_cr": mcap_cr,
        "market_cap_class": classify_by_value(mcap_cr),
    }

    # Update cache
    if cache is not None:
        cache[key] = result

    return result


def _get_market_cap_from_investorfeed(symbol: str) -> float | None:
    """Fallback: fetch market cap from InvestorFeed API."""
    try:
        from indian_quant.ingestion.web.investorfeed_client import InvestorFeedClient

        client = InvestorFeedClient(use_cache=True)
        profile = client.get_single_profile(symbol)
        if profile and profile.get("mcap_cr") is not None:
            return float(profile["mcap_cr"])
    except Exception as e:
        logger.debug("InvestorFeed fallback failed for %s: %s", symbol, e)
    return None


def classify_signals(signals: list[dict], router: Any | None = None) -> list[dict]:
    """Add market cap classification to all signals.

    Uses disk cache (pre-populated from InvestorFeed + previous runs).
    Only calls router for cache misses when no disk cache exists.
    SME-segment stocks get market_cap_class="SME" overriding value-based class.
    """
    cache = load_mcap_cache()
    has_cache = len(cache) > 0

    # Auto-refresh from InvestorFeed if cache is empty or stale
    if not has_cache:
        print("Market cap cache empty, refreshing from InvestorFeed...")
        refresh_cache_from_investorfeed()
        cache = load_mcap_cache()
        has_cache = len(cache) > 0

    fetched = 0
    cache_hits = 0
    cache_misses = 0

    for s in signals:
        symbol = s.get("symbol", "")
        exchange = s.get("exchange", "NSE")
        segment = s.get("segment", "EQ")
        key = f"{exchange}|{symbol}"

        # Try direct match first, then try the other exchange
        if key in cache:
            entry = cache[key]
            s["market_cap_cr"] = entry.get("market_cap_cr")
            s["market_cap_class"] = apply_sme_override(
                entry.get("market_cap_class", "Unknown"), segment
            )
            cache_hits += 1
        else:
            # Try other exchange (BSE stocks might be cached under BSE|symbol)
            other_key = f"BSE|{symbol}" if exchange == "NSE" else f"NSE|{symbol}"
            if other_key in cache:
                entry = cache[other_key]
                s["market_cap_cr"] = entry.get("market_cap_cr")
                s["market_cap_class"] = apply_sme_override(
                    entry.get("market_cap_class", "Unknown"), segment
                )
                cache_hits += 1
            elif cache and not has_cache:
                # Only call router if no disk cache exists (slow)
                info = get_market_cap(router, symbol, exchange, cache)
                s["market_cap_cr"] = info["market_cap_cr"]
                s["market_cap_class"] = apply_sme_override(info["market_cap_class"], segment)
                fetched += 1
            else:
                # Cache miss but cache file exists — mark Other (or SME)
                s["market_cap_cr"] = None
                s["market_cap_class"] = apply_sme_override("Other", segment)
                cache_misses += 1

    if fetched > 0:
        save_mcap_cache(cache)

    # Summary
    classes: dict[str, int] = {}
    for s in signals:
        cls = s.get("market_cap_class", "Unknown")
        classes[cls] = classes.get(cls, 0) + 1
    print(f"Market cap: {cache_hits} cached, {fetched} fetched, {cache_misses} misses")
    print(f"Distribution: {classes}")

    return signals
