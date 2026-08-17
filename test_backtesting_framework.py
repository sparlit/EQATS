#!/usr/bin/env python3
"""
Test Backtesting Framework Implementation
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtesting_framework import (
    BacktestEngine, BacktestResult, Trade,
    get_backtest_engine, simple_ma_crossover
)

def test_backtesting_framework():
    """Test backtesting framework functionality."""
    print("Testing backtesting framework implementation...")
    
    # Test 1: Initialize backtest engine
    print("\n1. Testing backtest engine initialization...")
    engine = BacktestEngine(initial_balance=10000.0, commission_per_lot=7.0)
    print(f"   Initial balance: {engine.initial_balance}")
    print(f"   Current balance: {engine.current_balance}")
    if engine.initial_balance == 10000.0:
        print("   [PASS] Backtest engine initialized correctly")
    else:
        print("   [FAIL] Backtest engine initialization failed")
        return 1
    
    # Test 2: Open position
    print("\n2. Testing position opening...")
    success = engine.open_position("EURUSD", "BUY", 0.1, 1.0950, sl=1.0900, tp=1.1100)
    print(f"   Position opened: {success}")
    print(f"   Open positions: {len(engine.positions)}")
    if success and len(engine.positions) == 1:
        print("   [PASS] Position opened correctly")
    else:
        print("   [FAIL] Position opening failed")
        return 1
    
    # Test 3: Close position
    print("\n3. Testing position closing...")
    success = engine.close_position("EURUSD", 1.0960, "Manual close")
    print(f"   Position closed: {success}")
    print(f"   Trades: {len(engine.trades)}")
    if success and len(engine.trades) == 1:
        print("   [PASS] Position closed correctly")
    else:
        print("   [FAIL] Position closing failed")
        return 1
    
    # Test 4: Check trade details
    print("\n4. Testing trade details...")
    trade = engine.trades[0]
    print(f"   Trade P&L: {trade.pnl:.2f}")
    print(f"   Trade direction: {trade.direction}")
    if trade.symbol == "EURUSD" and trade.direction == "BUY":
        print("   [PASS] Trade details recorded correctly")
    else:
        print("   [FAIL] Trade details not recorded")
        return 1
    
    # Test 5: Reset engine
    print("\n5. Testing engine reset...")
    engine.reset()
    print(f"   Balance after reset: {engine.current_balance}")
    print(f"   Positions after reset: {len(engine.positions)}")
    print(f"   Trades after reset: {len(engine.trades)}")
    if engine.current_balance == 10000.0 and len(engine.positions) == 0:
        print("   [PASS] Engine reset correctly")
    else:
        print("   [FAIL] Engine reset failed")
        return 1
    
    # Test 6: Multiple trades
    print("\n6. Testing multiple trades...")
    engine.open_position("EURUSD", "BUY", 0.1, 1.0950)
    engine.open_position("GBPUSD", "SELL", 0.2, 1.3000)
    engine.close_position("EURUSD", 1.0960)
    engine.close_position("GBPUSD", 1.2990)
    
    print(f"   Total trades: {len(engine.trades)}")
    if len(engine.trades) == 2:
        print("   [PASS] Multiple trades handled correctly")
    else:
        print("   [FAIL] Multiple trades not handled")
        return 1
    
    # Test 7: Equity curve
    print("\n7. Testing equity curve...")
    equity_length = len(engine.equity_curve)
    print(f"   Equity curve points: {equity_length}")
    if equity_length > 0:
        print("   [PASS] Equity curve tracked correctly")
    else:
        print("   [FAIL] Equity curve not tracked")
        return 1
    
    # Test 8: Stop loss execution
    print("\n8. Testing stop loss execution...")
    engine.reset()
    engine.open_position("EURUSD", "BUY", 0.1, 1.0950, sl=1.0940)
    engine._check_sl_tp(1.0935)  # Price below SL
    
    print(f"   Positions after SL: {len(engine.positions)}")
    print(f"   Trades after SL: {len(engine.trades)}")
    if len(engine.positions) == 0 and len(engine.trades) == 1:
        print("   [PASS] Stop loss executed correctly")
    else:
        print("   [FAIL] Stop loss not executed")
        return 1
    
    # Test 9: Take profit execution
    print("\n9. Testing take profit execution...")
    engine.reset()
    engine.open_position("EURUSD", "BUY", 0.1, 1.0950, tp=1.0960)
    engine._check_sl_tp(1.0965)  # Price above TP
    
    print(f"   Positions after TP: {len(engine.positions)}")
    print(f"   Trades after TP: {len(engine.trades)}")
    if len(engine.positions) == 0 and len(engine.trades) == 1:
        print("   [PASS] Take profit executed correctly")
    else:
        print("   [FAIL] Take profit not executed")
        return 1
    
    # Test 10: Backtest results calculation
    print("\n10. Testing backtest results calculation...")
    engine.reset()
    engine.open_position("EURUSD", "BUY", 0.1, 1.0950)
    engine.close_position("EURUSD", 1.0960)
    engine.open_position("GBPUSD", "SELL", 0.1, 1.3000)
    engine.close_position("GBPUSD", 1.2990)
    
    result = engine._calculate_results()
    print(f"   Total trades: {result.total_trades}")
    print(f"   Winning trades: {result.winning_trades}")
    print(f"   Total P&L: {result.total_pnl:.2f}")
    if result.total_trades == 2:
        print("   [PASS] Results calculated correctly")
    else:
        print("   [FAIL] Results calculation failed")
        return 1
    
    # Test 11: Strategy parameters
    print("\n11. Testing strategy parameters...")
    engine.set_strategy_params({'fast_ma': 10, 'slow_ma': 20})
    print(f"   Strategy params: {engine.strategy_params}")
    if engine.strategy_params['fast_ma'] == 10:
        print("   [PASS] Strategy parameters set correctly")
    else:
        print("   [FAIL] Strategy parameters not set")
        return 1
    
    # Test 12: Run backtest with sample data
    print("\n12. Testing backtest run with sample data...")
    engine.reset()
    
    # Create sample data
    sample_data = [
        {'close': 1.0950, 'open': 1.0940, 'high': 1.0960, 'low': 1.0930},
        {'close': 1.0955, 'open': 1.0950, 'high': 1.0965, 'low': 1.0945},
        {'close': 1.0960, 'open': 1.0955, 'high': 1.0970, 'low': 1.0950},
        {'close': 1.0955, 'open': 1.0960, 'high': 1.0965, 'low': 1.0950},
        {'close': 1.0950, 'open': 1.0955, 'high': 1.0960, 'low': 1.0945}
    ]
    
    result = engine.run_backtest(sample_data, simple_ma_crossover)
    print(f"   Backtest trades: {result.total_trades}")
    print("   [PASS] Backtest run completed")
    
    # Test 13: Save results
    print("\n13. Testing results saving...")
    saved = engine.save_results(result, "test_backtest_results.json")
    print(f"   Saved: {saved}")
    if saved:
        print("   [PASS] Results saved correctly")
    else:
        print("   [FAIL] Results saving failed")
        return 1
    
    # Cleanup
    if os.path.exists("test_backtest_results.json"):
        os.remove("test_backtest_results.json")
    
    # Test 14: Global engine
    print("\n14. Testing global engine instance...")
    global_engine = get_backtest_engine()
    if global_engine:
        print("   [PASS] Global engine instance works")
    else:
        print("   [FAIL] Global engine instance failed")
        return 1
    
    # Test 15: Commission calculation
    print("\n15. Testing commission calculation...")
    engine.reset()
    engine.open_position("EURUSD", "BUY", 0.1, 1.0950)
    engine.close_position("EURUSD", 1.0950)  # Same price, only commission loss
    
    print(f"   P&L (commission only): {engine.trades[0].pnl:.2f}")
    if engine.trades[0].pnl < 0:  # Should be negative due to commission
        print("   [PASS] Commission calculated correctly")
    else:
        print("   [FAIL] Commission not calculated")
        return 1
    
    print(f"\n{'='*60}")
    print("[PASS] All backtesting framework tests passed!")
    return 0

if __name__ == '__main__':
    sys.exit(test_backtesting_framework())
