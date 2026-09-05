"""09:15 IST — Pre-market task checklist (PDF + email + Telegram). Serverless entry-point."""
from __future__ import annotations

from dotenv import load_dotenv
load_dotenv(override=True)

from loguru import logger

from scheduler import run_premarket_tasks


def main() -> None:
    logger.info("[jobs.run_premarket] start")
    run_premarket_tasks()
    logger.info("[jobs.run_premarket] done")


if __name__ == "__main__":
    main()
