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


"""Issue #208: the second-factor code provider of connect() is a Python
callable, called on its own thread during the login with the challenge as a
dict, returning the code. No server needed: the provider is run the way the
login runs it.
"""
import pytest
from ibx import EClient, EWrapper


def test_code_provider_gets_the_challenge_and_returns_the_code():
    seen = []

    def provider(challenge):
        seen.append(challenge)
        return "12345678"

    c = EClient(EWrapper())
    assert c._test_code_provider(provider, "580 820", "https://example.com/s") == "12345678"
    assert seen == [{"display_id": "580 820", "avth_url": "https://example.com/s"}]


def test_an_exception_of_the_code_provider_ends_the_login():
    def provider(challenge):
        raise ValueError("no code")

    c = EClient(EWrapper())
    with pytest.raises(RuntimeError, match="code_provider raised"):
        c._test_code_provider(provider, "1", "")
