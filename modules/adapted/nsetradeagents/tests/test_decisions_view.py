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


"""Which gate stopped a candidate — shown in the table, not just on expand."""
from datetime import date

import pytest
from app.api.routes import _blocked_by
from app.core.config import settings
from app.models.models import DecisionRecord


def rec(**kw) -> DecisionRecord:
    base = {
        "as_of": date(2026, 9, 4),
        "ticker": "X.NS",
        "score": 80,
        "entered": False,
        "regime_open": True,
        "veto_verdict": None,
    }
    return DecisionRecord(**{**base, **kw})


def test_a_taken_trade_has_no_blocker():
    assert _blocked_by(rec(entered=True)) is None


def test_a_low_score_is_attributed_to_the_score():
    assert _blocked_by(rec(score=52)) == "score"


def test_score_wins_over_a_shut_regime():
    """Ordered by where the gates sit: a candidate that failed on score never
    reached the regime check, so blaming the regime would be wrong."""
    assert _blocked_by(rec(score=52, regime_open=False)) == "score"


def test_a_cleared_score_with_a_shut_regime_is_attributed_to_the_regime():
    """The case that prompted this: veto passed, nothing traded, and the table
    showed no reason at all."""
    assert _blocked_by(rec(score=70, regime_open=False, veto_verdict="PASS")) == "regime"


def test_a_kill_in_an_open_regime_is_attributed_to_the_veto():
    assert _blocked_by(rec(score=92, regime_open=True, veto_verdict="KILL")) == "veto"


def test_the_regime_outranks_a_kill_because_shadow_mode_does_not_block():
    """In shadow mode a KILL does not stop the trade, so when both apply the
    regime is what actually prevented it."""
    assert _blocked_by(rec(score=92, regime_open=False, veto_verdict="KILL")) == "regime"


def test_an_unscored_candidate_falls_back_rather_than_crashing():
    assert _blocked_by(rec(score=None, regime_open=None)) == "blocked"
