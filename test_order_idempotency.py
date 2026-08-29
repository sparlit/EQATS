"""
Unit tests for order execution idempotency and reconciliation.
Tests that the REST order execution path includes client_order_id
and performs reconciliation after timeout to prevent duplicate orders.
"""

import json
import socket
import time
from unittest.mock import Mock, patch, MagicMock
import urllib.request
import urllib.error

from institutional_integrations.universal_broker_adapter import UniversalBrokerGateway


def test_rest_order_includes_client_order_id():
    """Verify that REST order payload includes client_order_id for idempotency."""
    config = {
        "rest_url": "https://test-broker.example.com",
        "failure_threshold": 5,
        "retry_backoff_delay": 0.01,
    }
    gw = UniversalBrokerGateway(protocol="REST_WS", broker_config=config)

    # Mock successful response
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(
        {"ticket": "BROKER_12345", "price": 1.1000}
    ).encode("utf-8")
    mock_response.__enter__ = Mock(return_value=mock_response)
    mock_response.__exit__ = Mock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        result = gw.execute_order("EURUSD", "BUY", 0.1, 1.0900, 1.1100)

        # Verify order was successful
        assert result["success"] is True
        assert result["ticket"] == "BROKER_12345"

        # Verify the request was made
        assert mock_urlopen.called
        call_args = mock_urlopen.call_args
        request_obj = call_args[0][0]

        # Verify payload includes client_order_id
        payload = json.loads(request_obj.data.decode("utf-8"))
        assert "client_order_id" in payload
        assert payload["client_order_id"].startswith("EQATS_")
        assert payload["symbol"] == "EURUSD"
        assert payload["side"] == "BUY"
        assert payload["volume"] == 0.1


def test_timeout_triggers_reconciliation():
    """Verify that timeout exception triggers order reconciliation."""
    config = {
        "rest_url": "https://test-broker.example.com",
        "failure_threshold": 5,
        "retry_backoff_delay": 0.01,
    }
    gw = UniversalBrokerGateway(protocol="REST_WS", broker_config=config)

    # Track the client_order_id used
    captured_client_order_id = None

    def capture_request_and_timeout(*args, **kwargs):
        nonlocal captured_client_order_id
        request_obj = args[0]
        payload = json.loads(request_obj.data.decode("utf-8"))
        captured_client_order_id = payload["client_order_id"]
        raise socket.timeout("Connection timed out")

    # Mock reconciliation to return order found
    def mock_reconcile(client_order_id):
        return {
            "found": True,
            "ticket": "BROKER_RECONCILED_999",
            "price": 1.1005,
            "status": "FILLED",
        }

    with patch("urllib.request.urlopen", side_effect=capture_request_and_timeout):
        with patch.object(
            gw, "_reconcile_order_status", side_effect=mock_reconcile
        ) as mock_reconcile_method:
            result = gw.execute_order("EURUSD", "BUY", 0.1, 1.0900, 1.1100)

            # Verify reconciliation was called
            assert mock_reconcile_method.called
            assert captured_client_order_id is not None

            # Verify reconciliation returned the found order
            assert result["success"] is True
            assert result["ticket"] == "BROKER_RECONCILED_999"
            assert result["price"] == 1.1005
            assert result.get("reconciled") is True


