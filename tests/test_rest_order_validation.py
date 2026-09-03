"""
Security test for REST order execution validation.
Tests that the REST order adapter properly validates broker responses
and rejects invalid/incomplete responses that could create phantom positions.

This test validates the fix for the security vulnerability where any parseable
JSON response was treated as a successful order execution, including broker
rejections, pending acknowledgements, and empty objects.
"""

import json
import socket
import urllib.request
from typing import Any
from unittest.mock import MagicMock, Mock, patch

from institutional_integrations.universal_broker_adapter import UniversalBrokerGateway


def test_rejected_order_returns_failure() -> None:
    """Verify that broker rejection response returns failure, not success."""
    config = {"rest_url": "https://test-broker.example.com", "failure_threshold": 5, "retry_backoff_delay": 0.01}
    gw = UniversalBrokerGateway(protocol="REST_WS", broker_config=config)
    mock_response = MagicMock()
    mock_response.getcode.return_value = 200
    mock_response.read.return_value = json.dumps({"status": "REJECTED", "reason": "Insufficient margin"}).encode(
        "utf-8",
    )
    mock_response.__enter__ = Mock(return_value=mock_response)
    mock_response.__exit__ = Mock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_response):
        result = gw.execute_order("EURUSD", "BUY", 0.1, 1.09, 1.11)
        assert result["success"] is False
        assert result["ticket"] == ""
        assert result["price"] == 0.0
        assert "not accepted" in result["error"].lower()
        assert result["reason"] == "REJECTED"


def test_empty_response_returns_failure() -> None:
    """Verify that empty JSON response returns failure, not success."""
    config = {"rest_url": "https://test-broker.example.com", "failure_threshold": 5, "retry_backoff_delay": 0.01}
    gw = UniversalBrokerGateway(protocol="REST_WS", broker_config=config)
    mock_response = MagicMock()
    mock_response.getcode.return_value = 200
    mock_response.read.return_value = json.dumps({}).encode("utf-8")
    mock_response.__enter__ = Mock(return_value=mock_response)
    mock_response.__exit__ = Mock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_response):
        result = gw.execute_order("EURUSD", "BUY", 0.1, 1.09, 1.11)
        assert result["success"] is False
        assert result["ticket"] == ""
        assert result["price"] == 0.0
        assert "not accepted" in result["error"].lower()


def test_pending_order_returns_failure() -> None:
    """Verify that pending order response returns failure, not success."""
    config = {"rest_url": "https://test-broker.example.com", "failure_threshold": 5, "retry_backoff_delay": 0.01}
    gw = UniversalBrokerGateway(protocol="REST_WS", broker_config=config)
    mock_response = MagicMock()
    mock_response.getcode.return_value = 200
    mock_response.read.return_value = json.dumps({"status": "PENDING", "ticket": "BROKER_999"}).encode("utf-8")
    mock_response.__enter__ = Mock(return_value=mock_response)
    mock_response.__exit__ = Mock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_response):
        result = gw.execute_order("EURUSD", "BUY", 0.1, 1.09, 1.11)
        assert result["success"] is False
        assert result["ticket"] == ""
        assert result["price"] == 0.0
        assert "not accepted" in result["error"].lower()
        assert result["reason"] == "PENDING"


def test_missing_ticket_returns_failure() -> None:
    """Verify that response without broker ticket returns failure."""
    config = {"rest_url": "https://test-broker.example.com", "failure_threshold": 5, "retry_backoff_delay": 0.01}
    gw = UniversalBrokerGateway(protocol="REST_WS", broker_config=config)
    mock_response = MagicMock()
    mock_response.getcode.return_value = 200
    mock_response.read.return_value = json.dumps({"status": "ACCEPTED", "price": 1.1}).encode("utf-8")
    mock_response.__enter__ = Mock(return_value=mock_response)
    mock_response.__exit__ = Mock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_response):
        result = gw.execute_order("EURUSD", "BUY", 0.1, 1.09, 1.11)
        assert result["success"] is False
        assert result["ticket"] == ""
        assert result["price"] == 0.0
        assert "missing valid order ticket" in result["error"].lower()
        assert result["reason"] == "MISSING_TICKET"


