"""
Security test for ReleaseGateRunner to verify that live broker connectors
are blocked from release validation and that G11 properly validates execution
without allowing real trades.

This test validates the fix for the security vulnerability where ReleaseGateRunner
could accept a live-capable connector and execute real broker orders during G11
validation.
"""
from typing import Any
import unittest
from unittest.mock import Mock, patch

import connector
import database
import release_gates

class MockLiveConnector(connector.TradingConnector):
    """Mock connector that simulates a live broker connection (unsafe for testing)."""

    def __init__(self) -> None:
        self.is_demo = False
        self.demo_only = False

    def connect(self) -> Any:
        return True

    def is_connected(self) -> Any:
        return True

    def disconnect(self) -> None:
        pass

    def get_account_info(self) -> Any:
        return {'balance': 10000.0, 'equity': 10000.0, 'currency': 'USD', 'is_demo': False}

    def get_history(self, symbol: Any, count: Any) -> Any:
        return []

    def get_current_price(self, symbol: Any) -> Any:
        return {'bid': 1.085, 'ask': 1.0852}

    def execute_order(self, symbol, order_type, lot_size, sl, tp, product=None):
        # This should NEVER be called during release validation
        return {"success": True, "ticket": "LIVE-12345", "price": 1.0851, "error": None}

    def close_order(self, ticket: Any, reason: Any='MANUAL') -> Any:
        return {'success': True, 'price': 1.0851, 'profit': 0.0, 'error': None}

    def modify_order(self, ticket: Any, sl: Any, tp: Any) -> Any:
        return True

    def get_open_orders(self) -> Any:
        return []

    def draw_dashboard(self, symbol: Any, data: Any) -> None:
        pass

    def get_symbol_volume_constraints(self, symbol: Any='EURUSD') -> Any:
        return {'min_lot': 0.01, 'max_lot': 100.0, 'step_lot': 0.01}

class MockDemoConnector(connector.TradingConnector):
    """Mock connector that simulates a demo broker connection (safe for testing)."""

    def __init__(self) -> None:
        self.is_demo = True
        self.demo_only = True

    def connect(self) -> Any:
        return True

    def is_connected(self) -> Any:
        return True

    def disconnect(self) -> None:
        pass

    def get_account_info(self) -> Any:
        return {'balance': 10000.0, 'equity': 10000.0, 'currency': 'USD', 'is_demo': True}

    def get_history(self, symbol: Any, count: Any) -> Any:
        return []

    def get_current_price(self, symbol: Any) -> Any:
        return {'bid': 1.085, 'ask': 1.0852}

    def execute_order(self, symbol, order_type, lot_size, sl, tp, product=None):
        return {"success": True, "ticket": "DEMO-12345", "price": 1.0851, "error": None}

    def close_order(self, ticket: Any, reason: Any='MANUAL') -> Any:
        return {'success': True, 'price': 1.0851, 'profit': 0.0, 'error': None}

    def modify_order(self, ticket: Any, sl: Any, tp: Any) -> Any:
        return True

    def get_open_orders(self) -> Any:
        return [{'ticket': 'DEMO-12345', 'symbol': 'EURUSD', 'direction': 'BUY', 'open_price': 1.0851, 'sl': 1.08, 'tp': 1.1, 'lot_size': 0.1}]

    def draw_dashboard(self, symbol: Any, data: Any) -> None:
        pass

    def get_symbol_volume_constraints(self, symbol: Any='EURUSD') -> Any:
        return {'min_lot': 0.01, 'max_lot': 100.0, 'step_lot': 0.01}

