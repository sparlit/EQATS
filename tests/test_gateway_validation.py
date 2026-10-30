"""
Test suite for UniversalBrokerGateway order validation security fixes.

This test suite verifies that the gateway properly validates:
1. order_type (direction) - must be exactly "BUY" or "SELL"
2. lot_size (quantity) - must be finite, positive, and within bounds

These validations prevent fail-open execution where invalid values
could result in unintended orders being submitted to the broker.
"""
from typing import Any

from institutional_integrations.universal_broker_adapter import UniversalBrokerGateway


def test_gateway_rejects_invalid_order_type() -> None:
    """Test that invalid order_type values are rejected before FIX message construction."""
    gw = UniversalBrokerGateway(protocol='SIMULATOR', broker_config={})
    gw.connect()
    invalid_directions = ['BUYY', 'SHORT', 'LONG', 'B', 'S', 'buy ', ' BUY', '', 'HOLD', 'CANCEL', 123, None, ['BUY'], {'side': 'BUY'}]
    for invalid_type in invalid_directions:
        result = gw.execute_order('EURUSD', invalid_type, 0.1, 1.08, 1.1)
        assert result['success'] is False, f'Should reject invalid order_type: {invalid_type}'
        assert result['reason'] == 'INVALID_DIRECTION', f'Wrong reason for {invalid_type}'
        assert 'Invalid order_type' in result['error'], f'Wrong error message for {invalid_type}'

def test_gateway_accepts_valid_order_type() -> None:
    """Test that valid order_type values (BUY, SELL, case-insensitive) are accepted."""
    gw = UniversalBrokerGateway(protocol='SIMULATOR', broker_config={})
    gw.connect()
    valid_directions = ['BUY', 'SELL', 'buy', 'sell', 'Buy', 'Sell', 'BuY', 'SeLl']
    for valid_type in valid_directions:
        result = gw.execute_order('EURUSD', valid_type, 0.1, 1.08, 1.1)
        if not result['success']:
            assert result['reason'] != 'INVALID_DIRECTION', f"Should accept valid order_type: {valid_type}, got reason: {result['reason']}"

def test_gateway_rejects_invalid_lot_size() -> None:
    """Test that invalid lot_size values are rejected before order submission."""
    gw = UniversalBrokerGateway(protocol='SIMULATOR', broker_config={})
    gw.connect()
    invalid_quantities = ['abc', '0.1lots', None, [], {}, 'NaN']
    for invalid_qty in invalid_quantities:
        result = gw.execute_order('EURUSD', 'BUY', invalid_qty, 1.08, 1.1)
        assert result['success'] is False, f'Should reject non-numeric lot_size: {invalid_qty}'
        assert result['reason'] == 'INVALID_QUANTITY', f'Wrong reason for {invalid_qty}'
        assert 'Invalid lot_size' in result['error'], f'Wrong error message for {invalid_qty}'

def test_gateway_rejects_non_finite_lot_size() -> None:
    """Test that non-finite lot_size values (inf, -inf, nan) are rejected."""
    gw = UniversalBrokerGateway(protocol='SIMULATOR', broker_config={})
    gw.connect()
    non_finite_quantities = [float('inf'), float('-inf'), float('nan')]
    for invalid_qty in non_finite_quantities:
        result = gw.execute_order('EURUSD', 'BUY', invalid_qty, 1.08, 1.1)
        assert result['success'] is False, f'Should reject non-finite lot_size: {invalid_qty}'
        assert result['reason'] == 'INVALID_QUANTITY', f'Wrong reason for {invalid_qty}'
        assert 'finite and positive' in result['error'], f'Wrong error message for {invalid_qty}'

def test_gateway_rejects_negative_and_zero_lot_size() -> None:
    """Test that negative and zero lot_size values are rejected."""
    gw = UniversalBrokerGateway(protocol='SIMULATOR', broker_config={})
    gw.connect()
    invalid_quantities = [0.0, -0.1, -1.0, -100.0]
    for invalid_qty in invalid_quantities:
        result = gw.execute_order('EURUSD', 'BUY', invalid_qty, 1.08, 1.1)
        assert result['success'] is False, f'Should reject non-positive lot_size: {invalid_qty}'
        assert result['reason'] == 'INVALID_QUANTITY', f'Wrong reason for {invalid_qty}'

