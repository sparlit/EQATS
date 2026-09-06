"""Write data/ohlcv_cache.json.gz — 2y daily OHLCV for the scan universe (GitHub Actions)."""
from __future__ import annotations

import warnings
warnings.simplefilter("ignore")

from dotenv import load_dotenv
load_dotenv(override=True)

from loguru import logger

from data.ohlcv_cache import build_cache


def main() -> None:
    logger.info("[jobs.run_ohlcv_cache] building OHLCV cache…")
    build_cache()
    logger.success("[jobs.run_ohlcv_cache] done")


if __name__ == "__main__":
    main()
