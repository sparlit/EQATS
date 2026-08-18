#!/usr/bin/env python3
"""
Test Input Validation Implementation
"""

from input_validation import get_validator

def test_input_validation():
    """Test input validation functionality."""
    print("Testing input validation implementation...")
    
    validator = get_validator()
    
    # Test 1: Symbol validation
    print("\n1. Testing symbol validation...")
    try:
        result = validator.validate_symbol('EURUSD')
        print(f"   Valid symbol: {result} - PASS")
    except Exception as e:
        print(f"   Valid symbol failed: {e} - FAIL")
        assert False, "Test condition failed"
    
    try:
        validator.validate_symbol('XYZ')  # Too short
        print("   Invalid symbol accepted - FAIL")
        assert False, "Test condition failed"
    except Exception:
        print("   Invalid symbol rejected - PASS")
    
    # Test 2: Price validation
    print("\n2. Testing price validation...")
    try:
        result = validator.validate_price('1.1234', 'EURUSD')
        print(f"   Valid price: {result} - PASS")
    except Exception as e:
        print(f"   Valid price failed: {e} - FAIL")
        assert False, "Test condition failed"
    
    try:
        validator.validate_price('-1.0', 'EURUSD')
        print("   Negative price accepted - FAIL")
        assert False, "Test condition failed"
    except Exception:
        print("   Negative price rejected - PASS")
    
    # Test 3: Lot size validation
    print("\n3. Testing lot size validation...")
    try:
        result = validator.validate_lots('0.1', 'EURUSD')
        print(f"   Valid lot size: {result} - PASS")
    except Exception as e:
        print(f"   Valid lot size failed: {e} - FAIL")
        assert False, "Test condition failed"
    
    try:
        validator.validate_lots('0.001', 'EURUSD')
        print("   Too small lot size accepted - FAIL")
        assert False, "Test condition failed"
    except Exception:
        print("   Too small lot size rejected - PASS")
    
    # Test 4: Username validation
    print("\n4. Testing username validation...")
    try:
        result = validator.validate_username('testuser')
        print(f"   Valid username: {result} - PASS")
    except Exception as e:
        print(f"   Valid username failed: {e} - FAIL")
        assert False, "Test condition failed"
    
    try:
        validator.validate_username('te')
        print("   Too short username accepted - FAIL")
        assert False, "Test condition failed"
    except Exception:
        print("   Too short username rejected - PASS")
    
    # Test 5: Password validation
    print("\n5. Testing password validation...")
    try:
        result = validator.validate_password('TestPass123!')
        print(f"   Valid password accepted - PASS")
    except Exception as e:
        print(f"   Valid password failed: {e} - FAIL")
        assert False, "Test condition failed"
    
    try:
        validator.validate_password('weak')
        print("   Weak password accepted - FAIL")
        assert False, "Test condition failed"
    except Exception:
        print("   Weak password rejected - PASS")
    
    # Test 6: PIN validation
    print("\n6. Testing PIN validation...")
    try:
        result = validator.validate_pin('1234')
        print(f"   Valid PIN: {result} - PASS")
    except Exception as e:
        print(f"   Valid PIN failed: {e} - FAIL")
        assert False, "Test condition failed"
    
    try:
        validator.validate_pin('abc')
        print("   Non-numeric PIN accepted - FAIL")
        assert False, "Test condition failed"
    except Exception:
        print("   Non-numeric PIN rejected - PASS")
    
    # Test 7: MFA token validation
    print("\n7. Testing MFA token validation...")
    try:
        result = validator.validate_mfa_token('123456')
        print(f"   Valid MFA token: {result} - PASS")
    except Exception as e:
        print(f"   Valid MFA token failed: {e} - FAIL")
        assert False, "Test condition failed"
    
    try:
        validator.validate_mfa_token('12345')
        print("   Invalid MFA token length accepted - FAIL")
        assert False, "Test condition failed"
    except Exception:
        print("   Invalid MFA token length rejected - PASS")
    
    # Test 8: Order validation
    print("\n8. Testing order validation...")
    try:
        order_data = {
            'symbol': 'EURUSD',
            'order_type': 'BUY',
            'lots': '0.1',
            'price': '1.1234',
            'stop_loss': '1.1200',
            'take_profit': '1.1300'
        }
        result = validator.validate_order(order_data)
        print(f"   Valid order accepted - PASS")
    except Exception as e:
        print(f"   Valid order failed: {e} - FAIL")
        assert False, "Test condition failed"
    
    try:
        order_data = {
            'symbol': 'EURUSD',
            'order_type': 'INVALID',
            'lots': '0.1'
        }
        validator.validate_order(order_data)
        print("   Invalid order type accepted - FAIL")
        assert False, "Test condition failed"
    except Exception:
        print("   Invalid order type rejected - PASS")
    
    print(f"\n{'='*60}")
    print("[PASS] All input validation tests passed!")
    # Clean test exit

if __name__ == '__main__':
    import sys
    sys.exit(test_input_validation())
