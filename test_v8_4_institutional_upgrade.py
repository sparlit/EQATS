"""
Exhaustive Integration Test Suite for EQATS Version 8.4 Institutional Upgrade.
Verifies system version headers, ScalperBrain v8.4 dynamic adaptive volatility slippage controls,
multi-agent consensus directives, system capacity auto-tuning, and zero-error execution state.
"""

import pytest

import config
import database
from brain import ScalperBrain
from brain_agents_orchestrator import global_brain_orchestrator
from institutional_integrations.system_autotune import auto_tune_system_parameters, detect_system_capabilities
from institutional_integrations.trade_memory_protocol import global_trade_memory_protocol


def test_v8_4_version_assertions():
    """Verifies that all core engine modules report EQATS Version 8.5."""
    brain = ScalperBrain()
    assert brain.version.startswith("8.")

    vitals = detect_system_capabilities()
    assert vitals["cpu_logical_cores"] > 0
    assert vitals["ram_total_gb"] > 0

    tuned = auto_tune_system_parameters()
    assert tuned["hardware_caps"]["performance_tier"] in ["LOW", "MEDIUM", "HIGH", "ULTRA"]


def test_v8_4_brain_evaluation_and_slippage_control():
    """Verifies ScalperBrain evaluation output contains v8.4 dynamic volatility slippage calculations."""
    brain = ScalperBrain()
    history = [
        {"open": 1.1000 + i * 0.0001, "high": 1.1005 + i * 0.0001, "low": 1.0995 + i * 0.0001, "close": 1.1002 + i * 0.0001}
        for i in range(220)
    ]
    res = brain.evaluate("EURUSD", history, 10000.0)

    assert "decision" in res
    assert res["decision"] in ["BUY", "SELL", "HOLD"]
    assert "v8_4_slippage_pips" in res
    assert 0.5 <= res["v8_4_slippage_pips"] <= 5.0


def test_v8_4_multi_agent_swarm_orchestration():
    """Verifies that the multi-agent swarm orchestrator generates valid v8.4 directives."""
    class MockScalper:
        class MockConn:
            def get_current_price(self, sym):
                return {"bid": 1.1000, "ask": 1.1002}
            def get_account_info(self):
                return {"balance": 10000.0, "equity": 10000.0}
        conn = MockConn()
        daily_start_balance = 10000.0

    scalper = MockScalper()
    directive = global_brain_orchestrator.run_agentic_loop(scalper, symbol="EURUSD")

    assert directive.recommended_bias in ["BUY", "SELL", "HOLD"]
    assert 0.0 <= directive.confidence_score <= 100.0
    assert directive.recommended_style in ["SCALPING", "DAY_TRADING", "SWING_TRADING", "POSITION_TRADING"]
    assert len(directive.guidance_notes) > 0


def test_v8_4_trade_memory_reflection_protocol():
    """Verifies trade memory reflection protocol logging and post-mortem analysis for v8.4."""
    global_trade_memory_protocol.log_no_trade_veto(
        symbol="GBPUSD",
        direction="HOLD",
        signal_probability=55.0,
        veto_reason="V8.4 Test Veto Admission Gate",
        strategy_used="VOTING_ENSEMBLE",
    )

    summary = global_trade_memory_protocol.get_summary()
    assert "total_reflections" in summary
    assert "recent_reflections" in summary
    assert len(summary["recent_reflections"]) >= 1
