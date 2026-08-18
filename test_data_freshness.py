#!/usr/bin/env python3
"""
Test Data Freshness Monitoring Implementation
"""

import sys
import os
import time
from datetime import datetime as dt, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_freshness import DataFreshnessMonitor, DataQualityTracker

def test_data_freshness():
    """Test data freshness monitoring functionality."""
    print("Testing data freshness monitoring implementation...")
    
    # Test 1: Update data timestamp
    print("\n1. Testing data timestamp update...")
    monitor = DataFreshnessMonitor()
    monitor.update_data_timestamp("EURUSD")
    print(f"   Timestamps stored: {len(monitor.data_timestamps)}")
    if "EURUSD" in monitor.data_timestamps:
        print("   [PASS] Timestamp updated correctly")
    else:
        print("   [FAIL] Timestamp not updated")
        assert False, "Test condition failed"
    
    # Test 2: Get data age
    print("\n2. Testing data age calculation...")
    time.sleep(0.1)  # Small delay
    age = monitor.get_data_age("EURUSD")
    print(f"   Data age: {age:.2f} seconds")
    if age is not None and age > 0:
        print("   [PASS] Data age calculated correctly")
    else:
        print("   [FAIL] Data age not calculated")
        assert False, "Test condition failed"
    
    # Test 3: Check freshness
    print("\n3. Testing freshness check...")
    result = monitor.check_freshness("EURUSD")
    print(f"   Fresh: {result['fresh']}")
    print(f"   Stale: {result['stale']}")
    print(f"   Age: {result['age_seconds']:.2f}s")
    if result['fresh'] and not result['stale']:
        print("   [PASS] Freshness check correct")
    else:
        print("   [FAIL] Freshness check incorrect")
        assert False, "Test condition failed"
    
    # Test 4: Custom freshness threshold
    print("\n4. Testing custom freshness threshold...")
    monitor.set_freshness_threshold("BTCUSD", threshold_seconds=2.0)
    monitor.update_data_timestamp("BTCUSD")
    threshold = monitor.get_freshness_threshold("BTCUSD")
    print(f"   BTCUSD threshold: {threshold}s")
    if threshold == 2.0:
        print("   [PASS] Custom threshold set correctly")
    else:
        print("   [FAIL] Custom threshold not set")
        assert False, "Test condition failed"
    
    # Test 5: Stale data detection
    print("\n5. Testing stale data detection...")
    # Set a very old timestamp
    old_time = (dt.now() - timedelta(seconds=120)).isoformat()
    monitor.update_data_timestamp("GBPUSD", timestamp=old_time)
    
    result = monitor.check_freshness("GBPUSD")
    print(f"   Stale: {result['stale']}")
    print(f"   Age: {result['age_seconds']:.2f}s")
    if result['stale']:
        print("   [PASS] Stale data detected")
    else:
        print("   [FAIL] Stale data not detected")
        assert False, "Test condition failed"
    
    # Test 6: Check all symbols
    print("\n6. Testing check all symbols...")
    summary = monitor.check_all_symbols()
    print(f"   Total symbols: {summary['total_symbols']}")
    print(f"   Stale count: {summary['stale_count']}")
    print(f"   Fresh count: {summary['fresh_count']}")
    if summary['total_symbols'] >= 2 and summary['stale_count'] >= 1:
        print("   [PASS] All symbols checked correctly")
    else:
        print("   [FAIL] All symbols check failed")
        assert False, "Test condition failed"
    
    # Test 7: Get stale symbols
    print("\n7. Testing get stale symbols...")
    stale_symbols = monitor.get_stale_symbols()
    print(f"   Stale symbols: {stale_symbols}")
    if "GBPUSD" in stale_symbols:
        print("   [PASS] Stale symbols retrieved correctly")
    else:
        print("   [FAIL] Stale symbols not retrieved")
        assert False, "Test condition failed"
    
    # Test 8: Freshness summary
    print("\n8. Testing freshness summary...")
    summary = monitor.get_freshness_summary()
    print(f"   Total symbols: {summary['total_symbols']}")
    print(f"   Freshness %: {summary['freshness_percentage']:.1f}%")
    if summary['total_symbols'] > 0:
        print("   [PASS] Freshness summary correct")
    else:
        print("   [FAIL] Freshness summary incorrect")
        assert False, "Test condition failed"
    
    # Test 9: Should block trading
    print("\n9. Testing trading block decision...")
    should_block = monitor.should_block_trading("GBPUSD")
    print(f"   Should block GBPUSD: {should_block}")
    if should_block:
        print("   [PASS] Trading block decision correct")
    else:
        print("   [FAIL] Trading block decision incorrect")
        assert False, "Test condition failed"
    
    # Test 10: Warning threshold
    print("\n10. Testing warning threshold...")
    monitor2 = DataFreshnessMonitor()
    monitor2.set_freshness_threshold("EURUSD", threshold_seconds=10.0)
    monitor2.update_data_timestamp("EURUSD")
    time.sleep(0.1)
    
    result = monitor2.check_freshness("EURUSD")
    print(f"   Warning: {result['warning']}")
    print(f"   Age ratio: {result['age_ratio']:.2f}")
    if not result['warning']:  # Should not warn yet
        print("   [PASS] Warning threshold correct")
    else:
        print("   [FAIL] Warning threshold incorrect")
        assert False, "Test condition failed"
    
    # Test 11: Data quality tracker
    print("\n11. Testing data quality tracker...")
    tracker = DataQualityTracker()
    tracker.update_quality_score("EURUSD", 85.0)
    score = tracker.quality_scores.get("EURUSD")
    print(f"   Quality score: {score}")
    if score == 85.0:
        print("   [PASS] Quality score updated correctly")
    else:
        print("   [FAIL] Quality score not updated")
        assert False, "Test condition failed"
    
    # Test 12: Record error
    print("\n12. Testing error recording...")
    tracker.record_error("EURUSD", "Connection timeout")
    error_count = tracker.error_counts.get("EURUSD", 0)
    print(f"   Error count: {error_count}")
    if error_count == 1:
        print("   [PASS] Error recorded correctly")
    else:
        print("   [FAIL] Error not recorded")
        assert False, "Test condition failed"
    
    # Test 13: Record gap
    print("\n13. Testing gap recording...")
    tracker.record_gap("EURUSD")
    gap_count = tracker.gap_counts.get("EURUSD", 0)
    print(f"   Gap count: {gap_count}")
    if gap_count == 1:
        print("   [PASS] Gap recorded correctly")
    else:
        print("   [FAIL] Gap not recorded")
        assert False, "Test condition failed"
    
    # Test 14: Quality summary
    print("\n14. Testing quality summary...")
    summary = tracker.get_quality_summary("EURUSD")
    print(f"   Quality score: {summary['quality_score']}")
    print(f"   Error count: {summary['error_count']}")
    print(f"   Gap count: {summary['gap_count']}")
    print(f"   Acceptable: {summary['acceptable']}")
    if summary['quality_score'] == 85.0 and summary['error_count'] == 1:
        print("   [PASS] Quality summary correct")
    else:
        print("   [FAIL] Quality summary incorrect")
        assert False, "Test condition failed"
    
    # Test 15: Data acceptability
    print("\n15. Testing data acceptability...")
    acceptable = tracker.is_data_acceptable("EURUSD")
    print(f"   Acceptable: {acceptable}")
    if acceptable:  # 85 >= 70
        print("   [PASS] Data acceptability correct")
    else:
        print("   [FAIL] Data acceptability incorrect")
        assert False, "Test condition failed"
    
    # Test 16: Unacceptable data
    print("\n16. Testing unacceptable data...")
    tracker.update_quality_score("GBPUSD", 50.0)
    acceptable = tracker.is_data_acceptable("GBPUSD")
    print(f"   Acceptable: {acceptable}")
    if not acceptable:  # 50 < 70
        print("   [PASS] Unacceptable data detected")
    else:
        print("   [FAIL] Unacceptable data not detected")
        assert False, "Test condition failed"
    
    # Test 17: Reset tracking
    print("\n17. Testing reset tracking...")
    monitor.reset_tracking()
    print(f"   Timestamps after reset: {len(monitor.data_timestamps)}")
    print(f"   Stale symbols after reset: {len(monitor.stale_symbols)}")
    if len(monitor.data_timestamps) == 0 and len(monitor.stale_symbols) == 0:
        print("   [PASS] Reset tracking works correctly")
    else:
        print("   [FAIL] Reset tracking failed")
        assert False, "Test condition failed"
    
    # Test 18: Time until stale
    print("\n18. Testing time until stale calculation...")
    monitor3 = DataFreshnessMonitor()
    monitor3.set_freshness_threshold("EURUSD", threshold_seconds=60.0)
    monitor3.update_data_timestamp("EURUSD")
    
    result = monitor3.check_freshness("EURUSD")
    print(f"   Time until stale: {result['time_until_stale']:.2f}s")
    if result['time_until_stale'] > 0:
        print("   [PASS] Time until stale calculated correctly")
    else:
        print("   [FAIL] Time until stale not calculated")
        assert False, "Test condition failed"
    
    print(f"\n{'='*60}")
    print("[PASS] All data freshness monitoring tests passed!")
    # Clean test exit

if __name__ == '__main__':
    sys.exit(test_data_freshness())
