#!/usr/bin/env python3
"""
Test MFA Implementation
"""

from mfa_manager import get_mfa_manager

def test_mfa():
    """Test MFA functionality."""
    print("Testing MFA implementation...")
    
    mfa = get_mfa_manager()
    
    # Test 1: Setup MFA for user
    print("\n1. Setting up MFA for testuser...")
    data = mfa.setup_user_mfa('testuser')
    print(f"   Secret: {data['secret']}")
    print(f"   QR code length: {len(data['qr_code'])}")
    print(f"   Backup codes: {len(data['backup_codes'])}")
    print(f"   Issuer: {data['issuer']}")
    
    # Test 2: Get current token
    print("\n2. Getting current token...")
    token = mfa.get_current_token('testuser')
    print(f"   Current token: {token}")
    
    # Test 3: Verify token
    print("\n3. Verifying token...")
    verified = mfa.verify_token('testuser', token)
    print(f"   Token verification: {'PASS' if verified else 'FAIL'}")
    
    # Test 4: Verify wrong token
    print("\n4. Verifying wrong token...")
    wrong_verified = mfa.verify_token('testuser', '000000')
    print(f"   Wrong token rejected: {'PASS' if not wrong_verified else 'FAIL'}")
    
    # Test 5: Verify backup code
    print("\n5. Verifying backup code...")
    backup_code = data['backup_codes'][0]
    backup_verified = mfa.verify_backup_code('testuser', backup_code)
    print(f"   Backup code verification: {'PASS' if backup_verified else 'FAIL'}")
    
    # Test 6: Check MFA enabled
    print("\n6. Checking MFA enabled...")
    enabled = mfa.is_mfa_enabled('testuser')
    print(f"   MFA enabled: {'PASS' if enabled else 'FAIL'}")
    
    # Test 7: Disable MFA
    print("\n7. Disabling MFA...")
    mfa.disable_user_mfa('testuser')
    enabled_after = mfa.is_mfa_enabled('testuser')
    print(f"   MFA disabled: {'PASS' if not enabled_after else 'FAIL'}")
    
    # Summary
    all_passed = verified and not wrong_verified and backup_verified and enabled and not enabled_after
    print(f"\n{'='*60}")
    if all_passed:
        print("[PASS] All MFA tests passed!")
        # Clean test exit
    else:
        print("[FAIL] Some MFA tests failed!")
        assert False, "Test condition failed"

if __name__ == '__main__':
    import sys
    sys.exit(test_mfa())
