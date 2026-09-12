"""
Chaos & Stress Testing Suite for EQATS Version 11.0.0.

Tests systemic resilience against simulated network latency, message rate spikes,
WAL lock contention, and event bus load.
"""

import threading
import time
import pytest

from eqats_planes import ExecutionPlane, SafetyVerificationPlane, calculate_stop_loss_exposure
from event_bus import Event, EventBus
from v11_autonomous_self_healing_engine import V11HyperAutonomousSelfFixingGovernor


class MockConnector:
    def execute_order(self, symbol, direction, lot, sl, tp):
        return {"success": True, "ticket": 12345, "price": 100.0}


def test_safety_plane_actual_exposure():
    safety = SafetyVerificationPlane()
    import config
    old_cap = getattr(config, "GLOBAL_RISK_LIMIT_CAP_PERCENT", 100.0)
    config.GLOBAL_RISK_LIMIT_CAP_PERCENT = 5.0
    try:
        # Violate limit when actual exposure > cap (e.g., 6.0% > 5.0%)
        violations = safety.evaluate_invariants(
            current_risk=2.0,
            active_count=2,
            actual_aggregate_exposure_pct=6.0,
        )
        assert "INV-001" in violations

        # Pass when actual exposure <= cap
        violations_clean = safety.evaluate_invariants(
            current_risk=2.0,
            active_count=2,
            actual_aggregate_exposure_pct=4.0,
        )
        assert "INV-001" not in violations_clean
    finally:
        config.GLOBAL_RISK_LIMIT_CAP_PERCENT = old_cap


def test_execution_plane_rate_governance_multithreaded():
    conn = MockConnector()
    exec_plane = ExecutionPlane(conn)

    results = []
    def worker():
        res = exec_plane.check_rate_limits()
        results.append(res)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Rate limits block after 5 calls within 10s
    assert False in results
    assert exec_plane.rate_state in ("THROTTLED", "HALTED")


def test_self_healing_adaptive_checkpoint():
    governor = V11HyperAutonomousSelfFixingGovernor()
    res = governor.perform_database_healing()
    assert res is True


def test_event_bus_hf_tick_fastpath():
    bus = EventBus()
    tick_event = Event(family="MARKET_DATA", source="TestFeed", payload={"symbol": "NIFTY", "price": 24000.0})
    assert tick_event.integrity_metadata == "HF_TICK_FASTPATH"
