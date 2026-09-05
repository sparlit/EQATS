"""Write data/fundamentals_cache.json.gz — universe company fundamentals (GitHub Actions nightly)."""
from __future__ import annotations

import warnings
warnings.simplefilter("ignore")

from dotenv import load_dotenv
load_dotenv(override=True)

from loguru import logger

from data.fundamentals_cache import build_fundamentals_cache


def main() -> None:
    logger.info("[jobs.run_fundamentals_cache] building fundamentals cache…")
    build_fundamentals_cache()
    logger.success("[jobs.run_fundamentals_cache] done")


if __name__ == "__main__":
    main()