def test_gateway_rejects_lot_size_below_minimum() -> None:
    """Test that lot_size below minimum (0.01) is rejected."""
    gw = UniversalBrokerGateway(protocol='SIMULATOR', broker_config={})
    gw.connect()
    below_minimum = [0.001, 0.005, 0.009, 1e-05]
    for invalid_qty in below_minimum:
        result = gw.execute_order('EURUSD', 'BUY', invalid_qty, 1.08, 1.1)
        assert result['success'] is False, f'Should reject lot_size below minimum: {invalid_qty}'
        assert result['reason'] == 'QUANTITY_TOO_SMALL', f'Wrong reason for {invalid_qty}'
        assert 'below minimum' in result['error'], f'Wrong error message for {invalid_qty}'

def test_gateway_rejects_lot_size_above_maximum() -> None:
    """Test that lot_size above maximum (100.0) is rejected."""
    gw = UniversalBrokerGateway(protocol='SIMULATOR', broker_config={})
    gw.connect()
    above_maximum = [100.01, 101.0, 500.0, 1000.0, 10000.0]
    for invalid_qty in above_maximum:
        result = gw.execute_order('EURUSD', 'BUY', invalid_qty, 1.08, 1.1)
        assert result['success'] is False, f'Should reject lot_size above maximum: {invalid_qty}'
        assert result['reason'] == 'QUANTITY_TOO_LARGE', f'Wrong reason for {invalid_qty}'
        assert 'exceeds maximum' in result['error'], f'Wrong error message for {invalid_qty}'

def test_gateway_accepts_valid_lot_size() -> None:
    """Test that valid lot_size values within bounds are accepted."""
    gw = UniversalBrokerGateway(protocol='SIMULATOR', broker_config={})
    gw.connect()
    valid_quantities = [0.01, 0.1, 1.0, 5.0, 10.0, 50.0, 100.0]
    for valid_qty in valid_quantities:
        result = gw.execute_order('EURUSD', 'BUY', valid_qty, 1.08, 1.1)
        if not result['success']:
            assert result['reason'] not in ['INVALID_QUANTITY', 'QUANTITY_TOO_SMALL', 'QUANTITY_TOO_LARGE'], f"Should accept valid lot_size: {valid_qty}, got reason: {result['reason']}"

def test_gateway_validation_order() -> None:
    """Test that validation happens before circuit breaker and protocol routing."""
    gw = UniversalBrokerGateway(protocol='SIMULATOR', broker_config={})
    gw.connect()
    result = gw.execute_order('EURUSD', 'INVALID', 0.1, 1.08, 1.1)
    assert result['success'] is False
    assert result['reason'] == 'INVALID_DIRECTION'
    result = gw.execute_order('EURUSD', 'BUY', -1.0, 1.08, 1.1)
    assert result['success'] is False
    assert result['reason'] == 'INVALID_QUANTITY'

def test_gateway_validation_prevents_fix_message_construction() -> Any:
    """
    Test that validation prevents FIX message construction with invalid values.
    This is the core security fix - invalid values should never reach the FIX engine.
    """
    from institutional_integrations.fix_engine import FIXEngine
    call_tracker = {'called': False}

    class MockFIXEngine(FIXEngine):

        def send_new_order_single(self, *args: Any, **kwargs: Any) -> Any:
            call_tracker['called'] = True
            return '8=FIX.4.4...'
    gw = UniversalBrokerGateway(protocol='FIX', broker_config={'account_id': 'TEST_CLIENT', 'server': 'TEST_SERVER'})
    gw.fix_engine = MockFIXEngine(sender_comp_id='TEST', target_comp_id='BROKER')
    call_tracker['called'] = False
    result = gw.execute_order('EURUSD', 'BUYY', 0.1, 1.08, 1.1)
    assert result['success'] is False
    assert result['reason'] == 'INVALID_DIRECTION'
    assert not call_tracker['called'], 'FIX message should not be created for invalid direction'
    call_tracker['called'] = False
    result = gw.execute_order('EURUSD', 'BUY', 1000.0, 1.08, 1.1)
    assert result['success'] is False
    assert result['reason'] == 'QUANTITY_TOO_LARGE'
    assert not call_tracker['called'], 'FIX message should not be created for invalid quantity'


