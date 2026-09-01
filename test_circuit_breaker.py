"""
Unit and integration tests for CircuitBreaker and UniversalBrokerGateway integration.
"""
from typing import Any
import time
from event_bus import global_event_bus
from institutional_integrations.circuit_breaker import CircuitBreaker
from institutional_integrations.universal_broker_adapter import UniversalBrokerGateway

def test_circuit_breaker_transitions() -> None:
    """Tests CLOSED -> OPEN -> HALF_OPEN -> CLOSED state machine transitions."""
    events = []

    def handler(evt: Any) -> None:
        events.append(evt)
    global_event_bus.subscribe('circuit_breaker', handler)
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=0.2, half_open_probe=True)
    assert cb.get_state() == CircuitBreaker.CLOSED
    assert cb.allow() is True
    cb.record_failure()
    cb.record_failure()
    assert cb.get_state() == CircuitBreaker.CLOSED
    assert cb.allow() is True
    cb.record_failure()
    assert cb.get_state() == CircuitBreaker.OPEN
    assert cb.allow() is False
    assert cb.allow() is False
    time.sleep(0.25)
    assert cb.get_state() == CircuitBreaker.HALF_OPEN
    assert cb.allow() is True
    assert cb.allow() is False
    cb.record_success()
    assert cb.get_state() == CircuitBreaker.CLOSED
    assert cb.allow() is True

def test_circuit_breaker_probe_failure_reopens() -> None:
    """Tests that a failed probe call in HALF_OPEN state returns to OPEN state."""
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.1, half_open_probe=True)
    cb.record_failure()
    cb.record_failure()
    assert cb.get_state() == CircuitBreaker.OPEN
    time.sleep(0.15)
    assert cb.get_state() == CircuitBreaker.HALF_OPEN
    assert cb.allow() is True
    cb.record_failure()
    assert cb.get_state() == CircuitBreaker.OPEN
    assert cb.allow() is False

def test_circuit_breaker_excluded_exceptions() -> None:
    """Tests that excluded exception types do not increment failure counter."""

    class RiskViolation(Exception):
        pass
    cb = CircuitBreaker(failure_threshold=2, excluded_exceptions=(RiskViolation,))
    cb.record_failure(RiskViolation('Exceeds leverage limit'))
    cb.record_failure(RiskViolation('Exceeds drawdown'))
    assert cb.get_state() == CircuitBreaker.CLOSED

def test_universal_broker_gateway_circuit_breaker_integration() -> None:
    """Tests circuit breaker enforcement on UniversalBrokerGateway REST execution route."""
    config = {'rest_url': 'http://127.0.0.1:59999', 'failure_threshold': 3, 'cooldown_seconds': 1.0, 'retry_backoff_delay': 0.01}
    gw = UniversalBrokerGateway(protocol='REST_WS', broker_config=config)
    res1 = gw.execute_order('EURUSD', 'BUY', 0.01, 1.09, 1.11)
    assert res1['success'] is False
    assert res1['reason'] == 'NETWORK_UNREACHABLE'
    res2 = gw.execute_order('EURUSD', 'BUY', 0.01, 1.09, 1.11)
    assert res2['success'] is False
    res3 = gw.execute_order('EURUSD', 'BUY', 0.01, 1.09, 1.11)
    assert res3['success'] is False
    res4 = gw.execute_order('EURUSD', 'BUY', 0.01, 1.09, 1.11)
    assert res4['success'] is False
    assert res4['reason'] == 'circuit_open'
    assert res4['error'] == 'circuit_open'

def test_universal_broker_gateway_configurable_backoff_and_network_unreachable() -> None:
    """Tests custom retry backoff delay configuration and explicit network unreachable status."""
    config = {'rest_url': 'http://127.0.0.1:59998', 'retry_backoff_delay': 0.05}
    gw = UniversalBrokerGateway(protocol='REST_WS', broker_config=config)
    assert gw.retry_backoff_delay == 0.05
    res = gw.execute_order('GBPUSD', 'SELL', 0.02, 1.28, 1.26)
    assert res['success'] is False
    assert res['reason'] == 'NETWORK_UNREACHABLE'
    assert 'Network Unreachable' in res['error']

def test_universal_broker_gateway_fail_closed_without_rest_url() -> None:
    """
    Tests that REST-like protocols without rest_url fail closed instead of returning synthetic success.
    This prevents phantom orders from being created when configuration is missing.
    """
    config_no_url = {'api_key': 'test_key', 'api_secret': 'test_secret'}
    gw = UniversalBrokerGateway(protocol='REST_WS', broker_config=config_no_url)
    connect_result = gw.connect()
    assert connect_result is False, 'Connection should fail without rest_url'
    assert gw.is_connected() is False, 'Gateway should not be connected'
    res = gw.execute_order('EURUSD', 'BUY', 0.01, 1.09, 1.11)
    assert res['success'] is False, 'Order should fail without rest_url'
    assert res['reason'] == 'CONFIGURATION_ERROR', 'Should return CONFIGURATION_ERROR reason'
    assert 'No valid execution path' in res['error'], 'Error should indicate no valid execution path'
    assert res['ticket'] == '', 'Should not generate synthetic ticket'
    gw_ccxt = UniversalBrokerGateway(protocol='CCXT', broker_config=config_no_url)
    connect_result_ccxt = gw_ccxt.connect()
    assert connect_result_ccxt is False, 'CCXT connection should fail without rest_url'
    res_ccxt = gw_ccxt.execute_order('BTCUSDT', 'BUY', 0.1, 40000, 50000)
    assert res_ccxt['success'] is False, 'CCXT order should fail without rest_url'
    assert res_ccxt['reason'] == 'CONFIGURATION_ERROR'
    gw_ibkr = UniversalBrokerGateway(protocol='IBKR', broker_config=config_no_url)
    connect_result_ibkr = gw_ibkr.connect()
    assert connect_result_ibkr is False, 'IBKR connection should fail without rest_url'
    res_ibkr = gw_ibkr.execute_order('AAPL', 'BUY', 100, 150, 200)
    assert res_ibkr['success'] is False, 'IBKR order should fail without rest_url'
    assert res_ibkr['reason'] == 'CONFIGURATION_ERROR'
    gw_ctrader = UniversalBrokerGateway(protocol='CTRADER', broker_config=config_no_url)
    connect_result_ctrader = gw_ctrader.connect()
    assert connect_result_ctrader is False, 'CTRADER connection should fail without rest_url'
    res_ctrader = gw_ctrader.execute_order('GBPUSD', 'SELL', 0.02, 1.28, 1.26)
    assert res_ctrader['success'] is False, 'CTRADER order should fail without rest_url'
    assert res_ctrader['reason'] == 'CONFIGURATION_ERROR'

def test_universal_broker_gateway_rejects_unsupported_protocol() -> None:
    """
    Tests that unsupported protocols are rejected at initialization to prevent fail-open execution.
    """
    import pytest
    with pytest.raises(ValueError) as exc_info:
        UniversalBrokerGateway(protocol='UNSUPPORTED_PROTOCOL', broker_config={})
    assert 'Unsupported protocol' in str(exc_info.value)
    assert 'UNSUPPORTED_PROTOCOL' in str(exc_info.value)
    with pytest.raises(ValueError) as exc_info2:
        UniversalBrokerGateway(protocol='RANDOM_BROKER', broker_config={})
    assert 'Unsupported protocol' in str(exc_info2.value)
