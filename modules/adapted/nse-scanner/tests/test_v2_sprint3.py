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
from v2.candidates import evaluate_candidate, rank_candidates
from v2.participation import evaluate_participation
from v2.portfolio_risk import Allocation
from v2.preview import render_candidate_preview
from v2.trade_plan import build_long_trade_plan


def sample_frame(rows: int = 280, breakout: bool = True) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=rows)
    close = np.linspace(100.0, 160.0, rows)
    volume = np.full(rows, 1_000_000.0)
    delivery = np.full(rows, 45.0)
    if breakout:
        close[-1] = close[-2] + 8.0
        volume[-1] = 2_000_000.0
        delivery[-1] = 55.0
    return pd.DataFrame(
        {
            "trade_date": dates,
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": volume,
            "delivery_pct": delivery,
        }
    )


def test_participation_passes_on_volume_and_delivery_expansion():
    result = evaluate_participation(sample_frame())
    assert result.passed
    assert result.metrics["volume_multiple"] >= 1.2


def test_trade_plan_has_positive_risk_and_targets():
    plan = build_long_trade_plan(sample_frame())
    assert plan.risk_per_share > 0
    assert plan.target2 > plan.entry > plan.stop


def test_bear_regime_is_hard_override():
    candidate = evaluate_candidate("TEST", sample_frame(), regime="BEAR")
    assert not candidate.selected
    assert "bear_market_hard_override" in candidate.reasons_against


def test_stale_data_is_hard_override():
    candidate = evaluate_candidate("TEST", sample_frame(), regime="BULL", stale_data=True)
    assert not candidate.selected
    assert "stale_data_hard_override" in candidate.reasons_against


def test_preview_contains_trade_levels_and_reasons():
    candidate = evaluate_candidate("TEST", sample_frame(), regime="BULL", minimum_score=0)
    grouped = rank_candidates([candidate])
    text = render_candidate_preview(grouped, "BULL", candidate.trade_date)
    if candidate.selected:
        assert "📊 KJ NSE SCANNER V2" in text
        assert "Entry Trigger:" in text
        assert "Hybrid Hull (fixed):" in text
        assert "EMA" not in text
        assert "ADX" not in text
    else:
        assert "No candidate crossed the qualification threshold" in text


def test_preview_can_show_configured_allocation():
    candidate = evaluate_candidate("TEST", sample_frame(), regime="BULL", minimum_score=0)
    candidate = candidate.__class__(**{**candidate.to_dict(), "selected": True})
    text = render_candidate_preview(
        {candidate.horizon: [candidate]},
        "BULL",
        candidate.trade_date,
        allocations={(candidate.symbol, candidate.horizon): Allocation(100, 10_000, 500, "risk_budget_per_trade")},
    )
    assert "Proposed Quantity: 100" in text
    assert "Initial Risk: ₹500.00" in text
