#!/usr/bin/env python3
"""
Test Position Tracking and Limits Implementation
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from position_manager import Position, PositionManager

def test_position_manager():
    """Test position tracking and limits functionality."""
    print("Testing position tracking and limits implementation...")
    
    # Test 1: Create position
    print("\n1. Testing position creation...")
    position = Position(symbol="EURUSD", direction="BUY", lot_size=0.1, open_price=1.0950, ticket="TEST001")
    print(f"   Symbol: {position.symbol}")
    print(f"   Direction: {position.direction}")
    print(f"   Lot size: {position.lot_size}")
    print(f"   Open price: {position.open_price}")
    if position.symbol == "EURUSD" and position.direction == "BUY":
        print("   [PASS] Position created correctly")
    else:
        print("   [FAIL] Position not created correctly")
        return 1
    
    # Test 2: Position profit calculation
    print("\n2. Testing position profit calculation...")
    position.update_price(1.0960)  # Price moved up
    print(f"   Current price: {position.current_price}")
    print(f"   Profit: {position.profit}")
    if position.profit > 0:  # Should be profitable for long position
        print("   [PASS] Profit calculated correctly")
    else:
        print("   [FAIL] Profit not calculated correctly")
        return 1
    
    # Test 3: Position close
    print("\n3. Testing position close...")
    position.close(close_price=1.0970, reason="TAKE_PROFIT")
    print(f"   Is closed: {position.is_closed}")
    print(f"   Close price: {position.close_price}")
    print(f"   Close reason: {position.close_reason}")
    if position.is_closed and position.close_reason == "TAKE_PROFIT":
        print("   [PASS] Position closed correctly")
    else:
        print("   [FAIL] Position not closed correctly")
        return 1
    
    # Test 4: Position serialization
    print("\n4. Testing position serialization...")
    position_dict = position.to_dict()
    print(f"   Serialized keys: {list(position_dict.keys())}")
    
    restored_position = Position.from_dict(position_dict)
    print(f"   Restored symbol: {restored_position.symbol}")
    print(f"   Restored direction: {restored_position.direction}")
    if restored_position.symbol == position.symbol and restored_position.direction == position.direction:
        print("   [PASS] Position serialization works correctly")
    else:
        print("   [FAIL] Position serialization failed")
        return 1
    
    # Test 5: Position manager
    print("\n5. Testing position manager...")
    pm = PositionManager()
    
    pos1 = Position(symbol="EURUSD", direction="BUY", lot_size=0.1, open_price=1.0950, ticket="POS001")
    pos2 = Position(symbol="GBPUSD", direction="SELL", lot_size=0.2, open_price=1.3000, ticket="POS002")
    
    pm.add_position(pos1)
    pm.add_position(pos2)
    
    print(f"   Total positions: {len(pm.get_all_positions())}")
    print(f"   Open positions: {len(pm.get_open_positions())}")
    if len(pm.get_all_positions()) == 2 and len(pm.get_open_positions()) == 2:
        print("   [PASS] Position manager works correctly")
    else:
        print("   [FAIL] Position manager failed")
        return 1
    
    # Test 6: Position limits
    print("\n6. Testing position limits...")
    pm.set_position_limit("BTCUSD", max_lot=5.0)
    limit = pm.get_position_limit("BTCUSD")
    print(f"   BTCUSD limit: {limit}")
    if limit == 5.0:
        print("   [PASS] Position limit set correctly")
    else:
        print("   [FAIL] Position limit not set correctly")
        return 1
    
    # Test 7: Position limit check
    print("\n7. Testing position limit check...")
    result = pm.check_position_limit("EURUSD", 0.1, "BUY")
    print(f"   Valid: {result['valid']}")
    print(f"   Current exposure: {result['current_exposure']}")
    print(f"   New exposure: {result['new_exposure']}")
    if result['valid']:
        print("   [PASS] Position within limits")
    else:
        print("   [FAIL] Position incorrectly rejected")
        return 1
    
    # Test 8: Position limit exceeded
    print("\n8. Testing position limit exceeded...")
    # Create fresh manager
    pm3 = PositionManager()
    # Add large existing position
    pos3 = Position(symbol="EURUSD", direction="BUY", lot_size=45.0, open_price=1.0950, ticket="POS003")
    pm3.add_position(pos3)
    
    result = pm3.check_position_limit("EURUSD", 10.0, "BUY")
    print(f"   Valid: {result['valid']}")
    print(f"   Error: {result['error']}")
    if not result['valid'] and "exceeds limit" in result['error']:
        print("   [PASS] Position limit enforced")
    else:
        print("   [FAIL] Position limit not enforced")
        return 1
    
    # Test 9: Symbol exposure calculation
    print("\n9. Testing symbol exposure calculation...")
    pm4 = PositionManager()  # Fresh instance
    pm4.add_position(Position(symbol="EURUSD", direction="BUY", lot_size=0.5, open_price=1.0950, ticket="P1"))
    pm4.add_position(Position(symbol="EURUSD", direction="SELL", lot_size=0.3, open_price=1.0950, ticket="P2"))
    
    exposure = pm4.calculate_symbol_exposure("EURUSD")
    print(f"   EURUSD exposure: {exposure}")
    if exposure == 0.2:  # 0.5 - 0.3 = 0.2
        print("   [PASS] Exposure calculated correctly")
    else:
        print("   [FAIL] Exposure not calculated correctly")
        return 1
    
    # Test 10: Total exposure calculation
    print("\n10. Testing total exposure calculation...")
    # Add GBPUSD position to pm4
    pm4.add_position(Position(symbol="GBPUSD", direction="BUY", lot_size=0.5, open_price=1.3000, ticket="P3"))
    
    total_exposure = pm4.calculate_total_exposure()
    print(f"   Total exposure: {total_exposure}")
    if total_exposure == 1.3:  # 0.5 + 0.3 + 0.5 (absolute values)
        print("   [PASS] Total exposure calculated correctly")
    else:
        print("   [FAIL] Total exposure not calculated correctly")
        return 1
    
    # Test 11: Total P&L calculation
    print("\n11. Testing total P&L calculation...")
    pm5 = PositionManager()
    pos_profit = Position(symbol="EURUSD", direction="BUY", lot_size=0.1, open_price=1.0950, ticket="TP1")
    pos_profit.update_price(1.0960)  # Profit
    
    pos_loss = Position(symbol="GBPUSD", direction="SELL", lot_size=0.1, open_price=1.3000, ticket="TP2")
    pos_loss.update_price(1.2950)  # Loss for short
    
    pm5.add_position(pos_profit)
    pm5.add_position(pos_loss)
    
    total_pnl = pm5.calculate_total_pnl()
    print(f"   Total P&L: {total_pnl}")
    # Should be profit from EURUSD + loss from GBPUSD
    if total_pnl > 0:  # EURUSD profit should outweigh GBPUSD loss at this small move
        print("   [PASS] Total P&L calculated correctly")
    else:
        print("   [FAIL] Total P&L not calculated correctly")
        return 1
    
    # Test 12: Position summary
    print("\n12. Testing position summary...")
    summary = pm5.get_position_summary()
    print(f"   Total open positions: {summary['total_open_positions']}")
    print(f"   Total exposure: {summary['total_exposure']}")
    print(f"   Total P&L: {summary['total_pnl']}")
    print(f"   Symbols: {list(summary['symbols'].keys())}")
    if summary['total_open_positions'] == 2:
        print("   [PASS] Position summary correct")
    else:
        print("   [FAIL] Position summary incorrect")
        return 1
    
    # Test 13: Get positions by symbol
    print("\n13. Testing get positions by symbol...")
    eurusd_positions = pm5.get_positions_by_symbol("EURUSD")
    print(f"   EURUSD positions: {len(eurusd_positions)}")
    if len(eurusd_positions) == 1:
        print("   [PASS] Symbol filtering works correctly")
    else:
        print("   [FAIL] Symbol filtering failed")
        return 1
    
    # Test 14: Update position prices
    print("\n14. Testing update position prices...")
    prices = {"EURUSD": 1.0970, "GBPUSD": 1.2980}
    pm5.update_position_prices(prices)
    
    updated_eur = pm5.get_position("TP1")
    print(f"   EURUSD updated price: {updated_eur.current_price}")
    if updated_eur.current_price == 1.0970:
        print("   [PASS] Position prices updated correctly")
    else:
        print("   [FAIL] Position prices not updated")
        return 1
    
    # Test 15: Position persistence
    print("\n15. Testing position persistence...")
    pm6 = PositionManager()
    pm6.add_position(Position(symbol="EURUSD", direction="BUY", lot_size=0.1, open_price=1.0950, ticket="SAVE001"))
    
    saved = pm6.save_to_file("test_positions.json")
    print(f"   Saved: {saved}")
    
    pm7 = PositionManager()
    loaded = pm7.load_from_file("test_positions.json")
    print(f"   Loaded: {loaded}")
    
    if saved and loaded:
        print("   [PASS] Position persistence works correctly")
    else:
        print("   [FAIL] Position persistence failed")
        return 1
    
    # Cleanup
    if os.path.exists("test_positions.json"):
        os.remove("test_positions.json")
    
    print(f"\n{'='*60}")
    print("[PASS] All position tracking tests passed!")
    return 0

if __name__ == '__main__':
    sys.exit(test_position_manager())
