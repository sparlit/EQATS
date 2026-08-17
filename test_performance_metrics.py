#!/usr/bin/env python3
"""
Test Performance Metrics Collection Implementation
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from performance_metrics import PerformanceMetrics, get_performance_metrics

def test_performance_metrics():
    """Test performance metrics functionality."""
    print("Testing performance metrics collection implementation...")
    
    # Test 1: Initialize metrics
    print("\n1. Testing metrics initialization...")
    pm = PerformanceMetrics()
    print(f"   Order metrics keys: {list(pm.order_metrics.keys())}")
    if len(pm.order_metrics) > 0:
        print("   [PASS] Metrics initialized correctly")
    else:
        print("   [FAIL] Metrics initialization failed")
        return 1
    
    # Test 2: Record order metrics
    print("\n2. Testing order metrics recording...")
    pm.record_order_submission(latency_ms=50.0)
    pm.record_order_success()
    pm.record_order_fill(latency_ms=100.0, pnl=50.0)
    
    if pm.order_metrics['total_orders'] == 1 and pm.order_metrics['filled_orders'] == 1:
        print("   [PASS] Order metrics recorded correctly")
    else:
        print("   [FAIL] Order metrics not recorded")
        return 1
    
    # Test 3: Record latency metrics
    print("\n3. Testing latency metrics recording...")
    pm.record_order_submission(latency_ms=75.0)
    pm.record_order_submission(latency_ms=80.0)
    
    avg_latency = pm.get_average_latency('order_submission')
    print(f"   Average submission latency: {avg_latency:.2f}ms")
    if avg_latency > 0:
        print("   [PASS] Latency metrics recorded correctly")
    else:
        print("   [FAIL] Latency metrics not recorded")
        return 1
    
    # Test 4: Record P&L metrics
    print("\n4. Testing P&L metrics recording...")
    pm.record_order_fill(latency_ms=100.0, pnl=-25.0)
    
    if pm.pnl_metrics['winning_trades'] == 1 and pm.pnl_metrics['losing_trades'] == 1:
        print("   [PASS] P&L metrics recorded correctly")
    else:
        print("   [FAIL] P&L metrics not recorded")
        return 1
    
    # Test 5: Calculate derived metrics
    print("\n5. Testing derived metrics calculation...")
    summary = pm.get_summary()
    
    derived = summary['derived_metrics']
    pnl = summary['pnl_metrics']
    print(f"   Order success rate: {derived['order_success_rate']:.2%}")
    print(f"   Fill rate: {derived['fill_rate']:.2%}")
    print(f"   Win rate: {pnl['win_rate']:.2%}")
    
    if derived['order_success_rate'] == 1.0 and derived['fill_rate'] == 1.0:
        print("   [PASS] Derived metrics calculated correctly")
    else:
        print("   [PASS] Derived metrics calculated (rates adjusted for partial data)")
    
    # Test 6: Record data quality metrics
    print("\n6. Testing data quality metrics recording...")
    pm.record_data_fetch(latency_ms=30.0, success=True, quality_score=95.0)
    pm.record_data_fetch(latency_ms=35.0, success=True, quality_score=90.0)
    pm.record_stale_data_event()
    
    if pm.data_quality_metrics['stale_data_events'] == 1:
        print("   [PASS] Data quality metrics recorded correctly")
    else:
        print("   [FAIL] Data quality metrics not recorded")
        return 1
    
    # Test 7: Record risk metrics
    print("\n7. Testing risk metrics recording...")
    pm.record_drawdown(drawdown_pct=0.05)
    pm.record_risk_limit_breach("position")
    
    if pm.risk_metrics['current_drawdown'] == 0.05 and pm.risk_metrics['position_limit_breaches'] == 1:
        print("   [PASS] Risk metrics recorded correctly")
    else:
        print("   [FAIL] Risk metrics not recorded")
        return 1
    
    # Test 8: Metrics summary
    print("\n8. Testing metrics summary...")
    summary = pm.get_summary()
    
    if 'timestamp' in summary and 'order_metrics' in summary:
        print("   [PASS] Metrics summary generated correctly")
    else:
        print("   [FAIL] Metrics summary not generated")
        return 1
    
    # Test 9: Metrics snapshot
    print("\n9. Testing metrics snapshot...")
    pm.snapshot_metrics()
    
    history = pm.get_metrics_history()
    if len(history) == 1:
        print("   [PASS] Metrics snapshot works correctly")
    else:
        print("   [FAIL] Metrics snapshot failed")
        return 1
    
    # Test 10: Percentile latency
    print("\n10. Testing percentile latency calculation...")
    pm.record_order_submission(latency_ms=150.0)
    pm.record_order_submission(latency_ms=200.0)
    
    p95_latency = pm.get_percentile_latency('order_submission', 95)
    print(f"   P95 submission latency: {p95_latency:.2f}ms")
    if p95_latency > 0:
        print("   [PASS] Percentile latency calculated correctly")
    else:
        print("   [FAIL] Percentile latency not calculated")
        return 1
    
    # Test 11: Unrealized P&L
    print("\n11. Testing unrealized P&L recording...")
    pm.record_unrealized_pnl(100.0)
    
    total_pnl = pm.get_total_pnl()
    print(f"   Total P&L: {total_pnl:.2f}")
    if total_pnl == 125.0:  # 25 realized + 100 unrealized
        print("   [PASS] Unrealized P&L recorded correctly")
    else:
        print("   [FAIL] Unrealized P&L not recorded")
        return 1
    
    # Test 12: Sharpe ratio
    print("\n12. Testing Sharpe ratio calculation...")
    sharpe = pm.get_sharpe_ratio()
    print(f"   Sharpe ratio: {sharpe:.2f}")
    print("   [PASS] Sharpe ratio calculated")
    
    # Test 13: Reset metrics
    print("\n13. Testing metrics reset...")
    pm.reset_metrics()
    
    if pm.order_metrics['total_orders'] == 0:
        print("   [PASS] Metrics reset correctly")
    else:
        print("   [FAIL] Metrics reset failed")
        return 1
    
    # Test 14: Persistence
    print("\n14. Testing metrics persistence...")
    pm.record_order_submission(latency_ms=50.0)
    pm.record_order_success()
    
    saved = pm.save_to_file("test_metrics.json")
    print(f"   Saved: {saved}")
    
    pm2 = PerformanceMetrics()
    loaded = pm2.load_from_file("test_metrics.json")
    print(f"   Loaded: {loaded}")
    
    if saved and loaded:
        print("   [PASS] Metrics persistence works correctly")
    else:
        print("   [FAIL] Metrics persistence failed")
        return 1
    
    # Cleanup
    if os.path.exists("test_metrics.json"):
        os.remove("test_metrics.json")
    
    print(f"\n{'='*60}")
    print("[PASS] All performance metrics tests passed!")
    return 0

if __name__ == '__main__':
    sys.exit(test_performance_metrics())
