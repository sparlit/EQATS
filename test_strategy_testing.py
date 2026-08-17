#!/usr/bin/env python3
"""
Test Strategy Testing Implementation
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from strategy_testing import (
    StrategyTester, StrategyTestResult,
    get_strategy_tester,
    simple_buy_hold, simple_sell_hold, random_strategy
)

def test_strategy_testing():
    """Test strategy testing functionality."""
    print("Testing strategy testing implementation...")
    
    # Test 1: Initialize strategy tester
    print("\n1. Testing strategy tester initialization...")
    tester = StrategyTester()
    print(f"   Pass criteria: {tester.pass_criteria}")
    if tester.pass_criteria:
        print("   [PASS] Strategy tester initialized correctly")
    else:
        print("   [FAIL] Strategy tester initialization failed")
        return 1
    
    # Test 2: Set pass criteria
    print("\n2. Testing pass criteria setting...")
    tester.set_pass_criteria({'min_win_rate': 0.50, 'max_drawdown': 0.15})
    print(f"   Updated min_win_rate: {tester.pass_criteria['min_win_rate']}")
    if tester.pass_criteria['min_win_rate'] == 0.50:
        print("   [PASS] Pass criteria set correctly")
    else:
        print("   [FAIL] Pass criteria not set")
        return 1
    
    # Test 3: Test single strategy
    print("\n3. Testing single strategy test...")
    sample_data = [
        {'close': 1.0950, 'open': 1.0940, 'high': 1.0960, 'low': 1.0930},
        {'close': 1.0955, 'open': 1.0950, 'high': 1.0965, 'low': 1.0945},
        {'close': 1.0960, 'open': 1.0955, 'high': 1.0970, 'low': 1.0950},
        {'close': 1.0955, 'open': 1.0960, 'high': 1.0965, 'low': 1.0950},
        {'close': 1.0950, 'open': 1.0955, 'high': 1.0960, 'low': 1.0945}
    ]
    
    result = tester.test_strategy(
        strategy_name="Buy and Hold",
        strategy=simple_buy_hold,
        parameters={},
        data=sample_data
    )
    
    print(f"   Strategy name: {result.strategy_name}")
    print(f"   Trades: {result.backtest_result.total_trades}")
    print(f"   Passed: {result.passed}")
    if result.strategy_name == "Buy and Hold":
        print("   [PASS] Single strategy test works")
    else:
        print("   [FAIL] Single strategy test failed")
        return 1
    
    # Test 4: Test multiple strategies
    print("\n4. Testing multiple strategies comparison...")
    strategies = [
        {'name': 'Buy Hold', 'function': simple_buy_hold, 'parameters': {}},
        {'name': 'Sell Hold', 'function': simple_sell_hold, 'parameters': {}},
        {'name': 'Random', 'function': random_strategy, 'parameters': {}}
    ]
    
    results = tester.compare_strategies(strategies, sample_data)
    print(f"   Results count: {len(results)}")
    if len(results) == 3:
        print("   [PASS] Multiple strategies compared correctly")
    else:
        print("   [FAIL] Multiple strategies comparison failed")
        return 1
    
    # Test 5: Get best strategy
    print("\n5. Testing best strategy retrieval...")
    best = tester.get_best_strategy()
    if best:
        print(f"   Best strategy: {best.strategy_name}")
        print(f"   Best P&L: {best.backtest_result.total_pnl:.2f}")
        print("   [PASS] Best strategy retrieved correctly")
    else:
        print("   [FAIL] Best strategy retrieval failed")
        return 1
    
    # Test 6: Get summary
    print("\n6. Testing summary generation...")
    summary = tester.get_summary()
    print(f"   Total tests: {summary['total_tests']}")
    print(f"   Passed: {summary['passed']}")
    print(f"   Failed: {summary['failed']}")
    if summary['total_tests'] > 0:
        print("   [PASS] Summary generated correctly")
    else:
        print("   [FAIL] Summary generation failed")
        return 1
    
    # Test 7: Criteria checking
    print("\n7. Testing criteria checking...")
    # Reset to easier criteria for testing
    tester.set_pass_criteria({'min_win_rate': 0.0, 'max_drawdown': 1.0, 'min_profit_factor': 0.0, 'min_sharpe_ratio': 0.0})
    
    result = tester.test_strategy(
        strategy_name="Test Strategy",
        strategy=simple_buy_hold,
        parameters={},
        data=sample_data
    )
    
    print(f"   Passed with easy criteria: {result.passed}")
    if result.passed:
        print("   [PASS] Criteria checking works")
    else:
        print("   [FAIL] Criteria checking failed")
        return 1
    
    # Test 8: Save results
    print("\n8. Testing results saving...")
    saved = tester.save_results("test_strategy_results.json")
    print(f"   Saved: {saved}")
    if saved:
        print("   [PASS] Results saved correctly")
    else:
        print("   [FAIL] Results saving failed")
        return 1
    
    # Cleanup
    if os.path.exists("test_strategy_results.json"):
        os.remove("test_strategy_results.json")
    
    # Test 9: Global tester
    print("\n9. Testing global tester instance...")
    global_tester = get_strategy_tester()
    if global_tester:
        print("   [PASS] Global tester instance works")
    else:
        print("   [FAIL] Global tester instance failed")
        return 1
    
    # Test 10: Empty results handling
    print("\n10. Testing empty results handling...")
    empty_tester = StrategyTester()
    summary = empty_tester.get_summary()
    best = empty_tester.get_best_strategy()
    
    print(f"   Empty summary: {summary['total_tests']}")
    print(f"   Empty best: {best}")
    if summary['total_tests'] == 0 and best is None:
        print("   [PASS] Empty results handled correctly")
    else:
        print("   [FAIL] Empty results not handled")
        return 1
    
    print(f"\n{'='*60}")
    print("[PASS] All strategy testing tests passed!")
    return 0

if __name__ == '__main__':
    sys.exit(test_strategy_testing())