class TestReleaseGatesSecurity(unittest.TestCase):
    """Test suite for ReleaseGateRunner security controls."""

    def setUp(self) -> None:
        """Initialize database before each test."""
        database.init_db()

    def test_live_connector_blocked_in_constructor(self) -> None:
        """Test that ReleaseGateRunner blocks live connectors in constructor."""
        live_conn = MockLiveConnector()
        with self.assertRaises(PermissionError) as context:
            runner = release_gates.ReleaseGateRunner(conn=live_conn)
        self.assertIn('CRITICAL SAFETY BLOCK', str(context.exception))
        self.assertIn('SimulatorConnector', str(context.exception))

    def test_simulator_connector_allowed(self) -> None:
        """Test that SimulatorConnector is allowed."""
        sim_conn = connector.SimulatorConnector(initial_balance=10000.0)
        runner = release_gates.ReleaseGateRunner(conn=sim_conn)
        self.assertIsNotNone(runner)
        self.assertEqual(runner.conn, sim_conn)

    def test_demo_connector_allowed(self) -> None:
        """Test that demo-only connectors are allowed."""
        demo_conn = MockDemoConnector()
        runner = release_gates.ReleaseGateRunner(conn=demo_conn)
        self.assertIsNotNone(runner)
        self.assertEqual(runner.conn, demo_conn)

    def test_default_connector_is_simulator(self) -> None:
        """Test that default connector is SimulatorConnector."""
        runner = release_gates.ReleaseGateRunner()
        self.assertIsInstance(runner.conn, connector.SimulatorConnector)

    def test_is_safe_connector_validates_simulator(self) -> None:
        """Test _is_safe_connector correctly identifies SimulatorConnector."""
        runner = release_gates.ReleaseGateRunner()
        sim_conn = connector.SimulatorConnector(initial_balance=10000.0)
        self.assertTrue(runner._is_safe_connector(sim_conn))

    def test_is_safe_connector_rejects_live(self) -> None:
        """Test _is_safe_connector correctly rejects live connectors."""
        runner = release_gates.ReleaseGateRunner()
        live_conn = MockLiveConnector()
        self.assertFalse(runner._is_safe_connector(live_conn))

    def test_is_safe_connector_accepts_demo(self) -> None:
        """Test _is_safe_connector correctly accepts demo connectors."""
        runner = release_gates.ReleaseGateRunner()
        demo_conn = MockDemoConnector()
        self.assertTrue(runner._is_safe_connector(demo_conn))

    @patch('config.SIMULATION_MODE', False)
    @patch('config.DEMO_ACCOUNT_ONLY', False)
    def test_g11_blocks_non_demo_mode(self) -> None:
        """Test that G11 blocks execution when DEMO_ACCOUNT_ONLY is False."""
        runner = release_gates.ReleaseGateRunner()
        passed, reason = runner._check_g11_independent_execution_verification()
        self.assertFalse(passed)
        self.assertIn('SECURITY VIOLATION', reason)
        self.assertIn('DEMO_ACCOUNT_ONLY', reason)

    @patch('config.SIMULATION_MODE', True)
    def test_g11_allows_simulation_mode(self) -> None:
        """Test that G11 allows execution in SIMULATION_MODE."""
        runner = release_gates.ReleaseGateRunner()
        passed, reason = runner._check_g11_independent_execution_verification()
        self.assertIsInstance(passed, bool)
        self.assertNotIn('SECURITY VIOLATION', reason)

    def test_g11_validates_order_parameters(self) -> None:
        """Test that G11 properly validates order parameters match."""
        runner = release_gates.ReleaseGateRunner()
        mock_conn = Mock(spec=connector.SimulatorConnector)
        mock_conn.is_demo = True
        mock_conn.execute_order.return_value = {'success': True, 'ticket': 'TEST-123', 'price': 1.0851}
        mock_conn.get_open_orders.return_value = [{'ticket': 'TEST-123', 'symbol': 'EURUSD', 'direction': 'BUY', 'open_price': 1.0851, 'sl': 1.08, 'tp': 1.1, 'lot_size': 0.1}]
        mock_conn.close_order.return_value = {'success': True, 'price': 1.0851, 'profit': 0.0}
        runner.conn = mock_conn
        with patch('config.SIMULATION_MODE', True):
            passed, reason = runner._check_g11_independent_execution_verification()
        self.assertTrue(passed)
        self.assertIn('successfully', reason.lower())
        mock_conn.execute_order.assert_called_once()
        mock_conn.close_order.assert_called_once_with('TEST-123')

    def test_g11_fails_on_execution_error(self) -> None:
        """Test that G11 fails when execution returns error."""
        runner = release_gates.ReleaseGateRunner()
        mock_conn = Mock(spec=connector.SimulatorConnector)
        mock_conn.is_demo = True
        mock_conn.execute_order.return_value = {'success': False, 'error': 'Insufficient margin'}
        runner.conn = mock_conn
        with patch('config.SIMULATION_MODE', True):
            passed, reason = runner._check_g11_independent_execution_verification()
        self.assertFalse(passed)
        self.assertIn('Execution verification failed', reason)

    def test_g11_fails_on_parameter_mismatch(self) -> None:
        """Test that G11 fails when order parameters don't match."""
        runner = release_gates.ReleaseGateRunner()
        mock_conn = Mock(spec=connector.SimulatorConnector)
        mock_conn.is_demo = True
        mock_conn.execute_order.return_value = {'success': True, 'ticket': 'TEST-123', 'price': 1.0851}
        mock_conn.get_open_orders.return_value = [{'ticket': 'TEST-123', 'symbol': 'GBPUSD', 'direction': 'BUY', 'open_price': 1.0851, 'sl': 1.08, 'tp': 1.1, 'lot_size': 0.1}]
        mock_conn.close_order.return_value = {'success': True}
        runner.conn = mock_conn
        with patch('config.SIMULATION_MODE', True):
            passed, reason = runner._check_g11_independent_execution_verification()
        self.assertFalse(passed)
        self.assertIn('Parameter mismatch', reason)
        self.assertIn('symbol', reason.lower())

    def test_g11_fails_on_cleanup_failure(self) -> None:
        """Test that G11 fails when order cleanup fails."""
        runner = release_gates.ReleaseGateRunner()
        mock_conn = Mock(spec=connector.SimulatorConnector)
        mock_conn.is_demo = True
        mock_conn.execute_order.return_value = {'success': True, 'ticket': 'TEST-123', 'price': 1.0851}
        mock_conn.get_open_orders.return_value = [{'ticket': 'TEST-123', 'symbol': 'EURUSD', 'direction': 'BUY', 'open_price': 1.0851, 'sl': 1.08, 'tp': 1.1, 'lot_size': 0.1}]
        mock_conn.close_order.return_value = {'success': False, 'error': 'Order not found'}
        runner.conn = mock_conn
        with patch('config.SIMULATION_MODE', True):
            passed, reason = runner._check_g11_independent_execution_verification()
        self.assertFalse(passed)
        self.assertIn('cleanup failed', reason.lower())
if __name__ == '__main__':
    unittest.main()
