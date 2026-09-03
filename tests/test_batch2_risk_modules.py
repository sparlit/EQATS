"""
Integration and Unit Tests for Batch 2 Prop Firm Risk Guard Engines and ArkoRisk Modules.
"""

from datetime import datetime, time, timedelta
from typing import Any

import pytest

from institutional_integrations.arkorisk_guard import (
    PROP_FIRM_DATABASE,
    ArkoRiskGuard,
    DrawdownTaxonomy,
    MarketType,
    RiskProfilePreset,
)
from institutional_integrations.propfirm_risk_guard_engine import (
    ConsistencyConfig,
    CutoffConfig,
    DailyLossConfig,
    NewsWindow,
    PropFirmRiskGuardEngine,
    RiskSeverity,
    RiskTick,
    TrailingDDConfig,
)


def test_trailing_intraday_drawdown_breach() -> None:
    engine = PropFirmRiskGuardEngine(
        initial_balance=100000.0, trailing_config=TrailingDDConfig(max_drawdown=5000.0, mode="intraday_peak"),
    )
    now = datetime(2026, 7, 16, 10, 0, 0)
    events = engine.on_tick(RiskTick(now, 105000.0, position_size=1.0))
    snap = engine.snapshot()
    assert snap.watermark == 105000.0
    assert snap.floor == 100000.0
    assert not snap.breached
    events = engine.on_tick(RiskTick(now + timedelta(minutes=5), 99500.0, position_size=1.0))
    snap = engine.snapshot()
    assert snap.breached
    assert any(e.severity == RiskSeverity.BREACH for e in events)


def test_session_cutoff_scrambler() -> None:
    engine = PropFirmRiskGuardEngine(
        initial_balance=100000.0,
        cutoff_config=CutoffConfig(cutoff_time=time(17, 0, 0), warning_seconds=300.0, flatten_buffer_seconds=60.0),
    )
    tick_time = datetime(2026, 7, 16, 16, 59, 30)
    events = engine.on_tick(RiskTick(tick_time, 100000.0, position_size=2.0))
    flatten_events = [e for e in events if e.severity == RiskSeverity.FLATTEN]
    assert len(flatten_events) > 0
    assert "cutoff_scrambler" in flatten_events[0].rule_name


def test_consistency_score_auditor() -> None:
    engine = PropFirmRiskGuardEngine(
        initial_balance=100000.0, consistency_config=ConsistencyConfig(max_single_day_pct=30.0),
    )
    engine.completed_day_pnls = [100.0, 100.0]
    now = datetime(2026, 7, 16, 9, 0, 0)
    engine.on_tick(RiskTick(now, 100000.0))
    engine.on_tick(RiskTick(now + timedelta(hours=3), 100800.0))
    snap = engine.snapshot()
    assert snap.consistency_top_day_pct == 80.0
    assert snap.consistency_passed is False


def test_arkorisk_lot_sizing_and_firm_db() -> None:
    guard = ArkoRiskGuard(account_balance=100000.0, firm_key="FTMO", plan_key="2step")
    res = guard.calculate_lot_size(current_equity=100000.0, stop_loss_pips=20.0, pip_value_per_lot=10.0)
    assert res["lot_size"] > 0.0
    assert res["firm"] == "FTMO"
    assert "FTMO" in PROP_FIRM_DATABASE
    assert "APEX" in PROP_FIRM_DATABASE
    assert "TOPSTEP" in PROP_FIRM_DATABASE
