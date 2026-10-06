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


"""Helpers for identifying and timestamping locally supplied source files."""

from datetime import datetime
from hashlib import sha256
from pathlib import Path


def file_metadata(path):
    """Return an artifact's content hash and local modification timestamp."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Source artifact does not exist: {path}")

    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)

    modified_at = (
        datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    )
    return {
        "sha256": digest.hexdigest(),
        "modified_at": modified_at,
        "file_name": path.name,
    }
