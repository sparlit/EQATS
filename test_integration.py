#!/usr/bin/env python3
"""
Integration Tests
Tests how different modules work together.
"""

import sys
import os
import tempfile
import shutil
from datetime import datetime as dt, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_order_lifecycle_with_risk_controls():
    """Test order lifecycle integrated with risk controls."""
    print("\n=== Testing Order Lifecycle with Risk Controls ===")
    
    try:
        from order_lifecycle import Order, OrderState, get_order_registry
        from risk_controls import RiskControls, get_risk_controls
        
        # Test 1: Order validation before submission
        print("\n1. Testing order validation before submission...")
        rc = get_risk_controls()
        rc.reset_daily(start_balance=10000.0)
        
        # Validate order
        validation = rc.validate_order("EURUSD", "BUY", 0.1, price=1.0950, market_price=1.0955)
        
        if validation['valid']:
            print("   [PASS] Order validation passed")
        else:
            print("   [FAIL] Order validation failed")
            return False
        
        # Test 2: Create and submit order
        print("\n2. Testing order creation and submission...")
        order = Order(symbol="EURUSD", order_type="BUY", lot_size=0.1, sl=1.0900, tp=1.1100)
        
        if order.submit(price=1.0950):
            print("   [PASS] Order submitted successfully")
        else:
            print("   [FAIL] Order submission failed")
            return False
        
        # Test 3: Risk limit prevents excessive order
        print("\n3. Testing risk limit enforcement...")
        # Add existing position to exceed limit
        rc.update_position("EURUSD", 45.0, "BUY")
        
        # Try to validate large order
        validation = rc.validate_order("EURUSD", "BUY", 10.0)
        
        if not validation['valid']:
            print("   [PASS] Risk limit enforced")
        else:
            print("   [FAIL] Risk limit not enforced")
            return False
        
        # Test 4: Fat-finger detection on order
        print("\n4. Testing fat-finger detection on order...")
        fat_finger = rc.check_fat_finger("EURUSD", 100.0, price=1.0950, market_price=1.0955)
        
        if fat_finger['suspicious']:
            print("   [PASS] Fat-finger detected")
        else:
            print("   [FAIL] Fat-finger not detected")
            return False
        
        print("\n[PASS] Order lifecycle with risk controls integration works correctly")
        return True
        
    except Exception as e:
        print(f"   [ERROR] Integration test failed: {e}")
        return False


def test_position_tracking_with_reconciliation():
    """Test position tracking integrated with reconciliation."""
    print("\n=== Testing Position Tracking with Reconciliation ===")
    
    try:
        from position_manager import Position, get_position_manager
        from data_reconciliation import DataReconciler, get_data_reconciler
        
        # Test 1: Create positions and track
        print("\n1. Testing position creation and tracking...")
        pm = get_position_manager()
        
        pos1 = Position(symbol="EURUSD", direction="BUY", lot_size=0.5, open_price=1.0950, ticket="POS001")
        pos2 = Position(symbol="GBPUSD", direction="SELL", lot_size=0.3, open_price=1.3000, ticket="POS002")
        
        pm.add_position(pos1)
        pm.add_position(pos2)
        
        if len(pm.get_open_positions()) == 2:
            print("   [PASS] Positions tracked correctly")
        else:
            print("   [FAIL] Position tracking failed")
            return False
        
        # Test 2: Reconcile local positions with "broker" positions
        print("\n2. Testing position reconciliation...")
        reconciler = get_data_reconciler()
        
        local_positions = [
            {'symbol': 'EURUSD', 'lot_size': 0.5},
            {'symbol': 'GBPUSD', 'lot_size': 0.3}
        ]
        
        broker_positions = [
            {'symbol': 'EURUSD', 'lot_size': 0.5},
            {'symbol': 'GBPUSD', 'lot_size': 0.3}
        ]
        
        result = reconciler.reconcile_positions(local_positions, broker_positions)
        
        if result.success:
            print("   [PASS] Position reconciliation passed")
        else:
            print("   [FAIL] Position reconciliation failed")
            return False
        
        # Test 3: Detect position discrepancy
        print("\n3. Testing position discrepancy detection...")
        broker_positions_mismatch = [
            {'symbol': 'EURUSD', 'lot_size': 5.0},  # Much larger lot size
            {'symbol': 'GBPUSD', 'lot_size': 0.3}
        ]
        
        result = reconciler.reconcile_positions(local_positions, broker_positions_mismatch)
        
        if not result.success and len(result.discrepancies) > 0:
            print("   [PASS] Position discrepancy detected")
        else:
            print("   [FAIL] Position discrepancy not detected")
            return False
        
        # Test 4: Update position prices
        print("\n4. Testing position price updates...")
        prices = {"EURUSD": 1.0960, "GBPUSD": 1.2990}
        pm.update_position_prices(prices)
        
        updated_pos = pm.get_position("POS001")
        if updated_pos.current_price == 1.0960:
            print("   [PASS] Position prices updated correctly")
        else:
            print("   [FAIL] Position prices not updated")
            return False
        
        print("\n[PASS] Position tracking with reconciliation integration works correctly")
        return True
        
    except Exception as e:
        print(f"   [ERROR] Integration test failed: {e}")
        return False


