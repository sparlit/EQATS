"""08:30 IST — Morning briefing (PDF + email + Telegram). Serverless entry-point."""
from __future__ import annotations

from dotenv import load_dotenv
load_dotenv(override=True)

from loguru import logger

from scheduler import run_morning_briefing


def main() -> None:
    logger.info("[jobs.run_briefing] start")
    run_morning_briefing()
    logger.info("[jobs.run_briefing] done")


if __name__ == "__main__":
    main()
