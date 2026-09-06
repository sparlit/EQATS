"""
Logging — daily file + console.

Usage:
    from utils.logger import get_logger
    log = get_logger("oi_collector")
    log.info("message")
"""

import logging
import sys
import os
from datetime import datetime
from pathlib import Path


_setup_done = False


def setup_logging(log_dir: str = None, process_name: str = "collector") -> None:
    """One-time setup: root logger with console + daily file handlers."""
    global _setup_done
    if _setup_done:
        return

    if log_dir is None:
        log_dir = str(Path(__file__).parent.parent / "logs")
    os.makedirs(log_dir, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if sys.platform == "win32":
        stream = open(sys.stdout.fileno(), mode="w", encoding="utf-8", closefd=False)
    else:
        stream = sys.stdout

    console = logging.StreamHandler(stream=stream)
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    root.addHandler(console)

    log_file = os.path.join(log_dir, f"{process_name}_{datetime.now().strftime('%Y%m%d')}.log")
    file_h = logging.FileHandler(log_file, encoding="utf-8")
    file_h.setLevel(logging.DEBUG)
    file_h.setFormatter(fmt)
    root.addHandler(file_h)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    _setup_done = True


def get_logger(name: str) -> logging.Logger:
    """Get a named logger. Auto-calls setup_logging() on first use."""
    if not _setup_done:
        setup_logging()
    return logging.getLogger(name)