def test_data_validation_with_freshness():
    """Test data validation integrated with freshness monitoring."""
    print("\n=== Testing Data Validation with Freshness Monitoring ===")
    
    try:
        from data_validator import DataValidator, get_data_validator
        from data_freshness import DataFreshnessMonitor, get_freshness_monitor
        
        # Test 1: Validate fresh data
        print("\n1. Testing fresh data validation...")
        validator = get_data_validator()
        monitor = get_freshness_monitor()
        
        # Update timestamp
        monitor.update_data_timestamp("EURUSD")
        
        # Validate price data
        valid_data = [
            {'open': 1.0940, 'high': 1.0960, 'low': 1.0930, 'close': 1.0950},
            {'open': 1.0950, 'high': 1.0970, 'low': 1.0940, 'close': 1.0960},
            {'open': 1.0960, 'high': 1.0980, 'low': 1.0950, 'close': 1.0970},
            {'open': 1.0970, 'high': 1.0990, 'low': 1.0960, 'close': 1.0980},
            {'open': 1.0980, 'high': 1.1000, 'low': 1.0970, 'close': 1.0990},
            {'open': 1.0990, 'high': 1.1010, 'low': 1.0980, 'close': 1.1000},
            {'open': 1.1000, 'high': 1.1020, 'low': 1.0990, 'close': 1.1010},
            {'open': 1.1010, 'high': 1.1030, 'low': 1.1000, 'close': 1.1020},
            {'open': 1.1020, 'high': 1.1040, 'low': 1.1010, 'close': 1.1030},
            {'open': 1.1030, 'high': 1.1050, 'low': 1.1020, 'close': 1.1040}
        ]
        
        validation = validator.validate_data_consistency(valid_data)
        
        if validation['valid'] and validation['score'] == 100.0:
            print("   [PASS] Fresh data validated correctly")
        else:
            print("   [FAIL] Fresh data validation failed")
            return False
        
        # Test 2: Reject stale data
        print("\n2. Testing stale data rejection...")
        
        # Set old timestamp
        old_time = (dt.now() - timedelta(seconds=120)).isoformat()
        monitor.update_data_timestamp("GBPUSD", timestamp=old_time)
        
        freshness = monitor.check_freshness("GBPUSD")
        
        if freshness['stale']:
            print("   [PASS] Stale data detected")
        else:
            print("   [FAIL] Stale data not detected")
            return False
        
        # Test 3: Block trading on stale data
        print("\n3. Testing trading block on stale data...")
        should_block = monitor.should_block_trading("GBPUSD")
        
        if should_block:
            print("   [PASS] Trading blocked on stale data")
        else:
            print("   [FAIL] Trading not blocked on stale data")
            return False
        
        # Test 4: Data quality tracking
        print("\n4. Testing data quality tracking...")
        from data_freshness import DataQualityTracker, get_quality_tracker
        
        quality_tracker = get_quality_tracker()
        quality_tracker.update_quality_score("EURUSD", 85.0)
        
        quality_summary = quality_tracker.get_quality_summary("EURUSD")
        
        if quality_summary['quality_score'] == 85.0:
            print("   [PASS] Data quality tracked correctly")
        else:
            print("   [FAIL] Data quality not tracked")
            return False
        
        print("\n[PASS] Data validation with freshness monitoring integration works correctly")
        return True
        
    except Exception as e:
        print(f"   [ERROR] Integration test failed: {e}")
        return False


def test_kill_switch_with_order_blocking():
    """Test kill switch integrated with order blocking."""
    print("\n=== Testing Kill Switch with Order Blocking ===")
    
    try:
        from kill_switch import KillSwitch, KillSwitchReason, get_kill_switch
        from order_lifecycle import Order
        
        # Test 1: Activate kill switch
        print("\n1. Testing kill switch activation...")
        ks = get_kill_switch()
        
        # Ensure it's deactivated first
        if ks.is_activated():
            ks.deactivate(triggered_by="test")
        
        ks.activate(reason=KillSwitchReason.MANUAL, triggered_by="test_user")
        
        if ks.is_activated():
            print("   [PASS] Kill switch activated")
        else:
            print("   [FAIL] Kill switch not activated")
            return False
        
        # Test 2: Block new order
        print("\n2. Testing new order blocking...")
        if not ks.is_order_allowed("BUY", False):
            print("   [PASS] New order blocked")
        else:
            print("   [FAIL] New order not blocked")
            return False
        
        # Test 3: Allow position closing
        print("\n3. Testing position closing allowed...")
        if ks.is_order_allowed("SELL", True):
            print("   [PASS] Position closing allowed")
        else:
            print("   [FAIL] Position closing not allowed")
            return False
        
        # Test 4: Deactivate kill switch
        print("\n4. Testing kill switch deactivation...")
        ks.deactivate(triggered_by="test_user")
        
        if not ks.is_activated():
            print("   [PASS] Kill switch deactivated")
        else:
            print("   [FAIL] Kill switch not deactivated")
            return False
        
        # Test 5: Allow orders after deactivation
        print("\n5. Testing order allowed after deactivation...")
        if ks.is_order_allowed("BUY", False):
            print("   [PASS] Orders allowed after deactivation")
        else:
            print("   [FAIL] Orders not allowed after deactivation")
            return False
        
        print("\n[PASS] Kill switch with order blocking integration works correctly")
        return True
        
    except Exception as e:
        print(f"   [ERROR] Integration test failed: {e}")
        return False


