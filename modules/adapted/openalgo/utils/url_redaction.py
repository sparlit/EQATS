from __future__ import annotations

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


"""Redact replayable credentials embedded in public webhook URL paths."""


import re
from typing import Any

# The first path segment after each prefix is the credential. Flow may retain a
# non-secret symbol suffix, so the match stops at the next slash. Keeping this
# as one expression makes the same rule usable for a bare Flask path, a full
# URL, a Werkzeug request line, and arbitrary application-log text.
_URL_CREDENTIAL = re.compile(
    r"(?P<prefix>/(?:strategy|flow|chartink)/webhook/)[^/\s?#'\"<>]+",
    flags=re.IGNORECASE,
)

# Broker OAuth callbacks carry short-lived but replayable credentials in query
# parameters. Keep this URL-specific so an ordinary application line such as
# ``HTTP status code=200`` remains untouched while callback ``code=...`` is
# masked. The names cover the aliases accepted by ``blueprints/brlogin.py``.
_QUERY_CREDENTIAL = re.compile(
    r"(?P<prefix>[?&](?:"
    r"api[_-]?session|token(?:[_-]?id)?|request[_-]?token|auth[_-]?code|"
    r"access[_-]?token|session|code"
    r")=)[^&#\s'\"<>]+",
    flags=re.IGNORECASE,
)


def redact_url_credentials(value: Any) -> str:
    """Return ``value`` with shipped path and query credentials masked."""
    redacted = _URL_CREDENTIAL.sub(r"\g<prefix><redacted>", str(value))
    return _QUERY_CREDENTIAL.sub(r"\g<prefix>[REDACTED]", redacted)
