"""
Unit and integration tests for CircuitBreaker and UniversalBrokerGateway integration.
"""

import time

from event_bus import global_event_bus
from institutional_integrations.circuit_breaker import (
    CircuitBreaker,
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

    res = gw.execute_order("GBPUSD", "SELL", 0.02, 1.2800, 1.2600)

    assert res["success"] is False
    assert res["reason"] == "NETWORK_UNREACHABLE"
    assert "Network Unreachable" in res["error"]


def test_universal_broker_gateway_fail_closed_without_rest_url():
    """
    Tests that REST-like protocols without rest_url fail closed instead of returning synthetic success.
    This prevents phantom orders from being created when configuration is missing.
    """
    # Test 1: REST_WS protocol without rest_url should fail to connect
    config_no_url = {"api_key": "test_key", "api_secret": "test_secret"}
    gw = UniversalBrokerGateway(protocol="REST_WS", broker_config=config_no_url)

    # Connection should fail
    connect_result = gw.connect()
    assert connect_result is False, "Connection should fail without rest_url"
    assert gw.is_connected() is False, "Gateway should not be connected"

    # Order execution should fail with configuration error
    res = gw.execute_order("EURUSD", "BUY", 0.01, 1.0900, 1.1100)
    assert res["success"] is False, "Order should fail without rest_url"
    assert (
        res["reason"] == "CONFIGURATION_ERROR"
    ), "Should return CONFIGURATION_ERROR reason"
    assert (
        "No valid execution path" in res["error"]
    ), "Error should indicate no valid execution path"
    assert res["ticket"] == "", "Should not generate synthetic ticket"

    # Test 2: CCXT protocol without rest_url should also fail
    gw_ccxt = UniversalBrokerGateway(protocol="CCXT", broker_config=config_no_url)
    connect_result_ccxt = gw_ccxt.connect()
    assert connect_result_ccxt is False, "CCXT connection should fail without rest_url"

    res_ccxt = gw_ccxt.execute_order("BTCUSDT", "BUY", 0.1, 40000, 50000)
    assert res_ccxt["success"] is False, "CCXT order should fail without rest_url"
    assert res_ccxt["reason"] == "CONFIGURATION_ERROR"

    # Test 3: IBKR protocol without rest_url should also fail
    gw_ibkr = UniversalBrokerGateway(protocol="IBKR", broker_config=config_no_url)
    connect_result_ibkr = gw_ibkr.connect()
    assert connect_result_ibkr is False, "IBKR connection should fail without rest_url"

    res_ibkr = gw_ibkr.execute_order("AAPL", "BUY", 100, 150, 200)
    assert res_ibkr["success"] is False, "IBKR order should fail without rest_url"
    assert res_ibkr["reason"] == "CONFIGURATION_ERROR"

    # Test 4: CTRADER protocol without rest_url should also fail
    gw_ctrader = UniversalBrokerGateway(protocol="CTRADER", broker_config=config_no_url)
    connect_result_ctrader = gw_ctrader.connect()
    assert (
        connect_result_ctrader is False
    ), "CTRADER connection should fail without rest_url"

    res_ctrader = gw_ctrader.execute_order("GBPUSD", "SELL", 0.02, 1.2800, 1.2600)
    assert res_ctrader["success"] is False, "CTRADER order should fail without rest_url"
    assert res_ctrader["reason"] == "CONFIGURATION_ERROR"


def test_universal_broker_gateway_rejects_unsupported_protocol():
    """
    Tests that unsupported protocols are rejected at initialization to prevent fail-open execution.
    """
    import pytest

    # Test that unsupported protocol raises ValueError at initialization
    with pytest.raises(ValueError) as exc_info:
        UniversalBrokerGateway(protocol="UNSUPPORTED_PROTOCOL", broker_config={})

    assert "Unsupported protocol" in str(exc_info.value)
    assert "UNSUPPORTED_PROTOCOL" in str(exc_info.value)

    # Test another unsupported protocol
    with pytest.raises(ValueError) as exc_info2:
        UniversalBrokerGateway(protocol="RANDOM_BROKER", broker_config={})

    assert "Unsupported protocol" in str(exc_info2.value)
