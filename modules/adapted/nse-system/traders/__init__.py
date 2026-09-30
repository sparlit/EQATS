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
Traders registry — each module declares:
  SLUG, NAME, PILLAR, SOURCE, METHODS, scan(conn, limit)
"""

from traders import (
    apurva_parikh,
    chande,
    ishaan_agnihotri,
    john_crane,
    larry_spears,
    mcallen,
    nison,
    oneil,
    oshaughnessy,
    quantitative_value,
    seven_simple_strategies,
    singhal,
    value_investing_made_easy,
    way_of_the_turtle,
)

REGISTRY = [
    john_crane,
    larry_spears,
    oshaughnessy,
    quantitative_value,
    value_investing_made_easy,
    way_of_the_turtle,
    seven_simple_strategies,
    apurva_parikh,
    ishaan_agnihotri,
    nison,
    chande,
    oneil,
    mcallen,
    singhal,
]


def list_traders():
    return [
        {
            "slug": t.SLUG,
            "name": t.NAME,
            "pillar": t.PILLAR,
            "source": t.SOURCE,
            "methods": t.METHODS,
        }
        for t in REGISTRY
    ]


def get_trader(slug):
    for t in REGISTRY:
        if slug == t.SLUG:
            return t
    return None
