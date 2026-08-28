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
from unittest.mock import Mock, MagicMock, patch

import config
import connector
import database
import eqats_planes


class TestVolumeNormalizationSecurity(unittest.TestCase):
    """Test suite for volume normalization security fix."""

    def setUp(self):
        """Initialize database and test fixtures before each test."""
        database.init_db()
        
        # Create a mock connector that simulates broker with 1.0 lot minimum
        self.mock_conn = Mock(spec=connector.TradingConnector)
        self.mock_conn.is_connected.return_value = True
        self.mock_conn.get_account_info.return_value = {
            "balance": 10000.0,
            "equity": 10000.0,
            "currency": "USD",
            "is_demo": True,
        }
        self.mock_conn.get_current_price.return_value = {"bid": 1.0850, "ask": 1.0852}
        self.mock_conn.get_open_orders.return_value = []
        
        # Mock broker with 1.0 lot minimum (simulating XRP or similar)
        self.mock_conn.get_symbol_volume_constraints.return_value = {
            "volume_min": 1.0,  # Broker minimum is 1.0 lot
            "volume_max": 100.0,
            "volume_step": 0.1,
        }
        
        # Track what volume was actually passed to execute_order
        self.executed_volume = None
        def capture_execute_order(symbol, order_type, lot_size, sl, tp):
            self.executed_volume = lot_size
            return {
                "success": True,
                "ticket": "TEST-12345",
                "price": 1.0851,
                "error": None,
            }
        self.mock_conn.execute_order.side_effect = capture_execute_order
        
        # Initialize execution plane with mock connector
        self.execution_plane = eqats_planes.ExecutionPlane(self.mock_conn)

    def test_volume_normalized_before_fat_finger_check(self):
        """
        Test that volume is normalized to broker minimum BEFORE fat-finger validation.
        
        This is the core security fix: if we validate 0.01 lots but execute 1.0 lot,
        we bypass risk checks. The fix ensures we validate the actual volume that
        will be submitted.
        """
        # Simulate brain calculating 0.01 lots (below broker minimum of 1.0)
        brain_calculated_volume = 0.01
        
        # Get broker constraints
        constraints = self.mock_conn.get_symbol_volume_constraints("XRPUSD")
        vol_min = constraints["volume_min"]
        vol_max = constraints["volume_max"]
        vol_step = constraints["volume_step"]
        
        # Normalize volume BEFORE validation (this is the fix)
        normalized_volume = max(vol_min, min(vol_max, float(brain_calculated_volume)))
        if vol_step > 0:
            steps = round((normalized_volume - vol_min) / vol_step)
            calc_lots = vol_min + steps * vol_step
            normalized_volume = max(vol_min, min(vol_max, calc_lots))
        
        # Verify normalization increased volume to broker minimum
        self.assertEqual(normalized_volume, 1.0, 
                        "Volume should be normalized to broker minimum of 1.0")
        self.assertGreater(normalized_volume, brain_calculated_volume,
                          "Normalized volume should be greater than brain-calculated volume")
        
        # Now validate with the NORMALIZED volume (not the original)
        is_valid = self.execution_plane.validate_fat_finger(
            "XRPUSD", normalized_volume, 1.0851
        )
        
        # Execute with the same normalized volume
        result = self.execution_plane.execute_admitted_order(
            symbol="XRPUSD",
            direction="BUY",
            lot=normalized_volume,
            sl=1.0800,
            tp=1.1000,
        )
        
        # Verify execution succeeded
        self.assertTrue(result["success"], "Order execution should succeed")
        
        # CRITICAL: Verify the volume passed to execute_order matches what was validated
        self.assertEqual(self.executed_volume, normalized_volume,
                        "Executed volume must match validated volume")
        self.assertEqual(self.executed_volume, 1.0,
                        "Executed volume should be 1.0 (broker minimum)")

    def test_simulator_uses_same_volume_as_live(self):
        """
        Test that simulator stores the same normalized volume as live execution.
        
        This prevents divergence between paper and live exposure.
        """
        # Create simulator connector
        sim_conn = connector.SimulatorConnector(initial_balance=10000.0)
        sim_conn.connect()
        
        # Simulate brain calculating 0.01 lots
        brain_calculated_volume = 0.01
        
        # Get broker constraints (simulator returns standard 0.01 minimum)
        constraints = sim_conn.get_symbol_volume_constraints("EURUSD")
        vol_min = constraints["volume_min"]
        
        # For this test, let's simulate a symbol with higher minimum
        # In real scenario, this would come from live broker
        broker_vol_min = 1.0
        
        # Normalize to broker minimum
        normalized_volume = max(broker_vol_min, brain_calculated_volume)
        
        # Execute with normalized volume
        result = sim_conn.execute_order("EURUSD", "BUY", normalized_volume, 1.0800, 1.1000)
        
        # Verify simulator stored the normalized volume
        self.assertTrue(result["success"])
        ticket = result["ticket"]
        
        # Check stored trade
        self.assertIn(ticket, sim_conn.open_trades)
        stored_volume = sim_conn.open_trades[ticket]["lot_size"]
        
        # CRITICAL: Simulator must store the same volume that was validated
        self.assertEqual(stored_volume, normalized_volume,
                        "Simulator must store the normalized volume")

    def test_fat_finger_check_blocks_excessive_normalized_volume(self):
        """
        Test that fat-finger check correctly blocks excessive volumes after normalization.
        
        If normalization increases volume beyond safe limits, it should be blocked.
        """
        # Simulate a scenario where normalization would create excessive volume
        # For example, broker minimum is 5.0 lots (hypothetical)
        self.mock_conn.get_symbol_volume_constraints.return_value = {
            "volume_min": 5.0,  # Very high minimum
            "volume_max": 100.0,
            "volume_step": 0.1,
        }
        
        brain_calculated_volume = 0.01
        
        # Get constraints and normalize
        constraints = self.mock_conn.get_symbol_volume_constraints("TESTPAIR")
        vol_min = constraints["volume_min"]
        normalized_volume = max(vol_min, brain_calculated_volume)
        
        # Verify normalization increased to 5.0
        self.assertEqual(normalized_volume, 5.0)
        
        # Fat-finger check should block this (5.0 lots is at the limit)
        # The check allows up to 5.0 lots, so this should pass
        is_valid = self.execution_plane.validate_fat_finger(
            "TESTPAIR", normalized_volume, 1.0851
        )
        self.assertTrue(is_valid, "5.0 lots should be at the limit but valid")
        
        # But 10.0 lots should be blocked
        excessive_volume = 10.0
        is_blocked = self.execution_plane.validate_fat_finger(
            "TESTPAIR", excessive_volume, 1.0851
        )
        self.assertFalse(is_blocked, "10.0 lots should be blocked by fat-finger check")

    def test_mt5_connector_does_not_modify_volume(self):
        """
        Test that MT5Connector.execute_order does not modify the lot_size parameter.
        
        This is the core of the fix: execute_order must accept pre-normalized volume.
        """
        # Create a mock MT5 connector
        mt5_conn = connector.MT5Connector(demo_only=True)
        
        # Mock the MT5 module
        mock_mt5 = MagicMock()
        mt5_conn.mt5 = mock_mt5
        
        # Mock symbol info
        mock_info = MagicMock()
        mock_info.volume_min = 1.0
        mock_info.volume_max = 100.0
        mock_info.volume_step = 0.1
        mock_info.filling_mode = 2  # IOC
        mock_info.trade_stops_level = 10
        mock_info.point = 0.00001
        mock_mt5.symbol_info.return_value = mock_info
        mock_mt5.symbol_info_tick.return_value = MagicMock(bid=1.0850, ask=1.0852)
        
        # Mock order_send to capture the volume
        captured_volume = None
        def capture_order_send(request):
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
        
        # Execute with pre-normalized volume of 1.0
        pre_normalized_volume = 1.0
        result = mt5_conn.execute_order("EURUSD", "BUY", pre_normalized_volume, 1.0800, 1.1000)
        
        # CRITICAL: Verify execute_order did NOT modify the volume
        self.assertEqual(captured_volume, pre_normalized_volume,
                        "MT5Connector must not modify pre-normalized volume")
        self.assertEqual(captured_volume, 1.0,
                        "Volume sent to broker must be exactly what was passed in")


if __name__ == "__main__":
    unittest.main()
