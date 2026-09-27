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


"""Self-check for skill filtering, registry discovery, and Postgres storage/search."""
import sys
from pathlib import Path

# Run as a script, so the repo root has to go on sys.path before importing app.* - the package
# is not installed, it just sits at the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import skills
from app.core import db

TICKERS = [
    {"symbol": "AAA", "changePercent": 8.0, "volume": 1000, "avgVolume": 100},
    {"symbol": "BBB", "changePercent": 1.0, "volume": 1000, "avgVolume": 900},
]


def test_movement_skill():
    assert skills.load_skill("movement")(TICKERS) == [TICKERS[0]]


def test_volume_skill():
    assert skills.load_skill("volume")(TICKERS) == [TICKERS[0]]


def test_available_skills():
    assert {"movement", "volume"} <= set(skills.available_skills())


def test_db_roundtrip_and_search():
    db.init_schema()
    vec = [0.0] * 768
    vec[0] = 1.0
    db.insert_scraped_item("ZZZTEST", "## ZZZTEST\ntest report", vec)
    matches = db.similarity_search(vec, limit=1)
    assert matches[0]["symbol"] == "ZZZTEST"
    with db.connect() as conn:
        conn.execute("DELETE FROM scraped_items WHERE symbol = 'ZZZTEST'")


if __name__ == "__main__":
    test_movement_skill()
    test_volume_skill()
    test_available_skills()
    test_db_roundtrip_and_search()
    print("all checks passed")
