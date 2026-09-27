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


"""Scans watchlisted symbols for news/price/volume/corporate-action events - no LLM, cheap+fast."""
from datetime import date

from app import skills
from app.core import classifier, db, scraper, sentiment

_movement = skills.load_skill("movement")  # reuse |%change| >= 5 threshold
_volume = skills.load_skill("volume")  # reuse volume >= 2x avg threshold


def scan_symbol(symbol):
    """Returns count of new events inserted for one symbol. Lets exceptions propagate -
    scan() isolates failures per-symbol."""
    inserted = 0

    for item in scraper.get_news(symbol):
        if not item["url"]:
            continue
        score = sentiment.analyze(f"{item['title']}. {item['summary']}")
        if db.insert_event(
            symbol,
            "news",
            item["url"],
            item["title"],
            item["summary"],
            item["url"],
            item["published_at"],
            score["label"],
            score["score"],
        ):
            inserted += 1

    quote = scraper.get_quote(symbol)
    today = date.today().isoformat()
    change = quote.get("regularMarketChangePercent")
    if change is not None and _movement([{"changePercent": change}]):
        headline = f"{symbol} moved {change:+.1f}% today"
        if db.insert_event(symbol, "price_move", today, headline, None, None, today, None, None):
            inserted += 1
    vol, avg_vol = quote.get("regularMarketVolume"), quote.get("averageVolume")
    if vol and avg_vol and _volume([{"volume": vol, "avgVolume": avg_vol}]):
        headline = f"{symbol} trading at {vol:,} vs {avg_vol:,} average volume"
        if db.insert_event(symbol, "volume_spike", today, headline, None, None, today, None, None):
            inserted += 1

    for action in scraper.get_corporate_actions(symbol):
        if db.insert_event(
            symbol,
            "corporate_action",
            f"{action['action_type']}:{action['date']}",
            action["detail"],
            None,
            None,
            action["date"],
            None,
            None,
        ):
            inserted += 1

    return inserted


def scan(list_name=None, on_progress=None):
    """Scans every watchlisted symbol (or one list's). on_progress(done, total) mirrors
    main.scan's callback shape so api.py can reuse its progress-polling pattern."""
    symbols = db.watchlist_symbols(list_name)
    count = 0
    for i, symbol in enumerate(symbols, 1):
        try:
            count += scan_symbol(symbol)
        except Exception as e:
            print(f"skipped {symbol}: {e}")
        if on_progress:
            on_progress(i, len(symbols))
    classifier.tag_pending_async()  # news events get their Laya tags in the background
    return count


def should_auto_scan(last_run_date, today):
    """True once per calendar day - last_run_date is whatever db.get_last_event_scan_date()
    returned (None if the automatic scan has never run yet), today an ISO date string."""
    return last_run_date != today
