import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


# logger.py
import logging
from datetime import datetime
from pathlib import Path

# Create log file ONCE
_current_date = datetime.now().strftime("%Y-%m-%d")
_current_timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

LOG_DIR = Path("logs") / _current_date
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / f"{_current_timestamp}.log"

_LOGGING_CONFIGURED = False


def get_logger(name: str = __name__) -> logging.Logger:
    global _LOGGING_CONFIGURED

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if not _LOGGING_CONFIGURED:
        formatter = logging.Formatter(
            "[%(asctime)s]: %(name)s: %(levelname)s: %(lineno)d: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARNING)
        console_handler.setFormatter(formatter)

        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)

        _LOGGING_CONFIGURED = True

    return logger
