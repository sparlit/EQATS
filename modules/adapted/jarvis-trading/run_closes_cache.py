"""Write data/closes_cache.json — universe daily closes for the Pattern Finder (runs in GitHub Actions)."""
from __future__ import annotations

import warnings
warnings.simplefilter("ignore", FutureWarning)

from dotenv import load_dotenv
load_dotenv(override=True)

from loguru import logger

from data.closes import build_closes_cache


def main() -> None:
    logger.info("[jobs.run_closes_cache] building universe closes cache…")
    build_closes_cache()
    logger.success("[jobs.run_closes_cache] done")


if __name__ == "__main__":
    main()