def test_zero_price_returns_failure() -> None:
    """Verify that response with zero price returns failure."""
    config = {"rest_url": "https://test-broker.example.com", "failure_threshold": 5, "retry_backoff_delay": 0.01}
    gw = UniversalBrokerGateway(protocol="REST_WS", broker_config=config)
    mock_response = MagicMock()
    mock_response.getcode.return_value = 200
    mock_response.read.return_value = json.dumps({"status": "FILLED", "ticket": "BROKER_123", "price": 0.0}).encode(
        "utf-8",
    )
    mock_response.__enter__ = Mock(return_value=mock_response)
    mock_response.__exit__ = Mock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_response):
        result = gw.execute_order("EURUSD", "BUY", 0.1, 1.09, 1.11)
        assert result["success"] is False
        assert result["ticket"] == ""
        assert result["price"] == 0.0
        assert "missing valid execution price" in result["error"].lower()
        assert result["reason"] == "INVALID_PRICE"


def test_missing_price_returns_failure() -> None:
    """Verify that response without price returns failure."""
    config = {"rest_url": "https://test-broker.example.com", "failure_threshold": 5, "retry_backoff_delay": 0.01}
    gw = UniversalBrokerGateway(protocol="REST_WS", broker_config=config)
    mock_response = MagicMock()
    mock_response.getcode.return_value = 200
    mock_response.read.return_value = json.dumps({"status": "ACCEPTED", "ticket": "BROKER_456"}).encode("utf-8")
    mock_response.__enter__ = Mock(return_value=mock_response)
    mock_response.__exit__ = Mock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_response):
        result = gw.execute_order("EURUSD", "BUY", 0.1, 1.09, 1.11)
        assert result["success"] is False
        assert result["ticket"] == ""
        assert result["price"] == 0.0
        assert "missing valid execution price" in result["error"].lower()
        assert result["reason"] == "INVALID_PRICE"


def test_http_error_status_returns_failure() -> None:
    """Verify that non-200/201 HTTP status returns failure."""
    config = {"rest_url": "https://test-broker.example.com", "failure_threshold": 5, "retry_backoff_delay": 0.01}
    gw = UniversalBrokerGateway(protocol="REST_WS", broker_config=config)
    mock_response = MagicMock()
    mock_response.getcode.return_value = 400
    mock_response.read.return_value = json.dumps({"status": "ACCEPTED", "ticket": "BROKER_789", "price": 1.1}).encode(
        "utf-8",
    )
    mock_response.__enter__ = Mock(return_value=mock_response)
    mock_response.__exit__ = Mock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_response):
        result = gw.execute_order("EURUSD", "BUY", 0.1, 1.09, 1.11)
        assert result["success"] is False
        assert result["ticket"] == ""
        assert result["price"] == 0.0
        assert "HTTP 400" in result["error"]
        assert result["reason"] == "HTTP_ERROR"


def test_valid_accepted_order_returns_success() -> None:
    """Verify that valid ACCEPTED order with all fields returns success."""
    config = {"rest_url": "https://test-broker.example.com", "failure_threshold": 5, "retry_backoff_delay": 0.01}
    gw = UniversalBrokerGateway(protocol="REST_WS", broker_config=config)
    mock_response = MagicMock()
    mock_response.getcode.return_value = 200
    mock_response.read.return_value = json.dumps(
        {"status": "ACCEPTED", "ticket": "BROKER_VALID_123", "price": 1.1},
    ).encode("utf-8")
    mock_response.__enter__ = Mock(return_value=mock_response)
    mock_response.__exit__ = Mock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_response):
        result = gw.execute_order("EURUSD", "BUY", 0.1, 1.09, 1.11)
        assert result["success"] is True
        assert result["ticket"] == "BROKER_VALID_123"
        assert result["price"] == 1.1
        assert result["error"] == ""
        assert result["status"] == "ACCEPTED"


def test_valid_filled_order_returns_success() -> None:
    """Verify that valid FILLED order with all fields returns success."""
    config = {"rest_url": "https://test-broker.example.com", "failure_threshold": 5, "retry_backoff_delay": 0.01}
    gw = UniversalBrokerGateway(protocol="REST_WS", broker_config=config)
    mock_response = MagicMock()
    mock_response.getcode.return_value = 201
    mock_response.read.return_value = json.dumps(
        {"status": "FILLED", "ticket": "BROKER_FILLED_456", "price": 1.1005},
    ).encode("utf-8")
    mock_response.__enter__ = Mock(return_value=mock_response)
    mock_response.__exit__ = Mock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_response):
        result = gw.execute_order("EURUSD", "BUY", 0.1, 1.09, 1.11)
        assert result["success"] is True
        assert result["ticket"] == "BROKER_FILLED_456"
        assert result["price"] == 1.1005
        assert result["error"] == ""
        assert result["status"] == "FILLED"


