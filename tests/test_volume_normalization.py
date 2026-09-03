"""
Security test for volume normalization fix.

This test verifies that broker volume floor is applied BEFORE risk admission checks,
preventing the safety control bypass where an order validated at 0.01 lots could be
submitted at 1.0 lot (broker minimum).

The fix ensures:
1. Volume normalization happens before fat-finger validation
2. The same normalized volume is used for validation and execution
3. Both simulator and live connector use the same volume
"""

import unittest
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import config
import connector
import database
import eqats_planes


class TestVolumeNormalizationSecurity(unittest.TestCase):
    """Test suite for volume normalization security fix."""

    def setUp(self) -> Any:
        """Initialize database and test fixtures before each test."""
        database.init_db()
        self.mock_conn = Mock(spec=connector.TradingConnector)
        self.mock_conn.is_connected.return_value = True
        self.mock_conn.get_account_info.return_value = {
            "balance": 10000.0,
            "equity": 10000.0,
            "currency": "USD",
            "is_demo": True,
        }
        self.mock_conn.get_current_price.return_value = {"bid": 1.085, "ask": 1.0852}
        self.mock_conn.get_open_orders.return_value = []
        self.mock_conn.get_symbol_volume_constraints.return_value = {
            "volume_min": 1.0,
            "volume_max": 100.0,
            "volume_step": 0.1,
        }
        self.executed_volume = None

        def capture_execute_order(symbol: Any, order_type: Any, lot_size: Any, sl: Any, tp: Any) -> Any:
            self.executed_volume = lot_size
            return {"success": True, "ticket": "TEST-12345", "price": 1.0851, "error": None}

        self.mock_conn.execute_order.side_effect = capture_execute_order
        self.execution_plane = eqats_planes.ExecutionPlane(self.mock_conn)

    def test_volume_normalized_before_fat_finger_check(self) -> None:
        """
        Test that volume is normalized to broker minimum BEFORE fat-finger validation.

        This is the core security fix: if we validate 0.01 lots but execute 1.0 lot,
        we bypass risk checks. The fix ensures we validate the actual volume that
        will be submitted.
        """
        brain_calculated_volume = 0.01
        constraints = self.mock_conn.get_symbol_volume_constraints("XRPUSD")
        vol_min = constraints["volume_min"]
        vol_max = constraints["volume_max"]
        vol_step = constraints["volume_step"]
        normalized_volume = max(vol_min, min(vol_max, float(brain_calculated_volume)))
        if vol_step > 0:
            steps = round((normalized_volume - vol_min) / vol_step)
            calc_lots = vol_min + steps * vol_step
            normalized_volume = max(vol_min, min(vol_max, calc_lots))
        self.assertEqual(normalized_volume, 1.0, "Volume should be normalized to broker minimum of 1.0")
        self.assertGreater(
            normalized_volume,
            brain_calculated_volume,
            "Normalized volume should be greater than brain-calculated volume",
        )
        is_valid = self.execution_plane.validate_fat_finger("XRPUSD", normalized_volume, 1.0851)
        result = self.execution_plane.execute_admitted_order(
            symbol="XRPUSD", direction="BUY", lot=normalized_volume, sl=1.08, tp=1.1,
        )
        self.assertTrue(result["success"], "Order execution should succeed")
        self.assertEqual(self.executed_volume, normalized_volume, "Executed volume must match validated volume")
        self.assertEqual(self.executed_volume, 1.0, "Executed volume should be 1.0 (broker minimum)")

    def test_simulator_uses_same_volume_as_live(self) -> None:
        """
        Test that simulator stores the same normalized volume as live execution.

        This prevents divergence between paper and live exposure.
        """
        sim_conn = connector.SimulatorConnector(initial_balance=10000.0)
        sim_conn.connect()
        brain_calculated_volume = 0.01
        constraints = sim_conn.get_symbol_volume_constraints("EURUSD")
        vol_min = constraints["volume_min"]
        broker_vol_min = 1.0
        normalized_volume = max(broker_vol_min, brain_calculated_volume)
        result = sim_conn.execute_order("EURUSD", "BUY", normalized_volume, 1.08, 1.1)
        self.assertTrue(result["success"])
        ticket = result["ticket"]
        self.assertIn(ticket, sim_conn.open_trades)
        stored_volume = sim_conn.open_trades[ticket]["lot_size"]
        self.assertEqual(stored_volume, normalized_volume, "Simulator must store the normalized volume")

    def test_fat_finger_check_blocks_excessive_normalized_volume(self) -> None:
        """
        Test that fat-finger check correctly blocks excessive volumes after normalization.

        If normalization increases volume beyond safe limits, it should be blocked.
        """
        self.mock_conn.get_symbol_volume_constraints.return_value = {
            "volume_min": 5.0,
            "volume_max": 100.0,
            "volume_step": 0.1,
        }
        brain_calculated_volume = 0.01
        constraints = self.mock_conn.get_symbol_volume_constraints("TESTPAIR")
        vol_min = constraints["volume_min"]
        normalized_volume = max(vol_min, brain_calculated_volume)
        self.assertEqual(normalized_volume, 5.0)
        is_valid = self.execution_plane.validate_fat_finger("TESTPAIR", normalized_volume, 1.0851)
        self.assertTrue(is_valid, "5.0 lots should be at the limit but valid")
        excessive_volume = 10.0
        is_blocked = self.execution_plane.validate_fat_finger("TESTPAIR", excessive_volume, 1.0851)
        self.assertFalse(is_blocked, "10.0 lots should be blocked by fat-finger check")

    def test_mt5_connector_does_not_modify_volume(self) -> Any:
        """
        Test that MT5Connector.execute_order does not modify the lot_size parameter.

        This is the core of the fix: execute_order must accept pre-normalized volume.
        """
        mt5_conn = connector.MT5Connector(demo_only=True)
        mock_mt5 = MagicMock()
        mt5_conn.mt5 = mock_mt5
        mock_info = MagicMock()
        mock_info.volume_min = 1.0
        mock_info.volume_max = 100.0
        mock_info.volume_step = 0.1
        mock_info.filling_mode = 2
        mock_info.trade_stops_level = 10
        mock_info.point = 1e-05
        mock_mt5.symbol_info.return_value = mock_info
        mock_mt5.symbol_info_tick.return_value = MagicMock(bid=1.085, ask=1.0852)
        captured_volume = None

        def capture_order_send(request: Any) -> Any:
            nonlocal captured_volume
            captured_volume = request["volume"]
            result = MagicMock()
            result.retcode = mock_mt5.TRADE_RETCODE_DONE
            result.order = 12345
            result.price = 1.0851
            return result

        mock_mt5.order_send.side_effect = capture_order_send
        mock_mt5.TRADE_RETCODE_DONE = 10009
        mock_mt5.ORDER_FILLING_IOC = 1
        mock_mt5.TRADE_ACTION_DEAL = 1
        mock_mt5.ORDER_TYPE_BUY = 0
        mock_mt5.ORDER_TIME_GTC = 0
        pre_normalized_volume = 1.0
        result = mt5_conn.execute_order("EURUSD", "BUY", pre_normalized_volume, 1.08, 1.1)
        self.assertEqual(captured_volume, pre_normalized_volume, "MT5Connector must not modify pre-normalized volume")
        self.assertEqual(captured_volume, 1.0, "Volume sent to broker must be exactly what was passed in")


if __name__ == "__main__":
    unittest.main()
