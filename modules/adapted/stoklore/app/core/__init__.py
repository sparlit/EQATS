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


"""Domain and infrastructure layer: everything the HTTP layer sits on top of.

Postgres access (db), price/news/fundamentals fetching (scraper, netfetch, prices, minute_data,
price_sources, moneycontrol_local), broker clients (broker, kite), the LLM client (llm), and the
pure engines (rules, backtest, paper, trade_context, sentiment, events, stocks_master, backup).

Nothing here imports app.routers or app.services - the dependency runs one way, so an engine can
be exercised from a test or the CLI (app/cli.py) without standing up FastAPI. `app/core/config.py`
holds the cross-cutting constants these share.
"""
