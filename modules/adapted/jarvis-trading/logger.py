from __future__ import annotations

from loguru import logger


def configure_logger(log_path: str | None = None) -> None:
    """Configure loguru logger for the project."""
    logger.remove()
    logger.add("stderr", level="INFO")
    if log_path:
        logger.add(log_path, rotation="10 MB", retention="10 days", compression="zip")


logger.configure(handlers=[{"sink": "stderr", "level": "INFO"}])
