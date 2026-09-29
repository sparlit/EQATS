# codespell:ignore IST,ans
"""Unit tests for AI-Native SDLC Governor (Magic Number: 9100089)."""

from institutional_integrations.ai_native_sdlc_governor import (
    MAGIC_NUMBER_AI_NATIVE_SDLC,
    AINativeSDLCBrokerAdapter,
    AINativeSDLCGovernor,
    GateLedger,
    is_ist_market_open,
    round_tick_005,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
)


def test_magic_number_assignment() -> None:
    """Verifies that Magic Number 9100089 is assigned."""
    assert MAGIC_NUMBER_AI_NATIVE_SDLC == 9100089


def test_round_tick_005() -> None:
    """Tests 0.05 INR price tick rounding."""
    assert round_tick_005(2500.02) == 2500.00
    assert round_tick_005(2500.03) == 2500.05


def test_ist_market_open() -> None:
    """Tests market session validation."""
    assert isinstance(is_ist_market_open(), bool)


def test_gate_ledger_hash_chain() -> None:
    """Tests hash-chained gate ledger recording and cryptographic integrity verification."""
    ledger = GateLedger()
    e1 = ledger.record_approval(
        "GATE_PLAN_TO_SPEC", "PM_AGENT", "APPROVED", {"plan": "passed"}
    )
    assert e1.index == 0
    assert len(e1.entry_hash) == 64

    e2 = ledger.record_approval(
        "GATE_SPEC_TO_BUILD", "CTO_AGENT", "APPROVED", {"spec": "passed"}
    )
    assert e2.index == 1
    assert e2.prev_hash == e1.entry_hash

    assert ledger.verify_chain_integrity() is True

    # Tamper with chain entry
    e1.status = "REJECTED"
    assert ledger.verify_chain_integrity() is False


def test_control_band_monitor() -> None:
    """Tests ControlBandMonitor deviation evaluation."""
    governor = AINativeSDLCGovernor()
    eval_norm = governor.monitor.evaluate_metric("DRAWDOWN_PCT", 0.2)
    assert eval_norm["band"] == "NORMAL"

    eval_1s = governor.monitor.evaluate_metric("DRAWDOWN_PCT", 0.6)
    assert eval_1s["band"] == "1_SIGMA_NOTICE"

    eval_2s = governor.monitor.evaluate_metric("DRAWDOWN_PCT", 1.2)
    assert eval_2s["band"] == "2_SIGMA_ELEVATED"

    eval_3s = governor.monitor.evaluate_metric("DRAWDOWN_PCT", 2.2)
    assert eval_3s["band"] == "3_SIGMA_BREACH"
    assert eval_3s["action"] == "AUTO_INTENT_TRIGGER"


def test_advance_phase() -> None:
    """Tests phase lifecycle advancement with gate ledger proof."""
    governor = AINativeSDLCGovernor()
    assert governor.current_phase == "PLAN"

    success = governor.advance_phase("SPEC", "docs/spec.md", "CTO_AGENT")
    assert success is True
    assert governor.current_phase == "SPEC"
    assert governor.artifacts["SPEC"] == "docs/spec.md"


def test_pr_review_passes() -> None:
    """Tests multi-pass PR review evaluation with 5-nit cap enforcement."""
    governor = AINativeSDLCGovernor()
    nits = ["nit1", "nit2", "nit3", "nit4", "nit5", "nit6", "nit7"]

    # Passing review
    res_pass = governor.evaluate_pr_review_passes(
        pr_id="PR-101",
        bugs=[],
        security_vulnerabilities=[],
        compliance_gaps=[],
        nits=nits,
    )
    assert res_pass["approved"] is True
    assert len(res_pass["capped_nits"]) == 5
    assert res_pass["exceeded_nit_cap"] is True

    # Failing review
    res_fail = governor.evaluate_pr_review_passes(
        pr_id="PR-102",
        bugs=["Off-by-one index error"],
        security_vulnerabilities=[],
        compliance_gaps=[],
        nits=[],
    )
    assert res_fail["approved"] is False
    assert res_fail["status"] == "REJECTED_PR_REVIEW_FAIL"


def test_incident_intent_generation() -> None:
    """Tests closed-loop incident intent generation."""
    governor = AINativeSDLCGovernor()
    intent = governor.generate_incident_intent("DRAWDOWN_PCT", {"current_dd": 2.5})
    assert "Incident Remediation" in intent["title"]
    assert len(governor.generated_intents) == 1


def test_ci_eval_suite_evaluation() -> None:
    """Tests continuous CI eval suite pass-rate benchmarking."""
    governor = AINativeSDLCGovernor()
    evals = [{"id": f"eval_{i}", "passed": True} for i in range(9)] + [{"id": "eval_9", "passed": False}]

    res_pass = governor.evaluate_ci_eval_suite(evals, min_pass_rate_pct=90.0)
    assert res_pass["passed"] is True
    assert res_pass["pass_rate_pct"] == 90.0

    res_fail = governor.evaluate_ci_eval_suite(evals, min_pass_rate_pct=95.0)
    assert res_fail["passed"] is False


def test_production_gate_evaluation() -> None:
    """Tests production release safety gate evaluation."""
    governor = AINativeSDLCGovernor()

    # Normal authorized
    res_allow = governor.evaluate_production_gate(
        "RELIANCE",
        "BUY",
        2500.0,
        0.5,
        10.0,
        is_human_authorized=True,
    )
    assert res_allow["allowed"] is True
    assert res_allow["gate_status"] == "APPROVED_PRODUCTION_GATE"

    # Unauthorized
    res_unauth = governor.evaluate_production_gate(
        "RELIANCE",
        "BUY",
        2500.0,
        0.5,
        10.0,
        is_human_authorized=False,
    )
    assert res_unauth["allowed"] is False
    assert res_unauth["gate_status"] == "REJECTED_UNAUTHORIZED"

    # Breach
    res_breach = governor.evaluate_production_gate(
        "RELIANCE",
        "BUY",
        2500.0,
        2.5,
        10.0,
        is_human_authorized=True,
    )
    assert res_breach["allowed"] is False
    assert res_breach["gate_status"] == "REJECTED_CONTROL_BAND_BREACH"
    assert len(governor.generated_intents) == 1


def test_broker_adapter_integration() -> None:
    """Tests AINativeSDLCBrokerAdapter registration and order execution."""
    cls = IndianBrokerPluginRegistry.get_adapter_class("AI_NATIVE_SDLC_GOVERNOR")
    assert cls is AINativeSDLCBrokerAdapter

    adapter = AINativeSDLCBrokerAdapter()
    assert adapter.connect() is True
    assert adapter.is_connected() is True

    req = SEBIOrderRequest(
        symbol="TCS",
        order_type="BUY",
        quantity=5,
        price=3800.0,
    )
    res = adapter.execute_order(req)
    assert res.success is True
    assert res.status == "EXECUTED"

    info = adapter.get_account_info()
    assert info["magic_number"] == 9100089
    assert adapter.disconnect() is True