def test_backup_restore_with_positions():
    """Test backup/restore integrated with position data."""
    print("\n=== Testing Backup/Restore with Position Data ===")
    
    try:
        from position_manager import Position, get_position_manager
        from backup_manager import BackupManager, get_backup_manager
        
        # Create temporary directory for testing
        test_dir = tempfile.mkdtemp(prefix="forexscalpper_backup_test_")
        original_dir = os.getcwd()
        
        try:
            os.chdir(test_dir)
            
            # Test 1: Create position data
            print("\n1. Creating test position data...")
            pm = get_position_manager()
            
            pos1 = Position(symbol="EURUSD", direction="BUY", lot_size=0.5, open_price=1.0950, ticket="POS001")
            pos2 = Position(symbol="GBPUSD", direction="SELL", lot_size=0.3, open_price=1.3000, ticket="POS002")
            
            pm.add_position(pos1)
            pm.add_position(pos2)
            
            # Save positions to file
            pm.save_to_file("positions.json")
            
            if os.path.exists("positions.json"):
                print("   [PASS] Position data saved")
            else:
                print("   [FAIL] Position data not saved")
                return False
            
            # Test 2: Create backup
            print("\n2. Creating backup...")
            bm = BackupManager(backup_dir="backups")
            backup_result = bm.create_backup()
            
            if backup_result['success']:
                print("   [PASS] Backup created successfully")
            else:
                print("   [FAIL] Backup creation failed")
                return False
            
            backup_id = backup_result['backup_id']
            
            # Test 3: Modify original data
            print("\n3. Modifying original data...")
            pm2 = get_position_manager()
            pm2.add_position(Position(symbol="USDJPY", direction="BUY", lot_size=0.2, open_price=145.0, ticket="POS003"))
            pm2.save_to_file("positions.json")
            
            if len(pm2.get_all_positions()) == 3:
                print("   [PASS] Data modified")
            else:
                print("   [FAIL] Data modification failed")
                return False
            
            # Test 4: Restore backup
            print("\n4. Restoring backup...")
            restore_result = bm.restore_backup(backup_id, restore_to_original=True)
            
            if restore_result['success']:
                print("   [PASS] Backup restored successfully")
            else:
                print("   [FAIL] Backup restore failed")
                return False
            
            # Test 5: Verify restored data
            print("\n5. Verifying restored data...")
            pm3 = get_position_manager()
            pm3.load_from_file("positions.json")
            
            if len(pm3.get_all_positions()) == 2:  # Should be back to 2 positions
                print("   [PASS] Data restored correctly")
            else:
                print("   [FAIL] Data not restored correctly")
                return False
            
            print("\n[PASS] Backup/restore with position data integration works correctly")
            return True
            
        finally:
            os.chdir(original_dir)
            shutil.rmtree(test_dir, ignore_errors=True)
        
    except Exception as e:
        print(f"   [ERROR] Integration test failed: {e}")
        return False


def run_all_integration_tests():
    """Run all integration tests."""
    print("="*60)
    print("RUNNING INTEGRATION TESTS")
    print("="*60)
    
    results = []
    
    results.append(("Order Lifecycle with Risk Controls", test_order_lifecycle_with_risk_controls()))
    results.append(("Position Tracking with Reconciliation", test_position_tracking_with_reconciliation()))
    results.append(("Data Validation with Freshness", test_data_validation_with_freshness()))
    results.append(("Kill Switch with Order Blocking", test_kill_switch_with_order_blocking()))
    results.append(("Backup/Restore with Positions", test_backup_restore_with_positions()))
    
    print("\n" + "="*60)
    print("INTEGRATION TESTS SUMMARY")
    print("="*60)
    
    for name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"{status} {name}")
    
    all_passed = all(result[1] for result in results)
    
    print("="*60)
    if all_passed:
        print("[PASS] All integration tests passed!")
        return 0
    else:
        print("[FAIL] Some integration tests failed")
        return 1


if __name__ == '__main__':
    sys.exit(run_all_integration_tests())
