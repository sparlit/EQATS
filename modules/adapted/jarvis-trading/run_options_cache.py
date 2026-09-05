"""Write data/options_cache.json from Moneycontrol option chains (runs on a residential PC via Task Scheduler)."""
from __future__ import annotations

import warnings
warnings.simplefilter("ignore", FutureWarning)  # quiet yfinance/pandas chained-assignment + read_html noise

from dotenv import load_dotenv
load_dotenv(override=True)

from loguru import logger

from data.options import write_cache


def main() -> None:
    logger.info("[jobs.run_options_cache] fetching Moneycontrol option chains…")
    write_cache()
    logger.success("[jobs.run_options_cache] done")


if __name__ == "__main__":
    main()
