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


from v2.fundamentals import FundamentalSnapshot, evaluate_fundamentals
from v2.progression import ProgressionStage, next_holding_stage


def test_strong_fundamentals_pass():
    gate = evaluate_fundamentals(
        FundamentalSnapshot(
            "ABC",
            "2026-06-30",
            12,
            18,
            17,
            0.4,
            True,
            0,
            False,
        )
    )
    assert gate.passed
    assert gate.score == 6


def test_governance_flag_fails_even_with_strong_numbers():
    gate = evaluate_fundamentals(
        FundamentalSnapshot(
            "ABC",
            "2026-06-30",
            12,
            18,
            17,
            0.4,
            True,
            0,
            True,
        )
    )
    assert not gate.passed
    assert "governance_risk_flag" in gate.reasons_against


def test_6m_promotion_requires_explicit_fundamental_pass():
    blocked = next_holding_stage(
        "QUALIFIED_3M",
        {"6M": "QUALIFIED"},
        65,
        trend_intact=True,
        fundamentals_passed=None,
    )
    assert blocked.stage == ProgressionStage.QUALIFIED_3M
    promoted = next_holding_stage(
        "QUALIFIED_3M",
        {"6M": "QUALIFIED"},
        65,
        trend_intact=True,
        fundamentals_passed=True,
    )
    assert promoted.stage == ProgressionStage.QUALIFIED_6M
