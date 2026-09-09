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
Write data/nse_cache.json from NSE (FII/DII + corporate events).

Runs in GitHub Actions, where NSE is reachable. The deployed backend (on a
datacenter IP NSE blocks) reads this committed cache instead.
"""

from dotenv import load_dotenv

load_dotenv(override=True)

from data.econ_calendar import fetch_corporate_events
from data.fii_dii import fetch_fii_dii
from data.nse_cache import write_cache
from loguru import logger


def main() -> None:
    logger.info("[jobs.run_nse_cache] fetching NSE data for cache…")
    fii = fetch_fii_dii()
    corp = fetch_corporate_events(days_ahead=21, limit=20)
    write_cache(fii, corp)
    logger.success("NSE cache: FII/DII available={} · {} corporate events", fii.get("available"), len(corp))


if __name__ == "__main__":
    main()
