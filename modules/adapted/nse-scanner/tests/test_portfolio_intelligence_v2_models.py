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


import pytest
from src.portfolio_intelligence_v2.models import PortfolioRiskSnapshot, RebalanceProposal


def test_evaluated_risk_requires_evidence() -> None:
    with pytest.raises(ValueError):
        PortfolioRiskSnapshot(
            as_of_date="2026-07-31",
            position_count=5,
            concentration_pct=32.0,
            diversification_score=68.0,
            risk_status="MODERATE",
        )


def test_insufficient_data_snapshot_is_explicit() -> None:
    snapshot = PortfolioRiskSnapshot(
        as_of_date="2026-07-31",
        position_count=0,
        concentration_pct=0,
        diversification_score=0,
        risk_status="INSUFFICIENT_DATA",
        limitations=("Portfolio positions not supplied",),
    )
    assert snapshot.risk_status == "INSUFFICIENT_DATA"


def test_increase_requires_higher_weight_and_evidence() -> None:
    proposal = RebalanceProposal(
        symbol="TCS",
        action="INCREASE",
        current_weight_pct=5,
        proposed_weight_pct=7,
        rationale_codes=("QUALITY",),
        evidence_ids=("company:TCS:latest",),
    )
    assert proposal.proposed_weight_pct == 7


def test_exit_requires_zero_weight() -> None:
    with pytest.raises(ValueError):
        RebalanceProposal(
            symbol="ABC",
            action="EXIT",
            current_weight_pct=4,
            proposed_weight_pct=1,
            evidence_ids=("risk:ABC:latest",),
        )
