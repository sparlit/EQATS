"""
Security test for UniversalConnector to verify that non-SIMULATOR protocols
do not silently fall back to simulator mode on connection or execution failures.

This test validates the fix for the security vulnerability where failed live
connections or failed live order executions would unconditionally fall through
to SimulatorConnector, creating synthetic local positions that callers could
not distinguish from real broker executions.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock

import config
import database
from connector import UniversalConnector
from institutional_integrations.universal_broker_adapter import UniversalBrokerGateway


class TestUniversalConnectorSecurityFix(unittest.TestCase):
    """
    Tests that verify UniversalConnector does not silently fall back to
    simulator mode for non-SIMULATOR protocols.
    """

    def setUp(self):
        """Set up test environment with in-memory database."""
        config.DB_PATH = ":memory:"
        database.init_db()

    def test_simulator_protocol_uses_simulator(self):
        """Verify that SIMULATOR protocol correctly uses simulator."""
        conn = UniversalConnector(protocol="SIMULATOR", initial_balance=10000.0)

        # Should connect successfully using simulator
        result = conn.connect()
        self.assertTrue(result)
        self.assertTrue(conn.is_connected())

        # Should execute orders using simulator
        exec_result = conn.execute_order("EURUSD", "BUY", 0.01, 1.0900, 1.1100)
        self.assertTrue(exec_result["success"])
        self.assertIsNotNone(exec_result["ticket"])

    def test_live_protocol_connection_failure_does_not_fallback(self):
        """
        Verify that when a non-SIMULATOR protocol fails to connect,
        it does NOT silently fall back to simulator mode.
        """
        # Mock the gateway to fail connection
        with patch.object(UniversalBrokerGateway, "connect", return_value=False):
            conn = UniversalConnector(protocol="MT5", broker_config={})

            # Connection should fail and return False (not fall back to simulator)
            result = conn.connect()
            self.assertFalse(result)

            # is_connected should return False (not True from simulator)
            self.assertFalse(conn.is_connected())

    def test_live_protocol_connection_exception_raises_error(self):
        """
        Verify that when a non-SIMULATOR protocol raises an exception during connect,
        it propagates the exception (does not silently fall back to simulator).
        """
        # Mock the gateway to raise an exception
        with patch.object(
            UniversalBrokerGateway, "connect", side_effect=Exception("Network error")
        ):
            conn = UniversalConnector(protocol="FIX", broker_config={})

            # Connection should raise ConnectionError
            with self.assertRaises(ConnectionError) as context:
                conn.connect()

            self.assertIn("Failed to connect to live gateway", str(context.exception))
            self.assertIn("FIX", str(context.exception))

    def test_live_protocol_disconnected_gateway_rejects_orders(self):
        """
        Verify that when the live gateway is not connected,
        execute_order returns failure (does not fall back to simulator).
        """
        conn = UniversalConnector(protocol="REST_WS", broker_config={})

        # Mock gateway as disconnected
        with patch.object(conn.gateway, "is_connected", return_value=False):
            exec_result = conn.execute_order("EURUSD", "BUY", 0.01, 1.0900, 1.1100)

            # Should return failure, not success from simulator
            self.assertFalse(exec_result["success"])
            self.assertEqual(exec_result["ticket"], "")
            self.assertIn("not connected", exec_result["error"])
            self.assertIn("REST_WS", exec_result["error"])

    def test_live_protocol_failed_execution_does_not_fallback(self):
        """
        Verify that when a live order execution fails (returns success=False),
        it does NOT fall back to simulator and create a synthetic position.
        """
        conn = UniversalConnector(protocol="IBKR", broker_config={})

        # Mock gateway as connected
        with patch.object(conn.gateway, "is_connected", return_value=True):
            # Mock execute_order to return failure
            failed_response = {
                "success": False,
                "ticket": "",
                "price": 0.0,
                "error": "Insufficient margin",
            }
            with patch.object(
                conn.gateway, "execute_order", return_value=failed_response
            ):
                exec_result = conn.execute_order("EURUSD", "BUY", 0.01, 1.0900, 1.1100)

                # Should return the gateway failure, not simulator success
                self.assertFalse(exec_result["success"])
                self.assertEqual(exec_result["ticket"], "")
                self.assertIn("Insufficient margin", exec_result["error"])

    def test_live_protocol_timeout_does_not_fallback(self):
        """
        Verify that when a live order execution times out or has network failure,
        it does NOT fall back to simulator (critical for preventing duplicate orders).
        """
        conn = UniversalConnector(protocol="CCXT", broker_config={})

        # Mock gateway as connected
        with patch.object(conn.gateway, "is_connected", return_value=True):
            # Mock execute_order to return timeout/network error
            timeout_response = {
                "success": False,
                "ticket": "",
                "price": 0.0,
                "error": "Socket Timeout 3.0s",
                "reason": "NETWORK_UNREACHABLE",
            }
            with patch.object(
                conn.gateway, "execute_order", return_value=timeout_response
            ):
                exec_result = conn.execute_order("BTCUSD", "BUY", 0.1, 50000, 55000)

                # Should return the timeout error, not simulator success
                self.assertFalse(exec_result["success"])
                self.assertEqual(exec_result["ticket"], "")
                self.assertIn("Timeout", exec_result["error"])

    def test_live_protocol_successful_execution_tracked(self):
        """
        Verify that successful live executions are properly tracked
        and do not involve simulator.
        """
        conn = UniversalConnector(protocol="CTRADER", broker_config={})

        # Mock gateway as connected
        with patch.object(conn.gateway, "is_connected", return_value=True):
            # Mock successful execution
            success_response = {
                "success": True,
                "ticket": "LIVE_12345",
                "price": 1.1000,
                "error": "",
            }
            with patch.object(
                conn.gateway, "execute_order", return_value=success_response
            ):
                exec_result = conn.execute_order("EURUSD", "BUY", 0.01, 1.0900, 1.1100)

                # Should return success from gateway
                self.assertTrue(exec_result["success"])
                self.assertEqual(exec_result["ticket"], "LIVE_12345")

                # Ticket should be tracked as live
                self.assertIn("LIVE_12345", conn.live_tickets)

    def test_live_protocol_get_open_orders_does_not_merge_simulator(self):
        """
        Verify that get_open_orders for non-SIMULATOR protocols
        only returns live gateway orders, not simulator orders.
        """
        conn = UniversalConnector(protocol="FIX", broker_config={})

        # Add a fake order to simulator (should not be returned for FIX protocol)
        conn.sim_fallback.execute_order("EURUSD", "BUY", 0.01, 1.0900, 1.1100)

        # Mock gateway as connected with one live order
        live_orders = [{"ticket": "FIX_001", "symbol": "EURUSD", "direction": "BUY"}]
        with patch.object(conn.gateway, "is_connected", return_value=True):
            with patch.object(
                conn.gateway, "get_open_orders", return_value=live_orders
            ):
                orders = conn.get_open_orders()

                # Should only return live orders, not simulator orders
                self.assertEqual(len(orders), 1)
                self.assertEqual(orders[0]["ticket"], "FIX_001")

    def test_live_protocol_disconnected_get_open_orders_returns_empty(self):
        """
        Verify that get_open_orders returns empty list when gateway is disconnected
        for non-SIMULATOR protocols (does not return simulator orders).
        """
        conn = UniversalConnector(protocol="MT5", broker_config={})

        # Add a fake order to simulator (should not be returned for MT5 protocol)
        conn.sim_fallback.execute_order("EURUSD", "BUY", 0.01, 1.0900, 1.1100)

        # Mock gateway as disconnected
        with patch.object(conn.gateway, "is_connected", return_value=False):
            orders = conn.get_open_orders()

            # Should return empty list, not simulator orders
            self.assertEqual(len(orders), 0)

    def test_live_protocol_get_account_info_does_not_fallback(self):
        """
        Verify that get_account_info for disconnected non-SIMULATOR protocols
        returns error state, not simulator account info.
        """
        conn = UniversalConnector(protocol="IBKR", broker_config={})

        # Mock gateway as disconnected
        with patch.object(conn.gateway, "is_connected", return_value=False):
            account_info = conn.get_account_info()

            # Should return error state, not simulator balance
            self.assertEqual(account_info["balance"], 0.0)
            self.assertEqual(account_info["equity"], 0.0)
            self.assertIn("error", account_info)
            self.assertIn("not connected", account_info["error"])


if __name__ == "__main__":
    unittest.main()
