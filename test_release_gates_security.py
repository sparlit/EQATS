"""
Security test for ReleaseGateRunner to verify that live broker connectors
are blocked from release validation and that G11 properly validates execution
without allowing real trades.

This test validates the fix for the security vulnerability where ReleaseGateRunner
could accept a live-capable connector and execute real broker orders during G11
validation.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch

import config
import connector
import database
import release_gates


class MockLiveConnector(connector.TradingConnector):
    """Mock connector that simulates a live broker connection (unsafe for testing)."""

    def __init__(self):
        self.is_demo = False
        self.demo_only = False

    def connect(self):
        return True

    def is_connected(self):
        return True

    def disconnect(self):
        pass

    def get_account_info(self):
        return {
            "balance": 10000.0,
            "equity": 10000.0,
            "currency": "USD",
            "is_demo": False,  # LIVE account
        }

    def get_history(self, symbol, count):
        return []

    def get_current_price(self, symbol):
        return {"bid": 1.0850, "ask": 1.0852}

    def execute_order(self, symbol, order_type, lot_size, sl, tp):
        # This should NEVER be called during release validation
        return {"success": True, "ticket": "LIVE-12345", "price": 1.0851, "error": None}

    def close_order(self, ticket, reason="MANUAL"):
        return {"success": True, "price": 1.0851, "profit": 0.0, "error": None}

    def modify_order(self, ticket, sl, tp):
        return True

    def get_open_orders(self):
        return []

    def draw_dashboard(self, symbol, data):
        pass

    def get_symbol_volume_constraints(self, symbol="EURUSD"):
        return {"min_lot": 0.01, "max_lot": 100.0, "step_lot": 0.01}


class MockDemoConnector(connector.TradingConnector):
    """Mock connector that simulates a demo broker connection (safe for testing)."""

    def __init__(self):
        self.is_demo = True
        self.demo_only = True

    def connect(self):
        return True

    def is_connected(self):
        return True

    def disconnect(self):
        pass

    def get_account_info(self):
        return {
            "balance": 10000.0,
            "equity": 10000.0,
            "currency": "USD",
            "is_demo": True,  # DEMO account
        }

    def get_history(self, symbol, count):
        return []

    def get_current_price(self, symbol):
        return {"bid": 1.0850, "ask": 1.0852}

    def execute_order(self, symbol, order_type, lot_size, sl, tp):
        return {"success": True, "ticket": "DEMO-12345", "price": 1.0851, "error": None}

    def close_order(self, ticket, reason="MANUAL"):
        return {"success": True, "price": 1.0851, "profit": 0.0, "error": None}

    def modify_order(self, ticket, sl, tp):
        return True

    def get_open_orders(self):
        return [
            {
                "ticket": "DEMO-12345",
                "symbol": "EURUSD",
                "direction": "BUY",
                "open_price": 1.0851,
                "sl": 1.0800,
                "tp": 1.1000,
                "lot_size": 0.1,
            }
        ]

    def draw_dashboard(self, symbol, data):
        pass

    def get_symbol_volume_constraints(self, symbol="EURUSD"):
        return {"min_lot": 0.01, "max_lot": 100.0, "step_lot": 0.01}


class TestReleaseGatesSecurity(unittest.TestCase):
    """Test suite for ReleaseGateRunner security controls."""

    def setUp(self):
        """Initialize database before each test."""
        database.init_db()

    def test_live_connector_blocked_in_constructor(self):
        """Test that ReleaseGateRunner blocks live connectors in constructor."""
        live_conn = MockLiveConnector()

        with self.assertRaises(PermissionError) as context:
            runner = release_gates.ReleaseGateRunner(conn=live_conn)

        self.assertIn("CRITICAL SAFETY BLOCK", str(context.exception))
        self.assertIn("SimulatorConnector", str(context.exception))

    def test_simulator_connector_allowed(self):
        """Test that SimulatorConnector is allowed."""
        sim_conn = connector.SimulatorConnector(initial_balance=10000.0)

        # Should not raise an exception
        runner = release_gates.ReleaseGateRunner(conn=sim_conn)
        self.assertIsNotNone(runner)
        self.assertEqual(runner.conn, sim_conn)

    def test_demo_connector_allowed(self):
        """Test that demo-only connectors are allowed."""
        demo_conn = MockDemoConnector()

        # Should not raise an exception
        runner = release_gates.ReleaseGateRunner(conn=demo_conn)
        self.assertIsNotNone(runner)
        self.assertEqual(runner.conn, demo_conn)

    def test_default_connector_is_simulator(self):
        """Test that default connector is SimulatorConnector."""
        runner = release_gates.ReleaseGateRunner()
        self.assertIsInstance(runner.conn, connector.SimulatorConnector)

    def test_is_safe_connector_validates_simulator(self):
        """Test _is_safe_connector correctly identifies SimulatorConnector."""
        runner = release_gates.ReleaseGateRunner()
        sim_conn = connector.SimulatorConnector(initial_balance=10000.0)

        self.assertTrue(runner._is_safe_connector(sim_conn))

    def test_is_safe_connector_rejects_live(self):
        """Test _is_safe_connector correctly rejects live connectors."""
        runner = release_gates.ReleaseGateRunner()
        live_conn = MockLiveConnector()

        self.assertFalse(runner._is_safe_connector(live_conn))

    def test_is_safe_connector_accepts_demo(self):
        """Test _is_safe_connector correctly accepts demo connectors."""
        runner = release_gates.ReleaseGateRunner()
        demo_conn = MockDemoConnector()

        self.assertTrue(runner._is_safe_connector(demo_conn))

    @patch("config.SIMULATION_MODE", False)
    @patch("config.DEMO_ACCOUNT_ONLY", False)
    def test_g11_blocks_non_demo_mode(self):
        """Test that G11 blocks execution when DEMO_ACCOUNT_ONLY is False."""
        runner = release_gates.ReleaseGateRunner()

        passed, reason = runner._check_g11_independent_execution_verification()

        self.assertFalse(passed)
        self.assertIn("SECURITY VIOLATION", reason)
        self.assertIn("DEMO_ACCOUNT_ONLY", reason)

    @patch("config.SIMULATION_MODE", True)
    def test_g11_allows_simulation_mode(self):
        """Test that G11 allows execution in SIMULATION_MODE."""
        runner = release_gates.ReleaseGateRunner()

        passed, reason = runner._check_g11_independent_execution_verification()

        # Should pass or fail based on execution, not security
        self.assertIsInstance(passed, bool)
        self.assertNotIn("SECURITY VIOLATION", reason)

    def test_g11_validates_order_parameters(self):
        """Test that G11 properly validates order parameters match."""
        runner = release_gates.ReleaseGateRunner()

        # Mock the connector to return specific values
        mock_conn = Mock(spec=connector.SimulatorConnector)
        mock_conn.is_demo = True

        # Setup execute_order to return success
        mock_conn.execute_order.return_value = {
            "success": True,
            "ticket": "TEST-123",
            "price": 1.0851,
        }

        # Setup get_open_orders to return matching order
        mock_conn.get_open_orders.return_value = [
            {
                "ticket": "TEST-123",
                "symbol": "EURUSD",
                "direction": "BUY",
                "open_price": 1.0851,
                "sl": 1.0800,
                "tp": 1.1000,
                "lot_size": 0.1,
            }
        ]

        # Setup close_order to return success
        mock_conn.close_order.return_value = {
            "success": True,
            "price": 1.0851,
            "profit": 0.0,
        }

        runner.conn = mock_conn

        with patch("config.SIMULATION_MODE", True):
            passed, reason = runner._check_g11_independent_execution_verification()

        self.assertTrue(passed)
        self.assertIn("successfully", reason.lower())

        # Verify execute_order was called
        mock_conn.execute_order.assert_called_once()

        # Verify close_order was called for cleanup
        mock_conn.close_order.assert_called_once_with("TEST-123")

    def test_g11_fails_on_execution_error(self):
        """Test that G11 fails when execution returns error."""
        runner = release_gates.ReleaseGateRunner()

        # Mock the connector to return failure
        mock_conn = Mock(spec=connector.SimulatorConnector)
        mock_conn.is_demo = True

        mock_conn.execute_order.return_value = {
            "success": False,
            "error": "Insufficient margin",
        }

        runner.conn = mock_conn

        with patch("config.SIMULATION_MODE", True):
            passed, reason = runner._check_g11_independent_execution_verification()

        self.assertFalse(passed)
        self.assertIn("Execution verification failed", reason)

    def test_g11_fails_on_parameter_mismatch(self):
        """Test that G11 fails when order parameters don't match."""
        runner = release_gates.ReleaseGateRunner()

        # Mock the connector
        mock_conn = Mock(spec=connector.SimulatorConnector)
        mock_conn.is_demo = True

        mock_conn.execute_order.return_value = {
            "success": True,
            "ticket": "TEST-123",
            "price": 1.0851,
        }

        # Return order with wrong symbol
        mock_conn.get_open_orders.return_value = [
            {
                "ticket": "TEST-123",
                "symbol": "GBPUSD",  # Wrong symbol!
                "direction": "BUY",
                "open_price": 1.0851,
                "sl": 1.0800,
                "tp": 1.1000,
                "lot_size": 0.1,
            }
        ]

        mock_conn.close_order.return_value = {"success": True}

        runner.conn = mock_conn

        with patch("config.SIMULATION_MODE", True):
            passed, reason = runner._check_g11_independent_execution_verification()

        self.assertFalse(passed)
        self.assertIn("Parameter mismatch", reason)
        self.assertIn("symbol", reason.lower())

    def test_g11_fails_on_cleanup_failure(self):
        """Test that G11 fails when order cleanup fails."""
        runner = release_gates.ReleaseGateRunner()

        # Mock the connector
        mock_conn = Mock(spec=connector.SimulatorConnector)
        mock_conn.is_demo = True

        mock_conn.execute_order.return_value = {
            "success": True,
            "ticket": "TEST-123",
            "price": 1.0851,
        }

        mock_conn.get_open_orders.return_value = [
            {
                "ticket": "TEST-123",
                "symbol": "EURUSD",
                "direction": "BUY",
                "open_price": 1.0851,
                "sl": 1.0800,
                "tp": 1.1000,
                "lot_size": 0.1,
            }
        ]

        # Cleanup fails
        mock_conn.close_order.return_value = {
            "success": False,
            "error": "Order not found",
        }

        runner.conn = mock_conn

        with patch("config.SIMULATION_MODE", True):
            passed, reason = runner._check_g11_independent_execution_verification()

        self.assertFalse(passed)
        self.assertIn("cleanup failed", reason.lower())


if __name__ == "__main__":
    unittest.main()
