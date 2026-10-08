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


"""The `/agent` module: an LLM agent over OpenAlgo's internal service layer.

Nothing is re-exported here on purpose. Importing this package must not pull in
agno, LiteLLM, the database or a broker, so a submodule with narrow needs (the
wire contract in :mod:`services.agent.frames`, the provider vocabulary in
:mod:`services.agent.providers`) stays importable on its own.

The build contract is `docs/design/55-agent/README.md`. Where that document and
this code disagree, the code is right.
"""
