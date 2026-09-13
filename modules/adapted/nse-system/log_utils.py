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


"""
Simple file + console logger for the NSE system.
Writes to data/logs/nse.log (rotated daily, 14 days kept) and prints to stdout.
"""
import logging
import os
from logging.handlers import TimedRotatingFileHandler

LOG_DIR = os.path.join("data", "logs")
_LOGGERS = {}


def get_logger(name="nse"):
    """Return a configured logger. Safe to call multiple times."""
    if name in _LOGGERS:
        return _LOGGERS[name]
    os.makedirs(LOG_DIR, exist_ok=True)
    logger = logging.getLogger(name)
    if logger.handlers:
        _LOGGERS[name] = logger
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    fh = TimedRotatingFileHandler(
        os.path.join(LOG_DIR, f"{name}.log"), when="midnight", backupCount=14, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    _LOGGERS[name] = logger
    return logger
