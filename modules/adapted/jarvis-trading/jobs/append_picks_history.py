from __future__ import annotations

import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytz

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

WATCHLIST = Path("data/watchlist.csv")
HISTORY = Path("data/picks_history.json")
IST = ZoneInfo("Asia/Kolkata")


def is_ist_market_session_active(dt: datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.now(ist)
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


def main() -> None:
    if not WATCHLIST.exists():
        logger.warning("No watchlist.csv — nothing to append")
        return
    today = datetime.now(IST).strftime("%Y-%m-%d")
    try:
        data = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else {"history": {}}
    except Exception:
        data = {"history": {}}
    with WATCHLIST.open() as f:
        rows = [
            {
                "symbol": r["symbol"].replace(".NS", ""),
                "grade": r.get("grade", ""),
                "score": float(r["score"]) if r.get("score") else None,
            }
            for r in csv.DictReader(f)
            if r.get("symbol")
        ][:25]
    if not rows:
        logger.warning("Empty watchlist — skipping")
        return
    data["history"][today] = rows
    # keep last ~250 trading days
    keys = sorted(data["history"].keys())
    for k in keys[:-250]:
        del data["history"][k]
    HISTORY.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    logger.info("Picks history: %d dates (added %s with %d picks)", len(data["history"]), today, len(rows))


if __name__ == "__main__":
    main()
