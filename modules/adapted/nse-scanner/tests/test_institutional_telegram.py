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


from dataclasses import replace

from v2.candidates import Candidate
from v2.preview import render_candidate_messages


def _candidate(symbol: str, classification: str = "ACTION") -> Candidate:
    return Candidate(
        symbol=symbol,
        trade_date="2026-08-04",
        horizon="POSITIONAL_3_6M",
        setup="TREND_CONTINUATION",
        selected=classification == "ACTION",
        score=88.0,
        reasons_for=("daily_trend", "relative_strength"),
        reasons_against=(),
        entry=100.0,
        stop=94.0,
        target1=109.0,
        target2=118.0,
        reward_risk_t1=1.5,
        reward_risk_t2=3.0,
        metrics={"hull55": 96.0, "hma21": 98.0, "hma51": 94.0, "atr14": 4.0},
        classification=classification,
        primary_horizon="3M",
        eligible_horizons=("3M",),
        watch_horizons=(),
        horizon_scores={
            "1M": {"score": 75.0, "state": "WATCH", "component_scores": {}},
            "3M": {"score": 88.0, "state": "QUALIFIED", "component_scores": {"daily_trend": 18.0, "rs63": 17.0}},
            "6M": {"score": 72.0, "state": "WATCH", "component_scores": {}},
            "12M": {"score": 61.0, "state": "DEVELOPING", "component_scores": {}},
        },
        entry_trigger="TREND_CONTINUATION" if classification == "ACTION" else "NO_TRIGGER",
        trigger_score=78.0 if classification == "ACTION" else 0.0,
        trade_plan_state="READY" if classification == "ACTION" else "WAIT",
        trade_plan_score=85.0 if classification == "ACTION" else 0.0,
        entry_basis="recent_pivot_high_plus_0.10_atr",
        stop_basis="recent_swing_low_minus_0.20_atr",
        risk_percent=6.0,
        valid_for_sessions=5,
        pullback_state="NO_PULLBACK",
    )


def test_every_action_candidate_is_present() -> None:
    actions = [_candidate(f"STOCK{i:02d}") for i in range(1, 18)]
    messages = render_candidate_messages(
        actions,
        [],
        "NEUTRAL",
        "2026-08-04",
        evaluated=2692,
        tradable=2692,
        quality_qualified=17,
        benchmark_source="EQUAL_WEIGHT_UNIVERSE_FALLBACK",
    )
    joined = "\n".join(messages)
    for candidate in actions:
        assert candidate.symbol in joined
    assert "Fresh Actionable: 17" in messages[0]
    assert "NSE V3 — DAILY WATCHLIST" in joined
    assert all(len(message) <= 4096 for message in messages)


def test_action_card_matches_compact_mobile_layout() -> None:
    messages = render_candidate_messages(
        [_candidate("ABC")],
        [],
        "NEUTRAL",
        "2026-08-04",
        evaluated=100,
        quality_qualified=1,
        benchmark_source="OFFICIAL_INDEX_HISTORY",
    )
    action = next(message for message in messages if "ABC" in message)
    assert "ABC" in action
    assert "Watch for entry • 88/100" in action
    assert "Entry: ₹100.00–₹100.40" in action
    assert "SL ₹94.00 | T1 ₹109.00 | T2 ₹118.00" in action
    assert "✅ Daily trend" in action
    assert "Entry basis:" not in action
    assert "score breakdown:" not in action


def test_watchlist_is_compact_separate_and_has_preferred_entry() -> None:
    watches = [replace(_candidate("WATCH1", "WATCH")), replace(_candidate("WATCH2", "WATCH"))]
    messages = render_candidate_messages(
        [],
        watches,
        "NEUTRAL",
        "2026-08-04",
        evaluated=100,
        quality_qualified=2,
        benchmark_source="OFFICIAL_INDEX_HISTORY",
    )
    assert "Fresh Actionable: 0" in messages[0]
    watch_message = next(message for message in messages if "WATCH1" in message)
    assert "WATCH1" in watch_message
    assert "WATCH2" in watch_message
    assert "Planned entry: ₹" in watch_message
    assert "Trade plan wait" in watch_message


def test_watch_entry_uses_slower_structure_for_long_horizon() -> None:
    watch = replace(_candidate("LONGWATCH", "WATCH"), primary_horizon="12M")
    messages = render_candidate_messages(
        [],
        [watch],
        "NEUTRAL",
        "2026-08-04",
        evaluated=100,
        quality_qualified=1,
        benchmark_source="OFFICIAL_INDEX_HISTORY",
    )
    watch_message = next(message for message in messages if "LONGWATCH" in message)
    assert "Planned entry: ₹" in watch_message
    assert "not an active buy signal" in watch_message


def test_action_cards_keep_horizon_on_each_stock() -> None:
    swing = replace(_candidate("SWING"), primary_horizon="1M")
    positional = replace(_candidate("POSITIONAL"), primary_horizon="3M")
    messages = render_candidate_messages(
        [swing, positional],
        [],
        "NEUTRAL",
        "2026-08-04",
        evaluated=100,
        quality_qualified=2,
        benchmark_source="OFFICIAL_INDEX_HISTORY",
    )
    joined = "\n".join(messages)
    assert "1M Trend Continuation" in joined
    assert "3M Trend Continuation" in joined


def test_fallback_reason_is_readable() -> None:
    messages = render_candidate_messages(
        [],
        [],
        "NEUTRAL",
        "2026-08-04",
        evaluated=100,
        benchmark_source="EQUAL_WEIGHT_UNIVERSE_FALLBACK",
    )
    assert "official index history unavailable" in messages[0]
    assert "official_index_history_unavailable" not in messages[0]
