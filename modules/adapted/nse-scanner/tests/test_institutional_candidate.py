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


import numpy as np
import pandas as pd
from v2.candidates import Candidate, focus_horizons, rank_candidates, watch_candidates
from v2.horizon_scoring import HorizonScore


def _candidate(classification: str, symbol: str = "ABC", score: float = 82.0) -> Candidate:
    return Candidate(
        symbol=symbol,
        trade_date="2026-08-04",
        horizon="POSITIONAL_3_6M",
        setup="TREND_CONTINUATION",
        selected=classification == "ACTION",
        score=score,
        reasons_for=("daily_trend",),
        reasons_against=(),
        entry=100.0,
        stop=94.0,
        target1=109.0,
        target2=118.0,
        reward_risk_t1=1.5,
        reward_risk_t2=3.0,
        metrics={},
        classification=classification,
        primary_horizon="3M",
        eligible_horizons=("3M",),
        entry_trigger="TREND_CONTINUATION",
        trade_plan_state="READY" if classification == "ACTION" else "WAIT",
        trade_plan_score=88.0,
    )


def test_rank_candidates_returns_every_action_when_uncapped() -> None:
    rows = [_candidate("ACTION", f"S{i}", 80 + i) for i in range(15)]
    grouped = rank_candidates(rows, top_n=None)
    assert sum(len(values) for values in grouped.values()) == 15


def test_rank_candidates_excludes_watch_rows() -> None:
    rows = [_candidate("ACTION", "ACTION"), _candidate("WATCH", "WATCH")]
    grouped = rank_candidates(rows, top_n=None)
    symbols = [row.symbol for values in grouped.values() for row in values]
    assert symbols == ["ACTION"]


def test_watch_candidates_returns_quality_without_ready_entry() -> None:
    rows = [
        _candidate("WATCH", "LOW", 75.0),
        _candidate("WATCH", "HIGH", 88.0),
        _candidate("ACTION", "ACTION", 90.0),
    ]
    assert [row.symbol for row in watch_candidates(rows)] == ["HIGH", "LOW"]


def test_candidate_contract_exposes_horizon_and_plan_fields() -> None:
    row = _candidate("ACTION")
    payload = row.to_dict()
    assert payload["primary_horizon"] == "3M"
    assert payload["classification"] == "ACTION"
    assert payload["entry_trigger"] == "TREND_CONTINUATION"
    assert payload["trade_plan_state"] == "READY"


def test_focus_scores_are_horizon_specific() -> None:
    def score(horizon: str, value: float) -> HorizonScore:
        return HorizonScore(horizon, value, "QUALIFIED", {}, (), (), (), {})

    rows = {
        "1M": score("1M", 80.0),
        "3M": score("3M", 80.0),
        "6M": score("6M", 81.0),
        "12M": score("12M", 82.0),
    }
    assert focus_horizons(rows) == ("1M", "3M", "12M")
