"""
Test suite for UniversalBrokerGateway order validation security fixes.

This test suite verifies that the gateway properly validates:
1. order_type (direction) - must be exactly "BUY" or "SELL"
2. lot_size (quantity) - must be finite, positive, and within bounds

These validations prevent fail-open execution where invalid values
could result in unintended orders being submitted to the broker.
"""

import pytest
from institutional_integrations.universal_broker_adapter import UniversalBrokerGateway


def test_gateway_rejects_invalid_order_type():
    """Test that invalid order_type values are rejected before FIX message construction."""
    gw = UniversalBrokerGateway(protocol="SIMULATOR", broker_config={})
    gw.connect()

    # Test various invalid order_type values that should be rejected
    invalid_directions = [
        "BUYY",  # Typo - should not become SELL
        "SHORT",  # Not BUY, should not become SELL
        "LONG",  # Not BUY, should not become SELL
        "B",  # Abbreviation
        "S",  # Abbreviation
        "buy ",  # Trailing space
        " BUY",  # Leading space
        "",  # Empty string
        "HOLD",  # Invalid direction
        "CANCEL",  # Invalid direction
        123,  # Non-string type
        None,  # None type
        ["BUY"],  # List type
        {"side": "BUY"},  # Dict type
    ]

    for invalid_type in invalid_directions:
        result = gw.execute_order("EURUSD", invalid_type, 0.1, 1.0800, 1.1000)
        assert (
            result["success"] is False
        ), f"Should reject invalid order_type: {invalid_type}"
        assert (
            result["reason"] == "INVALID_DIRECTION"
        ), f"Wrong reason for {invalid_type}"
        assert (
            "Invalid order_type" in result["error"]
        ), f"Wrong error message for {invalid_type}"


def test_gateway_accepts_valid_order_type():
    """Test that valid order_type values (BUY, SELL, case-insensitive) are accepted."""
    gw = UniversalBrokerGateway(protocol="SIMULATOR", broker_config={})
    gw.connect()

    # Test valid order_type values (case-insensitive)
    valid_directions = ["BUY", "SELL", "buy", "sell", "Buy", "Sell", "BuY", "SeLl"]

    for valid_type in valid_directions:
        result = gw.execute_order("EURUSD", valid_type, 0.1, 1.0800, 1.1000)
        # Should not fail with INVALID_DIRECTION
        if not result["success"]:
            assert (
                result["reason"] != "INVALID_DIRECTION"
            ), f"Should accept valid order_type: {valid_type}, got reason: {result['reason']}"


def test_gateway_rejects_invalid_lot_size():
    """Test that invalid lot_size values are rejected before order submission."""
    gw = UniversalBrokerGateway(protocol="SIMULATOR", broker_config={})
    gw.connect()

    # Test non-numeric lot_size values
    invalid_quantities = [
        "abc",  # Non-numeric string
        "0.1lots",  # String with units
        None,  # None type
        [],  # List type
        {},  # Dict type
        "NaN",  # String NaN
    ]

    for invalid_qty in invalid_quantities:
        result = gw.execute_order("EURUSD", "BUY", invalid_qty, 1.0800, 1.1000)
        assert (
            result["success"] is False
        ), f"Should reject non-numeric lot_size: {invalid_qty}"
        assert result["reason"] == "INVALID_QUANTITY", f"Wrong reason for {invalid_qty}"
        assert (
            "Invalid lot_size" in result["error"]
        ), f"Wrong error message for {invalid_qty}"


def test_gateway_rejects_non_finite_lot_size():
    """Test that non-finite lot_size values (inf, -inf, nan) are rejected."""
    gw = UniversalBrokerGateway(protocol="SIMULATOR", broker_config={})
    gw.connect()

    import math

    # Test non-finite numeric values
    non_finite_quantities = [
        float("inf"),  # Positive infinity
        float("-inf"),  # Negative infinity
        float("nan"),  # Not a number
    ]

    for invalid_qty in non_finite_quantities:
        result = gw.execute_order("EURUSD", "BUY", invalid_qty, 1.0800, 1.1000)
        assert (
            result["success"] is False
        ), f"Should reject non-finite lot_size: {invalid_qty}"
        assert result["reason"] == "INVALID_QUANTITY", f"Wrong reason for {invalid_qty}"
        assert (
            "finite and positive" in result["error"]
        ), f"Wrong error message for {invalid_qty}"


def test_gateway_rejects_negative_and_zero_lot_size():
    """Test that negative and zero lot_size values are rejected."""
    gw = UniversalBrokerGateway(protocol="SIMULATOR", broker_config={})
    gw.connect()

    # Test negative and zero values
    invalid_quantities = [
        0.0,  # Zero
        -0.1,  # Negative
        -1.0,  # Negative
        -100.0,  # Large negative
    ]

    for invalid_qty in invalid_quantities:
        result = gw.execute_order("EURUSD", "BUY", invalid_qty, 1.0800, 1.1000)
        assert (
            result["success"] is False
        ), f"Should reject non-positive lot_size: {invalid_qty}"
        assert result["reason"] == "INVALID_QUANTITY", f"Wrong reason for {invalid_qty}"


def test_gateway_rejects_lot_size_below_minimum():
    """Test that lot_size below minimum (0.01) is rejected."""
    gw = UniversalBrokerGateway(protocol="SIMULATOR", broker_config={})
    gw.connect()

    # Test values below minimum
    below_minimum = [0.001, 0.005, 0.009, 0.00001]

    for invalid_qty in below_minimum:
        result = gw.execute_order("EURUSD", "BUY", invalid_qty, 1.0800, 1.1000)
        assert (
            result["success"] is False
        ), f"Should reject lot_size below minimum: {invalid_qty}"
        assert (
            result["reason"] == "QUANTITY_TOO_SMALL"
        ), f"Wrong reason for {invalid_qty}"
        assert (
            "below minimum" in result["error"]
        ), f"Wrong error message for {invalid_qty}"


