#!/usr/bin/env python3
"""
Test Risk Controls Implementation
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from risk_controls import RiskControls, RiskLimitExceeded

def test_risk_controls():
    """Test risk controls functionality."""
    print("Testing risk controls implementation...")
    
    rc = RiskControls()
    
    # Test 1: Valid lot size
    print("\n1. Testing valid lot size...")
    result = rc.check_lot_size("EURUSD", 0.1)
    print(f"   Valid: {result['valid']}")
    print(f"   Error: {result['error']}")
    if result['valid']:
        print("   [PASS] Valid lot size accepted")
    else:
        print("   [FAIL] Valid lot size rejected")
        assert False, "Test condition failed"
    
    # Test 2: Excessive lot size
    print("\n2. Testing excessive lot size...")
    result = rc.check_lot_size("EURUSD", 20.0)
    print(f"   Valid: {result['valid']}")
    print(f"   Error: {result['error']}")
    if not result['valid'] and "exceeds maximum" in result['error']:
        print("   [PASS] Excessive lot size rejected")
    else:
        print("   [FAIL] Excessive lot size not rejected")
        assert False, "Test condition failed"
    
    # Test 3: Minimum lot size
    print("\n3. Testing minimum lot size...")
    result = rc.check_lot_size("EURUSD", 0.001)
    print(f"   Valid: {result['valid']}")
    print(f"   Error: {result['error']}")
    if not result['valid'] and "below minimum" in result['error']:
        print("   [PASS] Minimum lot size rejected")
    else:
        print("   [FAIL] Minimum lot size not rejected")
        assert False, "Test condition failed"
    
    # Test 4: Symbol-specific limit
    print("\n4. Testing symbol-specific limit...")
    rc.set_symbol_limit("BTCUSD", max_lot=0.5, max_position=5.0)
    result = rc.check_lot_size("BTCUSD", 1.0)
    print(f"   Valid: {result['valid']}")
    print(f"   Error: {result['error']}")
    if not result['valid'] and "symbol limit" in result['error']:
        print("   [PASS] Symbol-specific limit enforced")
    else:
        print("   [FAIL] Symbol-specific limit not enforced")
        assert False, "Test condition failed"
    
    # Test 5: Price deviation check
    print("\n5. Testing price deviation check...")
    result = rc.check_price_deviation("EURUSD", 1.0950, 1.0955)
    print(f"   Valid: {result['valid']}")
    print(f"   Deviation: {result['deviation_pct']:.2%}")
    if result['valid']:
        print("   [PASS] Small price deviation accepted")
    else:
        print("   [FAIL] Small price deviation rejected")
        assert False, "Test condition failed"
    
    # Test 6: Excessive price deviation
    print("\n6. Testing excessive price deviation...")
    result = rc.check_price_deviation("EURUSD", 1.1600, 1.1000)
    print(f"   Valid: {result['valid']}")
    print(f"   Deviation: {result['deviation_pct']:.2%}")
    if not result['valid'] and "exceeds maximum" in result['error']:
        print("   [PASS] Excessive price deviation rejected")
    else:
        print("   [FAIL] Excessive price deviation not rejected")
        assert False, "Test condition failed"
    
    # Test 7: Position limit check
    print("\n7. Testing position limit check...")
    result = rc.check_position_limit("EURUSD", 0.1, "BUY")
    print(f"   Valid: {result['valid']}")
    print(f"   Current position: {result['current_position']}")
    print(f"   New position: {result['new_position']}")
    if result['valid']:
        print("   [PASS] Position within limits")
    else:
        print("   [FAIL] Position incorrectly rejected")
        assert False, "Test condition failed"
    
    # Test 8: Position limit exceeded
    print("\n8. Testing position limit exceeded...")
    rc.positions["EURUSD"] = 45.0  # Already have large position
    result = rc.check_position_limit("EURUSD", 10.0, "BUY")
    print(f"   Valid: {result['valid']}")
    print(f"   Error: {result['error']}")
    if not result['valid'] and "exceeds maximum" in result['error']:
        print("   [PASS] Position limit enforced")
    else:
        print("   [FAIL] Position limit not enforced")
        assert False, "Test condition failed"
    
    # Test 9: Total exposure check
    print("\n9. Testing total exposure check...")
    rc.positions = {}  # Reset positions
    result = rc.check_total_exposure("EURUSD", 0.1)
    print(f"   Valid: {result['valid']}")
    print(f"   Current exposure: {result['current_exposure']}")
    print(f"   New exposure: {result['new_exposure']}")
    if result['valid']:
        print("   [PASS] Total exposure within limits")
    else:
        print("   [FAIL] Total exposure incorrectly rejected")
        assert False, "Test condition failed"
    
    # Test 10: Total exposure exceeded
    print("\n10. Testing total exposure exceeded...")
    rc.positions = {"EURUSD": 50.0, "GBPUSD": 40.0, "USDJPY": 10.0}
    result = rc.check_total_exposure("BTCUSD", 5.0)
    print(f"   Valid: {result['valid']}")
    print(f"   Error: {result['error']}")
    if not result['valid'] and "exceeds maximum" in result['error']:
        print("   [PASS] Total exposure limit enforced")
    else:
        print("   [FAIL] Total exposure limit not enforced")
        assert False, "Test condition failed"
    
    # Test 11: Daily loss limit
    print("\n11. Testing daily loss limit...")
    rc.reset_daily(start_balance=10000.0)
    rc.update_daily_pnl(-500.0)  # 5% loss
    result = rc.check_daily_loss_limit()
    print(f"   Valid: {result['valid']}")
    print(f"   Daily P&L: {result['daily_pnl']}")
    print(f"   Daily P&L %: {result['daily_pnl_pct']:.2%}")
    if result['valid']:
        print("   [PASS] Daily loss within limits")
    else:
        print("   [FAIL] Daily loss incorrectly rejected")
        assert False, "Test condition failed"
    
    # Test 12: Daily loss exceeded
    print("\n12. Testing daily loss exceeded...")
    rc.update_daily_pnl(-1000.0)  # Additional 10% loss = 15% total
    result = rc.check_daily_loss_limit()
    print(f"   Valid: {result['valid']}")
    print(f"   Error: {result['error']}")
    if not result['valid'] and "exceeds maximum" in result['error']:
        print("   [PASS] Daily loss limit enforced")
    else:
        print("   [FAIL] Daily loss limit not enforced")
        assert False, "Test condition failed"
    
    # Test 13: Drawdown limit
    print("\n13. Testing drawdown limit...")
    rc.reset_daily(start_balance=10000.0)
    rc.update_balance(9500.0)  # 5% drawdown
    result = rc.check_drawdown_limit()
    print(f"   Valid: {result['valid']}")
    print(f"   Current drawdown: {result['current_drawdown']:.2%}")
    if result['valid']:
        print("   [PASS] Drawdown within limits")
    else:
        print("   [FAIL] Drawdown incorrectly rejected")
        assert False, "Test condition failed"
    
    # Test 14: Drawdown exceeded
    print("\n14. Testing drawdown exceeded...")
    rc.update_balance(7500.0)  # 25% drawdown
    result = rc.check_drawdown_limit()
    print(f"   Valid: {result['valid']}")
    print(f"   Error: {result['error']}")
    if not result['valid'] and "exceeds maximum" in result['error']:
        print("   [PASS] Drawdown limit enforced")
    else:
        print("   [FAIL] Drawdown limit not enforced")
        assert False, "Test condition failed"
    
    # Test 15: Comprehensive order validation
    print("\n15. Testing comprehensive order validation...")
    rc.reset_daily(start_balance=10000.0)
    rc.positions = {}
    result = rc.validate_order("EURUSD", "BUY", 0.1, price=1.0950, market_price=1.0955)
    print(f"   Valid: {result['valid']}")
    print(f"   Checks performed: {len(result['checks'])}")
    print(f"   Errors: {result['errors']}")
    if result['valid']:
        print("   [PASS] Comprehensive validation passed")
    else:
        print("   [FAIL] Comprehensive validation failed")
        assert False, "Test condition failed"
    
    # Test 16: Order validation with multiple failures
    print("\n16. Testing order validation with multiple failures...")
    rc.positions = {"EURUSD": 45.0}
    result = rc.validate_order("EURUSD", "BUY", 10.0, price=1.1500, market_price=1.1000)
    print(f"   Valid: {result['valid']}")
    print(f"   Errors: {result['errors']}")
    if not result['valid'] and len(result['errors']) > 0:
        print("   [PASS] Multiple errors detected")
    else:
        print("   [FAIL] Errors not detected")
        assert False, "Test condition failed"
    
    # Test 17: Position update
    print("\n17. Testing position update...")
    rc.positions = {}
    rc.update_position("EURUSD", 0.5, "BUY")
    print(f"   EURUSD position: {rc.positions.get('EURUSD', 0.0)}")
    if rc.positions.get("EURUSD") == 0.5:
        print("   [PASS] Position updated correctly")
    else:
        print("   [FAIL] Position not updated")
        assert False, "Test condition failed"
    
    # Test 18: Position close
    print("\n18. Testing position close...")
    rc.update_position("EURUSD", 0.5, "SELL")
    print(f"   EURUSD position: {rc.positions.get('EURUSD', 0.0)}")
    if "EURUSD" not in rc.positions:
        print("   [PASS] Position closed correctly")
    else:
        print("   [FAIL] Position not closed")
        assert False, "Test condition failed"
    
    # Test 19: Fat-finger detection - normal order
    print("\n19. Testing fat-finger detection (normal order)...")
    result = rc.check_fat_finger("EURUSD", 0.1, price=1.0950, market_price=1.0955)
    print(f"   Suspicious: {result['suspicious']}")
    print(f"   Risk level: {result['risk_level']}")
    print(f"   Warnings: {result['warnings']}")
    if not result['suspicious']:
        print("   [PASS] Normal order not flagged")
    else:
        print("   [FAIL] Normal order incorrectly flagged")
        assert False, "Test condition failed"
    
    # Test 20: Fat-finger detection - large lot size
    print("\n20. Testing fat-finger detection (large lot size)...")
    result = rc.check_fat_finger("EURUSD", 10.0, price=1.0950, market_price=1.0955)
    print(f"   Suspicious: {result['suspicious']}")
    print(f"   Risk level: {result['risk_level']}")
    print(f"   Warnings: {result['warnings']}")
    if result['suspicious'] and result['risk_level'] in ['MEDIUM', 'HIGH']:
        print("   [PASS] Large lot size flagged")
    else:
        print("   [FAIL] Large lot size not flagged")
        assert False, "Test condition failed"
    
    # Test 21: Fat-finger detection - round number
    print("\n21. Testing fat-finger detection (round number)...")
    result = rc.check_fat_finger("EURUSD", 10.0)
    print(f"   Suspicious: {result['suspicious']}")
    print(f"   Warnings: {result['warnings']}")
    if result['suspicious'] and "Round number" in str(result['warnings']):
        print("   [PASS] Round number flagged")
    else:
        print("   [FAIL] Round number not flagged")
        assert False, "Test condition failed"
    
    # Test 22: Fat-finger detection - price deviation
    print("\n22. Testing fat-finger detection (price deviation)...")
    result = rc.check_fat_finger("EURUSD", 0.1, price=1.1600, market_price=1.1000)
    print(f"   Suspicious: {result['suspicious']}")
    print(f"   Risk level: {result['risk_level']}")
    print(f"   Warnings: {result['warnings']}")
    if result['suspicious'] and "price deviation" in str(result['warnings']).lower():
        print("   [PASS] Price deviation flagged")
    else:
        print("   [FAIL] Price deviation not flagged")
        assert False, "Test condition failed"
    
    # Test 23: Fat-finger detection - repeated digits
    print("\n23. Testing fat-finger detection (repeated digits)...")
    result = rc.check_fat_finger("EURUSD", 1.11)
    print(f"   Suspicious: {result['suspicious']}")
    print(f"   Warnings: {result['warnings']}")
    if result['suspicious'] and "Repeated digit" in str(result['warnings']):
        print("   [PASS] Repeated digits flagged")
    else:
        print("   [FAIL] Repeated digits not flagged")
        assert False, "Test condition failed"
    
    print(f"\n{'='*60}")
    print("[PASS] All risk controls tests passed!")
    # Clean test exit

if __name__ == '__main__':
    sys.exit(test_risk_controls())
