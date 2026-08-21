"""
Unit and integration tests for CircuitBreaker and UniversalBrokerGateway integration.
"""

import time
<<<<<<< Updated upstream

from event_bus import global_event_bus
from institutional_integrations.circuit_breaker import (
    CircuitBreaker,
=======
import socket
import urllib.error
import pytest
from institutional_integrations.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenException,
>>>>>>> Stashed changes
)
from institutional_integrations.universal_broker_adapter import UniversalBrokerGateway


def test_circuit_breaker_transitions():
    """Tests CLOSED -> OPEN -> HALF_OPEN -> CLOSED state machine transitions."""
    events = []

    def handler(evt):
        events.append(evt)

    global_event_bus.subscribe("circuit_breaker", handler)

    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=0.2, half_open_probe=True)
    assert cb.get_state() == CircuitBreaker.CLOSED
    assert cb.allow() is True

    # Record 2 failures -> remains CLOSED
    cb.record_failure()
    cb.record_failure()
    assert cb.get_state() == CircuitBreaker.CLOSED
    assert cb.allow() is True

    # 3rd failure -> trips to OPEN
    cb.record_failure()
    assert cb.get_state() == CircuitBreaker.OPEN
    assert cb.allow() is False

    # During cooldown -> remains OPEN
    assert cb.allow() is False

    # Wait for cooldown to elapse (0.2s)
    time.sleep(0.25)

    # Cooldown elapsed -> state becomes HALF_OPEN on evaluation/probe
    assert cb.get_state() == CircuitBreaker.HALF_OPEN

    # Probe call allowed once
    assert cb.allow() is True
    # Subsequent probe call rejected while probe in flight
    assert cb.allow() is False

    # Probe succeeds -> transitions to CLOSED
    cb.record_success()
    assert cb.get_state() == CircuitBreaker.CLOSED
    assert cb.allow() is True


def test_circuit_breaker_probe_failure_reopens():
    """Tests that a failed probe call in HALF_OPEN state returns to OPEN state."""
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.1, half_open_probe=True)
    cb.record_failure()
    cb.record_failure()
    assert cb.get_state() == CircuitBreaker.OPEN

    time.sleep(0.15)
    assert cb.get_state() == CircuitBreaker.HALF_OPEN
    assert cb.allow() is True

    # Probe fails -> trips back to OPEN
    cb.record_failure()
    assert cb.get_state() == CircuitBreaker.OPEN
    assert cb.allow() is False


def test_circuit_breaker_excluded_exceptions():
    """Tests that excluded exception types do not increment failure counter."""

    class RiskViolation(Exception):
        pass

    cb = CircuitBreaker(failure_threshold=2, excluded_exceptions=(RiskViolation,))
    cb.record_failure(RiskViolation("Exceeds leverage limit"))
    cb.record_failure(RiskViolation("Exceeds drawdown"))

    assert cb.get_state() == CircuitBreaker.CLOSED


def test_universal_broker_gateway_circuit_breaker_integration():
    """Tests circuit breaker enforcement on UniversalBrokerGateway REST execution route."""
    config = {
        "rest_url": "http://127.0.0.1:59999",  # Non-existent endpoint
        "failure_threshold": 3,
        "cooldown_seconds": 1.0,
        "retry_backoff_delay": 0.01,
    }
    gw = UniversalBrokerGateway(protocol="REST_WS", broker_config=config)

    # Initial order execution fails with NETWORK_UNREACHABLE, increments breaker failure
    res1 = gw.execute_order("EURUSD", "BUY", 0.01, 1.0900, 1.1100)
    assert res1["success"] is False
    assert res1["reason"] == "NETWORK_UNREACHABLE"

    res2 = gw.execute_order("EURUSD", "BUY", 0.01, 1.0900, 1.1100)
    assert res2["success"] is False

    res3 = gw.execute_order("EURUSD", "BUY", 0.01, 1.0900, 1.1100)
    assert res3["success"] is False

    # Breaker is now OPEN -> 4th call short-circuits with 'circuit_open' without reaching out
    res4 = gw.execute_order("EURUSD", "BUY", 0.01, 1.0900, 1.1100)
    assert res4["success"] is False
    assert res4["reason"] == "circuit_open"
    assert res4["error"] == "circuit_open"


def test_universal_broker_gateway_configurable_backoff_and_network_unreachable():
    """Tests custom retry backoff delay configuration and explicit network unreachable status."""
    config = {"rest_url": "http://127.0.0.1:59998", "retry_backoff_delay": 0.05}
    gw = UniversalBrokerGateway(protocol="REST_WS", broker_config=config)
    assert gw.retry_backoff_delay == 0.05

    t0 = time.time()
    res = gw.execute_order("GBPUSD", "SELL", 0.02, 1.2800, 1.2600)
    elapsed = time.time() - t0

    assert res["success"] is False
    assert res["reason"] == "NETWORK_UNREACHABLE"
    assert "Network Unreachable" in res["error"]
