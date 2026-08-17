#!/usr/bin/env python3
"""
Test Data Validation for External Feeds
"""

import sys
import os
import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_validator import get_data_validator

def test_data_validator():
    """Test data validation functionality."""
    print("Testing data validation implementation...")
    
    validator = get_data_validator()
    
    # Test 1: Valid price data
    print("\n1. Testing valid price data...")
    valid_prices = [1.0950, 1.0955, 1.0960, 1.0965, 1.0970, 1.0975, 1.0980, 1.0985, 1.0990, 1.0995]
    result = validator.validate_prices(valid_prices, "EURUSD")
    print(f"   Valid: {result['valid']}")
    print(f"   Score: {result['score']}")
    print(f"   Errors: {result['errors']}")
    print(f"   Warnings: {result['warnings']}")
    if result['valid'] and result['score'] >= 90:
        print("   [PASS] Valid data accepted")
    else:
        print("   [FAIL] Valid data rejected")
        return 1
    
    # Test 2: Insufficient data points
    print("\n2. Testing insufficient data points...")
    short_prices = [1.0950, 1.0955]
    result = validator.validate_prices(short_prices, "EURUSD")
    print(f"   Valid: {result['valid']}")
    print(f"   Score: {result['score']}")
    if not result['valid'] and "Insufficient data points" in result['errors'][0]:
        print("   [PASS] Insufficient data rejected")
    else:
        print("   [FAIL] Insufficient data not rejected")
        return 1
    
    # Test 3: Data with None values
    print("\n3. Testing data with None values...")
    none_prices = [1.0950, None, 1.0960, 1.0965, 1.0970]
    result = validator.validate_prices(none_prices, "EURUSD")
    print(f"   Valid: {result['valid']}")
    print(f"   Score: {result['score']}")
    print(f"   Errors: {result['errors']}")
    if not result['valid'] and len(result['errors']) > 0:
        print("   [PASS] None values detected")
    else:
        print("   [FAIL] None values not detected")
        return 1
    
    # Test 4: Data with excessive price jump
    print("\n4. Testing excessive price jump...")
    jump_prices = [1.0950, 1.0955, 1.0960, 1.0965, 1.0970, 1.0975, 1.0980, 1.0985, 1.0990, 1.2500]  # ~14% jump
    result = validator.validate_prices(jump_prices, "EURUSD")
    print(f"   Valid: {result['valid']}")
    print(f"   Score: {result['score']}")
    if not result['valid'] and "Excessive price jump" in result['errors'][0]:
        print("   [PASS] Excessive jump detected")
    else:
        print("   [FAIL] Excessive jump not detected")
        return 1
    
    # Test 5: Timestamp validation
    print("\n5. Testing timestamp validation...")
    fresh_timestamp = datetime.datetime.now().isoformat()
    result = validator.validate_timestamp(fresh_timestamp)
    print(f"   Valid: {result['valid']}")
    print(f"   Score: {result['score']}")
    if result['valid'] and result['score'] >= 90:
        print("   [PASS] Fresh timestamp accepted")
    else:
        print("   [FAIL] Fresh timestamp rejected")
        return 1
    
    # Test 6: Stale timestamp
    print("\n6. Testing stale timestamp...")
    stale_timestamp = (datetime.datetime.now().replace(second=0, microsecond=0) - 
                      datetime.timedelta(minutes=10)).isoformat()
    result = validator.validate_timestamp(stale_timestamp)
    print(f"   Valid: {result['valid']}")
    print(f"   Score: {result['score']}")
    if not result['valid'] and "stale" in result['errors'][0]:
        print("   [PASS] Stale timestamp rejected")
    else:
        print("   [FAIL] Stale timestamp not rejected")
        return 1
    
    # Test 7: Completeness validation
    print("\n7. Testing completeness validation...")
    complete_data = {'open': 1.0950, 'high': 1.0980, 'low': 1.0940, 'close': 1.0970}
    required_fields = ['open', 'high', 'low', 'close']
    result = validator.validate_completeness(complete_data, required_fields)
    print(f"   Valid: {result['valid']}")
    print(f"   Score: {result['score']}")
    if result['valid'] and result['score'] >= 90:
        print("   [PASS] Complete data accepted")
    else:
        print("   [FAIL] Complete data rejected")
        return 1
    
    # Test 8: Incomplete data
    print("\n8. Testing incomplete data...")
    incomplete_data = {'open': 1.0950, 'close': 1.0970}
    result = validator.validate_completeness(incomplete_data, required_fields)
    print(f"   Valid: {result['valid']}")
    print(f"   Score: {result['score']}")
    if not result['valid'] and "Missing required fields" in result['errors'][0]:
        print("   [PASS] Incomplete data rejected")
    else:
        print("   [FAIL] Incomplete data not rejected")
        return 1
    
    # Test 9: OHLCV consistency validation
    print("\n9. Testing OHLCV consistency...")
    valid_ohlcv = [
        {'open': 1.0950, 'high': 1.0980, 'low': 1.0940, 'close': 1.0970},
        {'open': 1.0970, 'high': 1.1000, 'low': 1.0960, 'close': 1.0990}
    ]
    result = validator.validate_data_consistency(valid_ohlcv)
    print(f"   Valid: {result['valid']}")
    print(f"   Score: {result['score']}")
    if result['valid'] and result['score'] >= 90:
        print("   [PASS] Consistent OHLCV accepted")
    else:
        print("   [FAIL] Consistent OHLCV rejected")
        return 1
    
    # Test 10: Invalid OHLCV (high < low)
    print("\n10. Testing invalid OHLCV (high < low)...")
    invalid_ohlcv = [
        {'open': 1.0950, 'high': 1.0940, 'low': 1.0980, 'close': 1.0970}
    ]
    result = validator.validate_data_consistency(invalid_ohlcv)
    print(f"   Valid: {result['valid']}")
    print(f"   Score: {result['score']}")
    if not result['valid'] and "High < Low" in result['errors'][0]:
        print("   [PASS] Invalid OHLCV detected")
    else:
        print("   [FAIL] Invalid OHLCV not detected")
        return 1
    
    print(f"\n{'='*60}")
    print("[PASS] All data validation tests passed!")
    return 0

if __name__ == '__main__':
    sys.exit(test_data_validator())
