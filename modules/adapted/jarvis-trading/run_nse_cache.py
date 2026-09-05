"""
Write data/nse_cache.json from NSE (FII/DII + corporate events).

Runs in GitHub Actions, where NSE is reachable. The deployed backend (on a
datacenter IP NSE blocks) reads this committed cache instead.
"""
from __future__ import annotations

from dotenv import load_dotenv
load_dotenv(override=True)

from loguru import logger

from data.econ_calendar import fetch_corporate_events
from data.fii_dii import fetch_fii_dii
from data.nse_cache import write_cache


def main() -> None:
    logger.info("[jobs.run_nse_cache] fetching NSE data for cache…")
    fii = fetch_fii_dii()
    corp = fetch_corporate_events(days_ahead=21, limit=20)
    write_cache(fii, corp)
    logger.success("NSE cache: FII/DII available={} · {} corporate events",
                   fii.get("available"), len(corp))


if __name__ == "__main__":
    main()
