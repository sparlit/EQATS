#!/usr/bin/env python3
"""
Test Data Reconciliation Implementation
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_reconciliation import DataReconciler, ReconciliationResult

def test_data_reconciliation():
    """Test data reconciliation functionality."""
    print("Testing data reconciliation implementation...")
    
    # Test 1: Balance reconciliation - matching
    print("\n1. Testing balance reconciliation (matching)...")
    reconciler = DataReconciler()
    result = reconciler.reconcile_balance(10000.0, 10000.0, "USD")
    print(f"   Success: {result.success}")
    print(f"   Passed checks: {result.summary['passed_checks']}")
    if result.success and result.summary['passed_checks'] == 1:
        print("   [PASS] Balance reconciliation (matching) correct")
    else:
        print("   [FAIL] Balance reconciliation (matching) failed")
        assert False, "Test condition failed"
    
    # Test 2: Balance reconciliation - discrepancy
    print("\n2. Testing balance reconciliation (discrepancy)...")
    result = reconciler.reconcile_balance(10000.0, 9950.0, "USD")
    print(f"   Success: {result.success}")
    print(f"   Discrepancies: {len(result.discrepancies)}")
    if not result.success and len(result.discrepancies) > 0:
        print("   [PASS] Balance discrepancy detected")
    else:
        print("   [FAIL] Balance discrepancy not detected")
        assert False, "Test condition failed"
    
    # Test 3: Position reconciliation - matching
    print("\n3. Testing position reconciliation (matching)...")
    local_positions = [
        {'symbol': 'EURUSD', 'lot_size': 0.5}
    ]
    broker_positions = [
        {'symbol': 'EURUSD', 'lot_size': 0.5}
    ]
    result = reconciler.reconcile_positions(local_positions, broker_positions)
    print(f"   Success: {result.success}")
    print(f"   Passed checks: {result.summary['passed_checks']}")
    if result.success and result.summary['passed_checks'] == 1:
        print("   [PASS] Position reconciliation (matching) correct")
    else:
        print("   [FAIL] Position reconciliation (matching) failed")
        assert False, "Test condition failed"
    
    # Test 4: Position reconciliation - missing broker position
    print("\n4. Testing position reconciliation (missing broker position)...")
    local_positions = [
        {'symbol': 'EURUSD', 'lot_size': 0.5}
    ]
    broker_positions = []
    result = reconciler.reconcile_positions(local_positions, broker_positions)
    print(f"   Success: {result.success}")
    print(f"   Discrepancies: {len(result.discrepancies)}")
    if not result.success and len(result.discrepancies) > 0:
        print("   [PASS] Missing broker position detected")
    else:
        print("   [FAIL] Missing broker position not detected")
        assert False, "Test condition failed"
    
    # Test 5: Position reconciliation - orphan broker position
    print("\n5. Testing position reconciliation (orphan broker position)...")
    local_positions = []
    broker_positions = [
        {'symbol': 'GBPUSD', 'lot_size': 0.3}
    ]
    result = reconciler.reconcile_positions(local_positions, broker_positions)
    print(f"   Success: {result.success}")
    print(f"   Discrepancies: {len(result.discrepancies)}")
    if not result.success and len(result.discrepancies) > 0:
        print("   [PASS] Orphan broker position detected")
    else:
        print("   [FAIL] Orphan broker position not detected")
        assert False, "Test condition failed"
    
    # Test 6: Order reconciliation - matching
    print("\n6. Testing order reconciliation (matching)...")
    local_orders = [
        {'ticket': 'ORD001', 'state': 'FILLED'}
    ]
    broker_orders = [
        {'ticket': 'ORD001', 'state': 'FILLED'}
    ]
    result = reconciler.reconcile_orders(local_orders, broker_orders)
    print(f"   Success: {result.success}")
    print(f"   Passed checks: {result.summary['passed_checks']}")
    if result.success and result.summary['passed_checks'] == 1:
        print("   [PASS] Order reconciliation (matching) correct")
    else:
        print("   [FAIL] Order reconciliation (matching) failed")
        assert False, "Test condition failed"
    
    # Test 7: Order reconciliation - state mismatch
    print("\n7. Testing order reconciliation (state mismatch)...")
    local_orders = [
        {'ticket': 'ORD002', 'state': 'SUBMITTED'}
    ]
    broker_orders = [
        {'ticket': 'ORD002', 'state': 'FILLED'}
    ]
    result = reconciler.reconcile_orders(local_orders, broker_orders)
    print(f"   Success: {result.success}")
    print(f"   Discrepancies: {len(result.discrepancies)}")
    if len(result.discrepancies) > 0:
        print("   [PASS] Order state mismatch detected")
    else:
        print("   [FAIL] Order state mismatch not detected")
        assert False, "Test condition failed"
    
    # Test 8: Order reconciliation - terminal state okay
    print("\n8. Testing order reconciliation (terminal state okay)...")
    local_orders = [
        {'ticket': 'ORD003', 'state': 'FILLED'}
    ]
    broker_orders = []
    result = reconciler.reconcile_orders(local_orders, broker_orders)
    print(f"   Success: {result.success}")
    print(f"   Passed checks: {result.summary['passed_checks']}")
    if result.success and result.summary['passed_checks'] == 1:
        print("   [PASS] Terminal order handled correctly")
    else:
        print("   [FAIL] Terminal order not handled correctly")
        assert False, "Test condition failed"
    
    # Test 9: Trade reconciliation - matching
    print("\n9. Testing trade reconciliation (matching)...")
    local_trades = [
        {'trade_id': 'TRD001', 'price': 1.0950}
    ]
    broker_trades = [
        {'trade_id': 'TRD001', 'price': 1.0950}
    ]
    result = reconciler.reconcile_trades(local_trades, broker_trades)
    print(f"   Success: {result.success}")
    print(f"   Passed checks: {result.summary['passed_checks']}")
    if result.success and result.summary['passed_checks'] == 1:
        print("   [PASS] Trade reconciliation (matching) correct")
    else:
        print("   [FAIL] Trade reconciliation (matching) failed")
        assert False, "Test condition failed"
    
    # Test 10: Trade reconciliation - price mismatch
    print("\n10. Testing trade reconciliation (price mismatch)...")
    local_trades = [
        {'trade_id': 'TRD002', 'price': 1.0950}
    ]
    broker_trades = [
        {'trade_id': 'TRD002', 'price': 1.0960}
    ]
    result = reconciler.reconcile_trades(local_trades, broker_trades)
    print(f"   Success: {result.success}")
    print(f"   Discrepancies: {len(result.discrepancies)}")
    if len(result.discrepancies) > 0:
        print("   [PASS] Trade price mismatch detected")
    else:
        print("   [FAIL] Trade price mismatch not detected")
        assert False, "Test condition failed"
    
    # Test 11: Full reconciliation
    print("\n11. Testing full reconciliation...")
    local_data = {
        'balance': 10000.0,
        'currency': 'USD',
        'positions': [{'symbol': 'EURUSD', 'lot_size': 0.5}],
        'orders': [{'ticket': 'ORD001', 'state': 'FILLED'}],
        'trades': [{'trade_id': 'TRD001', 'price': 1.0950}]
    }
    broker_data = {
        'balance': 10000.0,
        'currency': 'USD',
        'positions': [{'symbol': 'EURUSD', 'lot_size': 0.5}],
        'orders': [{'ticket': 'ORD001', 'state': 'FILLED'}],
        'trades': [{'trade_id': 'TRD001', 'price': 1.0950}]
    }
    result = reconciler.full_reconciliation(local_data, broker_data)
    print(f"   Success: {result.success}")
    print(f"   Total checks: {result.summary['total_checks']}")
    print(f"   Passed checks: {result.summary['passed_checks']}")
    if result.success and result.summary['total_checks'] == result.summary['passed_checks']:
        print("   [PASS] Full reconciliation correct")
    else:
        print("   [FAIL] Full reconciliation failed")
        assert False, "Test condition failed"
    
    # Test 12: Full reconciliation with discrepancies
    print("\n12. Testing full reconciliation with discrepancies...")
    local_data = {
        'balance': 10000.0,
        'currency': 'USD',
        'positions': [{'symbol': 'EURUSD', 'lot_size': 0.5}],
        'orders': [],
        'trades': []
    }
    broker_data = {
        'balance': 9900.0,
        'currency': 'USD',
        'positions': [{'symbol': 'EURUSD', 'lot_size': 0.5}],
        'orders': [],
        'trades': []
    }
    result = reconciler.full_reconciliation(local_data, broker_data)
    print(f"   Success: {result.success}")
    print(f"   Failed checks: {result.summary['failed_checks']}")
    if not result.success and result.summary['failed_checks'] > 0:
        print("   [PASS] Discrepancies detected in full reconciliation")
    else:
        print("   [FAIL] Discrepancies not detected")
        assert False, "Test condition failed"
    
    # Test 13: Reconciliation history
    print("\n13. Testing reconciliation history...")
    history = reconciler.get_reconciliation_history()
    print(f"   History length: {len(history)}")
    if len(history) >= 2:  # Should have at least 2 from previous tests
        print("   [PASS] Reconciliation history tracked")
    else:
        print("   [FAIL] Reconciliation history not tracked")
        assert False, "Test condition failed"
    
    # Test 14: Should block trading
    print("\n14. Testing trading block decision...")
    should_block = reconciler.should_block_trading()
    print(f"   Should block: {should_block}")
    # Should block because last reconciliation had discrepancies
    if should_block:
        print("   [PASS] Trading block decision correct")
    else:
        print("   [FAIL] Trading block decision incorrect")
        assert False, "Test condition failed"
    
    # Test 15: ReconciliationResult class
    print("\n15. Testing ReconciliationResult class...")
    result = ReconciliationResult()
    result.add_total_check()
    result.add_passed_check()
    print(f"   Has discrepancies: {result.has_discrepancies()}")
    print(f"   Has critical: {result.has_critical_discrepancies()}")
    if not result.has_discrepancies() and not result.has_critical_discrepancies():
        print("   [PASS] ReconciliationResult works correctly")
    else:
        print("   [FAIL] ReconciliationResult failed")
        assert False, "Test condition failed"
    
    print(f"\n{'='*60}")
    print("[PASS] All data reconciliation tests passed!")
    # Clean test exit

if __name__ == '__main__':
    sys.exit(test_data_reconciliation())
