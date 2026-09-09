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
from src.autonomous_investment_intelligence.models import (
    AutonomousDecisionCycle,
    AutonomousDecisionOutcome,
    HumanApproval,
)


def test_actionable_cycle_requires_evidence_and_score():
    with pytest.raises(ValueError, match="evidence references"):
        AutonomousDecisionCycle(
            cycle_id="C-1",
            decision_id="D-1",
            scope="PORTFOLIO",
            as_of_date="2026-07-31",
            action="REDUCE",
            status="AWAITING_APPROVAL",
            deterministic_score=72,
        )


def test_unresolved_cycle_blocks_portfolio_action():
    with pytest.raises(ValueError, match="cannot propose"):
        AutonomousDecisionCycle(
            cycle_id="C-2",
            decision_id="D-2",
            scope="COMPANY",
            as_of_date="2026-07-31",
            action="BUY",
            status="INSUFFICIENT_DATA",
            limitations=("Missing verified filing",),
        )


def test_approved_portfolio_action_requires_constraints():
    with pytest.raises(ValueError, match="require constraints"):
        AutonomousDecisionCycle(
            cycle_id="C-3",
            decision_id="D-3",
            scope="PORTFOLIO",
            as_of_date="2026-07-31",
            action="ADD",
            status="APPROVED",
            evidence_references=("evidence:1",),
            deterministic_score=81,
        )


def test_human_approval_requires_reference():
    with pytest.raises(ValueError, match="approval_reference"):
        HumanApproval(
            cycle_id="C-4",
            reviewer="Jayesh",
            reviewed_date="2026-07-31",
            decision="APPROVE",
            reason="Evidence and limits reviewed",
        )


def test_executed_outcome_requires_approval_and_audit():
    with pytest.raises(ValueError, match="approval_reference"):
        AutonomousDecisionOutcome(
            cycle_id="C-5",
            recorded_date="2026-07-31",
            outcome="EXECUTED",
            executed_action="REDUCE",
            audit_references=("audit:1",),
        )


def test_valid_governed_cycle_and_outcome():
    cycle = AutonomousDecisionCycle(
        cycle_id="C-6",
        decision_id="D-6",
        scope="PORTFOLIO",
        as_of_date="2026-07-31",
        action="REDUCE",
        status="APPROVED",
        evidence_references=("evidence:1", "decision:D-6"),
        deterministic_score=76,
        constraints=("Maximum reduction 2 percent",),
        expires_on="2026-08-02",
    )
    approval = HumanApproval(
        cycle_id="C-6",
        reviewer="Jayesh",
        reviewed_date="2026-07-31",
        decision="APPROVE",
        reason="Risk threshold exceeded",
        approval_reference="approval:C-6",
    )
    outcome = AutonomousDecisionOutcome(
        cycle_id="C-6",
        recorded_date="2026-07-31",
        outcome="EXECUTED",
        executed_action="REDUCE",
        approval_reference="approval:C-6",
        audit_references=("audit:C-6",),
    )

    assert cycle.status == "APPROVED"
    assert approval.decision == "APPROVE"
    assert outcome.outcome == "EXECUTED"
