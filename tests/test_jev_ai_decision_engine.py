"""Unit tests for JEV AI Decision Engine (Magic Number: 9100088)."""

from unittest.mock import MagicMock, patch

import pytest

from institutional_integrations.jev_ai_decision_engine import (
    MAGIC_NUMBER_JEV_AI,
    JevAIDecisionBrokerAdapter,
    JevAIDecisionEngine,
    is_ist_market_open,
    round_tick_005,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
)


def test_magic_number_assignment() -> None:
    """Verifies that Magic Number 9100088 is assigned."""
    assert MAGIC_NUMBER_JEV_AI == 9100088


def test_round_tick_005() -> None:
    """Tests 0.05 INR price tick rounding."""
    assert round_tick_005(100.02) == 100.00
    assert round_tick_005(100.03) == 100.05
    assert round_tick_005(100.07) == 100.05
    assert round_tick_005(100.08) == 100.10


def test_ist_market_open() -> None:
    """Tests IST market session validation."""
    assert isinstance(is_ist_market_open(), bool)


def test_classify_market_regime_fallback() -> None:
    """Tests offline heuristic fallback for market regime classification."""
    engine = JevAIDecisionEngine()
    res = engine.classify_market_regime("RELIANCE", 2500.0, vix=25.0, atr=80.0, rsi=60.0)
    assert res["regime"] == "HIGH_VOLATILITY_BREAKOUT"
    assert res["is_fallback"] is True

    res_bull = engine.classify_market_regime("INFY", 1500.0, vix=15.0, atr=10.0, rsi=60.0, trend_direction="UP")
    assert res_bull["regime"] == "BULLISH_TREND"


def test_score_trade_risk_severity_fallback() -> None:
    """Tests trade risk severity score calculation in fallback mode."""
    engine = JevAIDecisionEngine()
    res_low = engine.score_trade_risk_severity("TCS", position_size_inr=10000.0, portfolio_drawdown_pct=0.2, slippage_estimate_bps=5.0)
    assert res_low["score_label"] == "LOW"

    res_crit = engine.score_trade_risk_severity("TCS", position_size_inr=600000.0, portfolio_drawdown_pct=2.5, slippage_estimate_bps=60.0)
    assert res_crit["score_label"] == "CRITICAL"


def test_evaluate_execution_safety_noul_fallback() -> None:
    """Tests Noul yes/no execution safety guardrail evaluation."""
    engine = JevAIDecisionEngine()
    res_safe = engine.evaluate_execution_safety_noul("SBIN", "BUY", 800.0, vix=15.0, portfolio_drawdown_pct=0.5)
    assert res_safe["is_safe"] is True
    assert res_safe["noul_prob"] >= 0.5

    res_unsafe = engine.evaluate_execution_safety_noul("SBIN", "BUY", 800.0, vix=25.0, portfolio_drawdown_pct=2.5)
    assert res_unsafe["is_safe"] is False


def test_preset_workflows() -> None:
    """Tests preset workflows: tool-guard, model-route, research-check, completion-review."""
    engine = JevAIDecisionEngine()

    # Tool Guard
    tg = engine.guard_tool_call(
        tool="execute_order",
        action="Submit market buy",
        arguments_summary=["symbol=RELIANCE"],
        side_effects=["Executes order"],
        policy=["Check drawdown limit"],
        drawdown_pct=0.5,
    )
    assert tg["decision"] == "allow"

    tg_deny = engine.guard_tool_call(
        tool="emergency_halt",
        action="emergency_halt_all",
        arguments_summary=[],
        side_effects=[],
        policy=[],
        drawdown_pct=2.5,
    )
    assert tg_deny["decision"] == "deny"

    # Model Route
    mr = engine.route_execution_model(
        task="Route intraday order",
        candidates=[{"id": "fast_engine"}, {"id": "deep_engine"}],
        priorities=["latency"],
    )
    assert mr["selected_model"] == "fast_engine"

    # Research Check
    rc = engine.check_research_signal(
        claim="Earnings beat expected",
        evidence=["Q3 revenue up 15%"],
    )
    assert rc["decision"] == "accept"

    # Completion Review
    cr = engine.review_execution_completion(
        objective="Execute order slice",
        completed_work=["Submitted 100 shares"],
        known_gaps=[],
    )
    assert cr["decision"] == "complete"


def test_full_decision_matrix() -> None:
    """Tests evaluate_full_decision_matrix method."""
    engine = JevAIDecisionEngine()
    res = engine.evaluate_full_decision_matrix(
        symbol="NIFTY",
        price=22000.0,
        vix=16.0,
        atr=150.0,
        rsi=55.0,
        position_size_inr=100000.0,
        portfolio_drawdown_pct=0.8,
        slippage_bps=12.0,
    )
    assert res.magic_number == 9100088
    assert "market_regime" in res.choices
    assert "trade_risk_severity" in res.scores
    assert "execution_safety" in res.nouls


def test_broker_adapter_integration() -> None:
    """Tests JevAIDecisionBrokerAdapter registration and order placement."""
    cls = IndianBrokerPluginRegistry.get_adapter_class("JEV_AI_DECISION_ENGINE")
    assert cls is JevAIDecisionBrokerAdapter

    adapter = JevAIDecisionBrokerAdapter()
    assert adapter.connect() is True
    assert adapter.is_connected() is True

    req = SEBIOrderRequest(
        symbol="RELIANCE",
        order_type="BUY",
        quantity=10,
        price=2500.0,
    )
    res = adapter.execute_order(req)
    assert res.success is True
    assert res.status == "EXECUTED"

    info = adapter.get_account_info()
    assert info["magic_number"] == 9100088
    assert adapter.disconnect() is True
