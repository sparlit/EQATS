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


import json

from fastapi import APIRouter

from app.core import db, scraper
from app.schemas import ScrapeRequest

router = APIRouter(tags=["system"])


@router.post("/api/cache/clear")
def clear_cache():
    db.clear_cache()
    return {"ok": True}


SCRAPE_OUTPUT_FILE = "local_data/scraped.json"


@router.post("/api/scrape")
def scrape_url(req: ScrapeRequest):
    """Scrapes an arbitrary URL's HTML (requests + BeautifulSoup, via scraper.scrape_article)
    and writes {url, title, text} to one JSON file, overwritten each call."""
    data = {"url": req.url, **scraper.scrape_article(req.url)}
    with open(SCRAPE_OUTPUT_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return data