def test_fix_atomic_send_methods_invoked() -> None:
    """
    Test that UniversalBrokerGateway uses atomic send methods on FIXEngine
    for modify_order, execute_order, and close_order to prevent out-of-order transmission.
    """
    from institutional_integrations.fix_engine import FIXEngine

    calls = []

    class MockAtomicFIXEngine(FIXEngine):
        def send_new_order_single(self, cl_ord_id: Any, symbol: Any, side: Any, quantity: Any, ord_type: Any, price: Any) -> Any:
            calls.append(('send_new_order_single', cl_ord_id, symbol, side, quantity, ord_type, price))
            return "8=FIX.4.4..."

        def send_order_cancel_replace_request(self, cl_ord_id: Any, orig_cl_ord_id: Any, stop_px: Any = None, price: Any = None) -> Any:
            calls.append(('send_order_cancel_replace_request', cl_ord_id, orig_cl_ord_id, stop_px, price))
            return "8=FIX.4.4..."

        def send_order_cancel_request(self, cl_ord_id: Any, orig_cl_ord_id: Any) -> Any:
            calls.append(('send_order_cancel_request', cl_ord_id, orig_cl_ord_id))
            return "8=FIX.4.4..."

    gw = UniversalBrokerGateway(protocol='FIX', broker_config={'account_id': 'TEST_CLIENT', 'server': 'TEST_SERVER'})
    mock_engine = MockAtomicFIXEngine(sender_comp_id='TEST', target_comp_id='BROKER')
    gw.fix_engine = mock_engine
    gw.is_connected_flag = True

    # 1. Test execute_order invokes send_new_order_single
    exec_res = gw.execute_order('EURUSD', 'BUY', 1.0, 1.08, 1.10)
    assert exec_res['success'] is True
    assert len(calls) == 1
    assert calls[0][0] == 'send_new_order_single'
    assert calls[0][2] == 'EURUSD'

    # 2. Test modify_order invokes send_order_cancel_replace_request
    mod_res = gw.modify_order('TICKET123', 1.085, 1.105)
    assert mod_res is True
    assert len(calls) == 2
    assert calls[1][0] == 'send_order_cancel_replace_request'
    assert calls[1][2] == 'TICKET123'
    assert calls[1][3] == 1.085
    assert calls[1][4] == 1.105

    # 3. Test close_order invokes send_order_cancel_request
    close_res = gw.close_order('TICKET123', reason='TP')
    assert close_res['success'] is True
    assert len(calls) == 3
    assert calls[2][0] == 'send_order_cancel_request'
    assert calls[2][2] == 'TICKET123'
if __name__ == '__main__':
    print('Testing gateway order validation...')
    test_gateway_rejects_invalid_order_type()
    print('✓ Invalid order_type rejection test passed')
    test_gateway_accepts_valid_order_type()
    print('✓ Valid order_type acceptance test passed')
    test_gateway_rejects_invalid_lot_size()
    print('✓ Invalid lot_size rejection test passed')
    test_gateway_rejects_non_finite_lot_size()
    print('✓ Non-finite lot_size rejection test passed')
    test_gateway_rejects_negative_and_zero_lot_size()
    print('✓ Negative/zero lot_size rejection test passed')
    test_gateway_rejects_lot_size_below_minimum()
    print('✓ Below-minimum lot_size rejection test passed')
    test_gateway_rejects_lot_size_above_maximum()
    print('✓ Above-maximum lot_size rejection test passed')
    test_gateway_accepts_valid_lot_size()
    print('✓ Valid lot_size acceptance test passed')
    test_gateway_validation_order()
    print('✓ Validation order test passed')
    test_gateway_validation_prevents_fix_message_construction()
    print('✓ FIX message construction prevention test passed')
    print('\n✅ All gateway validation tests passed!')
