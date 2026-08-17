#!/usr/bin/env python3
"""
Unit Tests for Security Modules
Tests encryption, password management, MFA, input validation, and kill switch.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pyotp

def test_secure_encryption():
    """Test secure encryption module."""
    print("\n=== Testing Secure Encryption ===")
    
    try:
        from secure_encryption import SecureEncryption
        
        # Set test environment variable (64-char hex string = 256 bits)
        os.environ['ENCRYPTION_KEY'] = 'a' * 64  # 64 character hex string
        
        # Test 1: Encrypt and decrypt
        print("\n1. Testing encrypt/decrypt...")
        enc = SecureEncryption()
        plaintext = "test_secret_data"
        encrypted = enc.encrypt(plaintext)
        decrypted = enc.decrypt(encrypted)
        
        if decrypted == plaintext:
            print("   [PASS] Encrypt/decrypt works correctly")
        else:
            print("   [FAIL] Encrypt/decrypt failed")
            return False
        
        # Test 2: Different encryption produces different ciphertext
        print("\n2. Testing encryption uniqueness...")
        encrypted1 = enc.encrypt(plaintext)
        encrypted2 = enc.encrypt(plaintext)
        
        if encrypted1 != encrypted2:
            print("   [PASS] Encryption produces unique ciphertext")
        else:
            print("   [FAIL] Encryption not unique")
            return False
        
        print("\n[PASS] All secure encryption tests passed")
        return True
        
    except Exception as e:
        print(f"   [ERROR] Secure encryption test failed: {e}")
        return False


def test_password_manager():
    """Test password manager module."""
    print("\n=== Testing Password Manager ===")
    
    try:
        from password_manager import PasswordManager
        
        # Test 1: Hash password
        print("\n1. Testing password hashing...")
        pm = PasswordManager()
        password = "test_password_123"
        hashed = pm.hash_password(password)
        
        if hashed != password and len(hashed) > 50:  # Bcrypt hash is long
            print("   [PASS] Password hashed correctly")
        else:
            print("   [FAIL] Password hashing failed")
            return False
        
        # Test 2: Verify correct password
        print("\n2. Testing password verification (correct)...")
        if pm.verify_password(password, hashed):
            print("   [PASS] Correct password verified")
        else:
            print("   [FAIL] Correct password not verified")
            return False
        
        # Test 3: Verify incorrect password
        print("\n3. Testing password verification (incorrect)...")
        if not pm.verify_password("wrong_password", hashed):
            print("   [PASS] Incorrect password rejected")
        else:
            print("   [FAIL] Incorrect password accepted")
            return False
        
        print("\n[PASS] All password manager tests passed")
        return True
        
    except Exception as e:
        print(f"   [ERROR] Password manager test failed: {e}")
        return False


def test_mfa_manager():
    """Test MFA manager module."""
    print("\n=== Testing MFA Manager ===")
    
    try:
        from mfa_manager import MFAManager
        
        # Test 1: Generate secret
        print("\n1. Testing secret generation...")
        mfa = MFAManager()
        secret = mfa.generate_secret()
        
        if len(secret) > 20:
            print("   [PASS] Secret generated correctly")
        else:
            print("   [FAIL] Secret generation failed")
            return False
        
        # Test 2: Setup user MFA (includes backup codes and QR)
        print("\n2. Testing user MFA setup...")
        user_setup = mfa.setup_user_mfa("test_user")
        
        if 'secret' in user_setup and 'backup_codes' in user_setup and 'qr_code' in user_setup:
            print("   [PASS] User MFA setup works correctly")
        else:
            print("   [FAIL] User MFA setup failed")
            return False
        
        # Test 3: Generate TOTP token
        print("\n3. Testing TOTP token generation...")
        totp = pyotp.TOTP(secret)
        current_token = totp.now()
        
        if len(current_token) == 6:
            print("   [PASS] TOTP token generated correctly")
        else:
            print("   [FAIL] TOTP token generation failed")
            return False
        
        print("\n[PASS] All MFA manager tests passed")
        return True
        
    except Exception as e:
        print(f"   [ERROR] MFA manager test failed: {e}")
        return False


def test_input_validation():
    """Test input validation module."""
    print("\n=== Testing Input Validation ===")
    
    try:
        from input_validation import InputValidator
        
        # Test 1: Validate symbol
        print("\n1. Testing symbol validation...")
        validator = InputValidator()
        
        valid_symbol = validator.validate_symbol("EURUSD")
        print(f"   Valid symbol: {valid_symbol}")
        
        try:
            validator.validate_symbol("INVALID!SYMBOL")
            print("   [FAIL] Invalid symbol accepted")
            return False
        except:
            print("   [PASS] Invalid symbol rejected")
        
        # Test 2: Validate lots
        print("\n2. Testing lot validation...")
        valid_lots = validator.validate_lots(0.1, "EURUSD")
        print(f"   Valid lots: {valid_lots}")
        
        try:
            validator.validate_lots(-0.1, "EURUSD")
            print("   [FAIL] Negative lots accepted")
            return False
        except:
            print("   [PASS] Negative lots rejected")
        
        # Test 3: Validate price
        print("\n3. Testing price validation...")
        valid_price = validator.validate_price(1.0950, "EURUSD")
        print(f"   Valid price: {valid_price}")
        
        try:
            validator.validate_price(-1.0, "EURUSD")
            print("   [FAIL] Negative price accepted")
            return False
        except:
            print("   [PASS] Negative price rejected")
        
        # Test 4: Validate email
        print("\n4. Testing email validation...")
        valid_email = validator.validate_email("test@example.com")
        print(f"   Valid email: {valid_email}")
        
        try:
            validator.validate_email("invalid-email")
            print("   [FAIL] Invalid email accepted")
            return False
        except:
            print("   [PASS] Invalid email rejected")
        
        print("\n[PASS] All input validation tests passed")
        return True
        
    except Exception as e:
        print(f"   [ERROR] Input validation test failed: {e}")
        return False


def test_kill_switch():
    """Test kill switch module."""
    print("\n=== Testing Kill Switch ===")
    
    try:
        from kill_switch import KillSwitch, KillSwitchReason
        
        # Test 1: Initialize kill switch
        print("\n1. Testing kill switch initialization...")
        ks = KillSwitch()
        
        if not ks.is_activated():
            print("   [PASS] Kill switch initialized correctly")
        else:
            print("   [FAIL] Kill switch active on initialization")
            return False
        
        # Test 2: Activate kill switch
        print("\n2. Testing kill switch activation...")
        ks.activate(reason=KillSwitchReason.MANUAL, triggered_by="test_user")
        
        if ks.is_activated():
            print("   [PASS] Kill switch activated correctly")
        else:
            print("   [FAIL] Kill switch not activated")
            return False
        
        # Test 3: Check order blocking
        print("\n3. Testing order blocking...")
        if not ks.is_order_allowed("BUY", False):
            print("   [PASS] Orders blocked when kill switch active")
        else:
            print("   [FAIL] Orders not blocked")
            return False
        
        # Test 4: Check position closing allowed
        print("\n4. Testing position closing allowed...")
        if ks.is_order_allowed("SELL", True):  # True = position closing
            print("   [PASS] Position closing allowed")
        else:
            print("   [FAIL] Position closing not allowed")
            return False
        
        # Test 5: Deactivate kill switch
        print("\n5. Testing kill switch deactivation...")
        ks.deactivate(triggered_by="test_user")
        
        if not ks.is_activated():
            print("   [PASS] Kill switch deactivated correctly")
        else:
            print("   [FAIL] Kill switch not deactivated")
            return False
        
        # Test 6: Check order allowed
        print("\n6. Testing order allowed...")
        if ks.is_order_allowed("BUY", False):
            print("   [PASS] Orders allowed when kill switch inactive")
        else:
            print("   [FAIL] Orders not allowed")
            return False
        
        print("\n[PASS] All kill switch tests passed")
        return True
        
    except Exception as e:
        print(f"   [ERROR] Kill switch test failed: {e}")
        return False


def run_all_security_tests():
    """Run all security module tests."""
    print("="*60)
    print("RUNNING SECURITY MODULE UNIT TESTS")
    print("="*60)
    
    results = []
    
    results.append(("Secure Encryption", test_secure_encryption()))
    results.append(("Password Manager", test_password_manager()))
    results.append(("MFA Manager", test_mfa_manager()))
    results.append(("Input Validation", test_input_validation()))
    results.append(("Kill Switch", test_kill_switch()))
    
    print("\n" + "="*60)
    print("SECURITY TESTS SUMMARY")
    print("="*60)
    
    for name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"{status} {name}")
    
    all_passed = all(result[1] for result in results)
    
    print("="*60)
    if all_passed:
        print("[PASS] All security tests passed!")
        return 0
    else:
        print("[FAIL] Some security tests failed")
        return 1


if __name__ == '__main__':
    sys.exit(run_all_security_tests())
