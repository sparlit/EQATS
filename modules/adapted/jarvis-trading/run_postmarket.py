"""15:35 IST — Post-market checklist (PDF + email + Telegram). Serverless entry-point."""
from __future__ import annotations

from dotenv import load_dotenv
load_dotenv(override=True)

from loguru import logger

from scheduler import run_post_market_summary


def main() -> None:
    logger.info("[jobs.run_postmarket] start")
    run_post_market_summary()
    logger.info("[jobs.run_postmarket] done")


if __name__ == "__main__":
    main()