def test_reconciliation_prevents_duplicate_on_timeout():
    """Verify that when reconciliation finds the order, no retry is attempted."""
    config = {
        "rest_url": "https://test-broker.example.com",
        "failure_threshold": 5,
        "retry_backoff_delay": 0.01,
    }
    gw = UniversalBrokerGateway(protocol="REST_WS", broker_config=config)

    call_count = 0

    def timeout_on_first_call(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise socket.timeout("Connection timed out")

    # Mock reconciliation to return order found
    def mock_reconcile(client_order_id):
        return {
            "found": True,
            "ticket": "BROKER_FOUND_888",
            "price": 1.1010,
            "status": "ACCEPTED",
        }

    with patch("urllib.request.urlopen", side_effect=timeout_on_first_call):
        with patch.object(gw, "_reconcile_order_status", side_effect=mock_reconcile):
            result = gw.execute_order("EURUSD", "BUY", 0.1, 1.0900, 1.1100)

            # Should only call once since reconciliation found the order
            assert call_count == 1
            assert result["success"] is True
            assert result["ticket"] == "BROKER_FOUND_888"
            assert result.get("reconciled") is True


def test_reconciliation_allows_retry_when_order_not_found():
    """Verify that when reconciliation doesn't find the order, retry proceeds."""
    config = {
        "rest_url": "https://test-broker.example.com",
        "failure_threshold": 5,
        "retry_backoff_delay": 0.01,
    }
    gw = UniversalBrokerGateway(protocol="REST_WS", broker_config=config)

    call_count = 0

    def timeout_then_succeed(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise socket.timeout("Connection timed out")
        else:
            # Second attempt succeeds
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps(
                {"ticket": "BROKER_RETRY_777", "price": 1.1015}
            ).encode("utf-8")
            mock_response.__enter__ = Mock(return_value=mock_response)
            mock_response.__exit__ = Mock(return_value=False)
            return mock_response

    # Mock reconciliation to return order NOT found
    def mock_reconcile(client_order_id):
        return {"found": False}

    with patch("urllib.request.urlopen", side_effect=timeout_then_succeed):
        with patch.object(gw, "_reconcile_order_status", side_effect=mock_reconcile):
            result = gw.execute_order("EURUSD", "BUY", 0.1, 1.0900, 1.1100)

            # Should call twice: first timeout, then retry succeeds
            assert call_count == 2
            assert result["success"] is True
            assert result["ticket"] == "BROKER_RETRY_777"
            assert (
                result.get("reconciled") is not True
            )  # Not reconciled, direct success


def test_same_client_order_id_used_across_retries():
    """Verify that the same client_order_id is used for both retry attempts."""
    config = {
        "rest_url": "https://test-broker.example.com",
        "failure_threshold": 5,
        "retry_backoff_delay": 0.01,
    }
    gw = UniversalBrokerGateway(protocol="REST_WS", broker_config=config)

    captured_client_order_ids = []

    def capture_and_timeout(*args, **kwargs):
        request_obj = args[0]
        payload = json.loads(request_obj.data.decode("utf-8"))
        captured_client_order_ids.append(payload["client_order_id"])
        raise socket.timeout("Connection timed out")

    # Mock reconciliation to return order NOT found (so retry proceeds)
    def mock_reconcile(client_order_id):
        return {"found": False}

    with patch("urllib.request.urlopen", side_effect=capture_and_timeout):
        with patch.object(gw, "_reconcile_order_status", side_effect=mock_reconcile):
            result = gw.execute_order("EURUSD", "BUY", 0.1, 1.0900, 1.1100)

            # Should have attempted twice
            assert len(captured_client_order_ids) == 2
            # Both attempts should use the SAME client_order_id
            assert captured_client_order_ids[0] == captured_client_order_ids[1]
            assert result["success"] is False  # Both attempts failed


def test_generic_exception_also_triggers_reconciliation():
    """Verify that generic exceptions also trigger reconciliation."""
    config = {
        "rest_url": "https://test-broker.example.com",
        "failure_threshold": 5,
        "retry_backoff_delay": 0.01,
    }
    gw = UniversalBrokerGateway(protocol="REST_WS", broker_config=config)

    def raise_generic_exception(*args, **kwargs):
        raise Exception("Unexpected error during request")

    # Mock reconciliation to return order found
    def mock_reconcile(client_order_id):
        return {
            "found": True,
            "ticket": "BROKER_EXCEPTION_666",
            "price": 1.1020,
            "status": "FILLED",
        }

    with patch("urllib.request.urlopen", side_effect=raise_generic_exception):
        with patch.object(
            gw, "_reconcile_order_status", side_effect=mock_reconcile
        ) as mock_reconcile_method:
            result = gw.execute_order("EURUSD", "BUY", 0.1, 1.0900, 1.1100)

            # Verify reconciliation was called
            assert mock_reconcile_method.called

            # Verify reconciliation returned the found order
            assert result["success"] is True
            assert result["ticket"] == "BROKER_EXCEPTION_666"
            assert result.get("reconciled") is True


def test_reconcile_order_status_method():
    """Test the _reconcile_order_status method directly."""
    config = {
        "rest_url": "https://test-broker.example.com",
        "failure_threshold": 5,
    }
    gw = UniversalBrokerGateway(protocol="REST_WS", broker_config=config)

    # Mock successful reconciliation response
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(
        {"found": True, "status": "FILLED", "ticket": "BROKER_555", "price": 1.1025}
    ).encode("utf-8")
    mock_response.__enter__ = Mock(return_value=mock_response)
    mock_response.__exit__ = Mock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        result = gw._reconcile_order_status("EQATS_test123_1234567890")

        # Verify reconciliation found the order
        assert result["found"] is True
        assert result["ticket"] == "BROKER_555"
        assert result["price"] == 1.1025

        # Verify the correct endpoint was called
        assert mock_urlopen.called
        call_args = mock_urlopen.call_args
        request_obj = call_args[0][0]
        assert "/v1/order/status" in request_obj.full_url
        assert "client_order_id=EQATS_test123_1234567890" in request_obj.full_url


def test_reconcile_order_status_not_found():
    """Test reconciliation when order is not found at broker."""
    config = {
        "rest_url": "https://test-broker.example.com",
        "failure_threshold": 5,
    }
    gw = UniversalBrokerGateway(protocol="REST_WS", broker_config=config)

    # Mock response indicating order not found
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"found": False}).encode("utf-8")
    mock_response.__enter__ = Mock(return_value=mock_response)
    mock_response.__exit__ = Mock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_response):
        result = gw._reconcile_order_status("EQATS_test456_9876543210")

        # Verify reconciliation did not find the order
        assert result["found"] is False


def test_reconcile_handles_query_failure():
    """Test that reconciliation gracefully handles query failures."""
    config = {
        "rest_url": "https://test-broker.example.com",
        "failure_threshold": 5,
    }
    gw = UniversalBrokerGateway(protocol="REST_WS", broker_config=config)

    # Mock query failure
    with patch("urllib.request.urlopen", side_effect=socket.timeout("Query timeout")):
        result = gw._reconcile_order_status("EQATS_test789_1111111111")

        # Should return not found when query fails
        assert result["found"] is False


if __name__ == "__main__":
    print("Running order idempotency tests...")

    test_rest_order_includes_client_order_id()
    print("✓ REST order includes client_order_id")

    test_timeout_triggers_reconciliation()
    print("✓ Timeout triggers reconciliation")

    test_reconciliation_prevents_duplicate_on_timeout()
    print("✓ Reconciliation prevents duplicate on timeout")

    test_reconciliation_allows_retry_when_order_not_found()
    print("✓ Reconciliation allows retry when order not found")

    test_same_client_order_id_used_across_retries()
    print("✓ Same client_order_id used across retries")

    test_generic_exception_also_triggers_reconciliation()
    print("✓ Generic exception also triggers reconciliation")

    test_reconcile_order_status_method()
    print("✓ Reconcile order status method works")

    test_reconcile_order_status_not_found()
    print("✓ Reconcile handles order not found")

    test_reconcile_handles_query_failure()
    print("✓ Reconcile handles query failure")

    print("\nAll idempotency tests passed!")