def test_gateway_rejects_lot_size_above_maximum():
    """Test that lot_size above maximum (100.0) is rejected."""
    gw = UniversalBrokerGateway(protocol="SIMULATOR", broker_config={})
    gw.connect()

    # Test values above maximum
    above_maximum = [100.01, 101.0, 500.0, 1000.0, 10000.0]

    for invalid_qty in above_maximum:
        result = gw.execute_order("EURUSD", "BUY", invalid_qty, 1.0800, 1.1000)
        assert (
            result["success"] is False
        ), f"Should reject lot_size above maximum: {invalid_qty}"
        assert (
            result["reason"] == "QUANTITY_TOO_LARGE"
        ), f"Wrong reason for {invalid_qty}"
        assert (
            "exceeds maximum" in result["error"]
        ), f"Wrong error message for {invalid_qty}"


def test_gateway_accepts_valid_lot_size():
    """Test that valid lot_size values within bounds are accepted."""
    gw = UniversalBrokerGateway(protocol="SIMULATOR", broker_config={})
    gw.connect()

    # Test valid lot_size values within bounds [0.01, 100.0]
    valid_quantities = [
        0.01,  # Minimum
        0.1,  # Small
        1.0,  # Standard
        5.0,  # Medium
        10.0,  # Large
        50.0,  # Very large
        100.0,  # Maximum
    ]

    for valid_qty in valid_quantities:
        result = gw.execute_order("EURUSD", "BUY", valid_qty, 1.0800, 1.1000)
        # Should not fail with quantity-related reasons
        if not result["success"]:
            assert result["reason"] not in [
                "INVALID_QUANTITY",
                "QUANTITY_TOO_SMALL",
                "QUANTITY_TOO_LARGE",
            ], f"Should accept valid lot_size: {valid_qty}, got reason: {result['reason']}"


def test_gateway_validation_order():
    """Test that validation happens before circuit breaker and protocol routing."""
    # Create gateway with invalid configuration to ensure validation happens first
    gw = UniversalBrokerGateway(protocol="SIMULATOR", broker_config={})
    gw.connect()

    # Invalid order_type should be rejected immediately, before any protocol logic
    result = gw.execute_order("EURUSD", "INVALID", 0.1, 1.0800, 1.1000)
    assert result["success"] is False
    assert result["reason"] == "INVALID_DIRECTION"

    # Invalid lot_size should be rejected immediately
    result = gw.execute_order("EURUSD", "BUY", -1.0, 1.0800, 1.1000)
    assert result["success"] is False
    assert result["reason"] == "INVALID_QUANTITY"


def test_gateway_validation_prevents_fix_message_construction():
    """
    Test that validation prevents FIX message construction with invalid values.
    This is the core security fix - invalid values should never reach the FIX engine.
    """
    from institutional_integrations.fix_engine import FIXEngine

    # Create a mock FIX engine to track if create_new_order_single is called
    call_tracker = {"called": False}

    class MockFIXEngine(FIXEngine):
        def create_new_order_single(self, *args, **kwargs):
            call_tracker["called"] = True
            return super().create_new_order_single(*args, **kwargs)

    # Create gateway with FIX protocol
    gw = UniversalBrokerGateway(
        protocol="FIX",
        broker_config={"account_id": "TEST_CLIENT", "server": "TEST_SERVER"},
    )
    gw.fix_engine = MockFIXEngine(sender_comp_id="TEST", target_comp_id="BROKER")

    # Try to execute order with invalid direction
    call_tracker["called"] = False
    result = gw.execute_order("EURUSD", "BUYY", 0.1, 1.0800, 1.1000)
    assert result["success"] is False
    assert result["reason"] == "INVALID_DIRECTION"
    assert not call_tracker[
        "called"
    ], "FIX message should not be created for invalid direction"

    # Try to execute order with invalid quantity
    call_tracker["called"] = False
    result = gw.execute_order("EURUSD", "BUY", 1000.0, 1.0800, 1.1000)
    assert result["success"] is False
    assert result["reason"] == "QUANTITY_TOO_LARGE"
    assert not call_tracker[
        "called"
    ], "FIX message should not be created for invalid quantity"


if __name__ == "__main__":
    # Run tests
    print("Testing gateway order validation...")

    test_gateway_rejects_invalid_order_type()
    print("✓ Invalid order_type rejection test passed")

    test_gateway_accepts_valid_order_type()
    print("✓ Valid order_type acceptance test passed")

    test_gateway_rejects_invalid_lot_size()
    print("✓ Invalid lot_size rejection test passed")

    test_gateway_rejects_non_finite_lot_size()
    print("✓ Non-finite lot_size rejection test passed")

    test_gateway_rejects_negative_and_zero_lot_size()
    print("✓ Negative/zero lot_size rejection test passed")

    test_gateway_rejects_lot_size_below_minimum()
    print("✓ Below-minimum lot_size rejection test passed")

    test_gateway_rejects_lot_size_above_maximum()
    print("✓ Above-maximum lot_size rejection test passed")

    test_gateway_accepts_valid_lot_size()
    print("✓ Valid lot_size acceptance test passed")

    test_gateway_validation_order()
    print("✓ Validation order test passed")

    test_gateway_validation_prevents_fix_message_construction()
    print("✓ FIX message construction prevention test passed")

    print("\n✅ All gateway validation tests passed!")