def test_valid_partial_order_returns_success() -> None:
    """Verify that valid PARTIAL order with all fields returns success."""
    config = {"rest_url": "https://test-broker.example.com", "failure_threshold": 5, "retry_backoff_delay": 0.01}
    gw = UniversalBrokerGateway(protocol="REST_WS", broker_config=config)
    mock_response = MagicMock()
    mock_response.getcode.return_value = 200
    mock_response.read.return_value = json.dumps(
        {"status": "PARTIAL", "ticket": "BROKER_PARTIAL_789", "price": 1.0995},
    ).encode("utf-8")
    mock_response.__enter__ = Mock(return_value=mock_response)
    mock_response.__exit__ = Mock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_response):
        result = gw.execute_order("EURUSD", "BUY", 0.1, 1.09, 1.11)
        assert result["success"] is True
        assert result["ticket"] == "BROKER_PARTIAL_789"
        assert result["price"] == 1.0995
        assert result["error"] == ""
        assert result["status"] == "PARTIAL"


def test_order_id_field_accepted_as_ticket() -> None:
    """Verify that order_id field is accepted as alternative to ticket field."""
    config = {"rest_url": "https://test-broker.example.com", "failure_threshold": 5, "retry_backoff_delay": 0.01}
    gw = UniversalBrokerGateway(protocol="REST_WS", broker_config=config)
    mock_response = MagicMock()
    mock_response.getcode.return_value = 200
    mock_response.read.return_value = json.dumps(
        {"status": "ACCEPTED", "order_id": "BROKER_ORDER_999", "price": 1.101},
    ).encode("utf-8")
    mock_response.__enter__ = Mock(return_value=mock_response)
    mock_response.__exit__ = Mock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_response):
        result = gw.execute_order("EURUSD", "BUY", 0.1, 1.09, 1.11)
        assert result["success"] is True
        assert result["ticket"] == "BROKER_ORDER_999"
        assert result["price"] == 1.101
        assert result["error"] == ""


def test_case_insensitive_status_validation() -> None:
    """Verify that status validation is case-insensitive."""
    config = {"rest_url": "https://test-broker.example.com", "failure_threshold": 5, "retry_backoff_delay": 0.01}
    gw = UniversalBrokerGateway(protocol="REST_WS", broker_config=config)
    mock_response = MagicMock()
    mock_response.getcode.return_value = 200
    mock_response.read.return_value = json.dumps(
        {"status": "accepted", "ticket": "BROKER_LOWER_111", "price": 1.102},
    ).encode("utf-8")
    mock_response.__enter__ = Mock(return_value=mock_response)
    mock_response.__exit__ = Mock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_response):
        result = gw.execute_order("EURUSD", "BUY", 0.1, 1.09, 1.11)
        assert result["success"] is True
        assert result["ticket"] == "BROKER_LOWER_111"
        assert result["price"] == 1.102


if __name__ == "__main__":
    print("Running REST order validation security tests...")
    test_rejected_order_returns_failure()
    print("✓ Rejected order returns failure")
    test_empty_response_returns_failure()
    print("✓ Empty response returns failure")
    test_pending_order_returns_failure()
    print("✓ Pending order returns failure")
    test_missing_ticket_returns_failure()
    print("✓ Missing ticket returns failure")
    test_zero_price_returns_failure()
    print("✓ Zero price returns failure")
    test_missing_price_returns_failure()
    print("✓ Missing price returns failure")
    test_http_error_status_returns_failure()
    print("✓ HTTP error status returns failure")
    test_valid_accepted_order_returns_success()
    print("✓ Valid ACCEPTED order returns success")
    test_valid_filled_order_returns_success()
    print("✓ Valid FILLED order returns success")
    test_valid_partial_order_returns_success()
    print("✓ Valid PARTIAL order returns success")
    test_order_id_field_accepted_as_ticket()
    print("✓ order_id field accepted as ticket")
    test_case_insensitive_status_validation()
    print("✓ Case-insensitive status validation")
    print("\n✅ All REST order validation security tests passed!")
