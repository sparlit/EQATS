#!/usr/bin/env python3
"""
Test script to verify the password hashing security fix.

This script demonstrates:
1. New credentials use bcrypt hashing
2. Legacy SHA-256 hashes are still verified
3. Automatic migration from SHA-256 to bcrypt
4. Migration status monitoring
"""

import os
import sys
import tempfile

# Create temporary test database
test_db = tempfile.mktemp(suffix=".db")
os.environ.setdefault("DB_PATH", test_db)

import config

config.DB_PATH = test_db

import database


def test_bcrypt_availability():
    """Test 1: Verify bcrypt is available"""
    print("Test 1: Checking bcrypt availability...")
    if database._BCRYPT_AVAILABLE:
        print("  ✓ bcrypt is available - secure hashing enabled")
        print(
            f"  ✓ Using {database._BCRYPT_ROUNDS} rounds (2^{database._BCRYPT_ROUNDS} = {2**database._BCRYPT_ROUNDS} iterations)"
        )
    else:
        print("  ✗ bcrypt not available - using legacy SHA-256 (INSECURE)")
        print("  ! Install with: pip install bcrypt")
    print()


def test_new_user_creation():
    """Test 2: New users get bcrypt hashes"""
    print("Test 2: Creating new user with bcrypt...")
    database.init_db()

    # Create a test user
    database.add_user("test_user", "SecurePassword123!", "987654", role="QUANT_TRADER")

    # Check the hash format
    conn = database.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT password_hash, pin_hash FROM users WHERE username = ?", ("test_user",)
    )
    row = cursor.fetchone()
    conn.close()

    pwd_hash = row["password_hash"]
    pin_hash = row["pin_hash"]

    if database._BCRYPT_AVAILABLE:
        assert pwd_hash.startswith(
            "$2b$"
        ), f"Password hash should use bcrypt, got: {pwd_hash[:10]}"
        assert pin_hash.startswith(
            "$2b$"
        ), f"PIN hash should use bcrypt, got: {pin_hash[:10]}"
        print(f"  ✓ Password hash format: {pwd_hash[:29]}...")
        print(f"  ✓ PIN hash format: {pin_hash[:29]}...")
    else:
        print(f"  ! Using legacy SHA-256 (bcrypt not available)")
        print(f"  ! Password hash: {pwd_hash[:16]}...")
    print()


def test_password_verification():
    """Test 3: Password verification works"""
    print("Test 3: Testing password verification...")

    # Correct password
    assert database.verify_user_password(
        "test_user", "SecurePassword123!"
    ), "Correct password should verify"
    print("  ✓ Correct password verified")

    # Wrong password
    assert not database.verify_user_password(
        "test_user", "WrongPassword"
    ), "Wrong password should fail"
    print("  ✓ Wrong password rejected")

    # Correct credentials with PIN
    assert database.verify_user_credentials(
        "test_user", "SecurePassword123!", "987654"
    ), "Correct credentials should verify"
    print("  ✓ Correct password + PIN verified")

    # Wrong PIN
    assert not database.verify_user_credentials(
        "test_user", "SecurePassword123!", "000000"
    ), "Wrong PIN should fail"
    print("  ✓ Wrong PIN rejected")
    print()


def test_legacy_migration():
    """Test 4: Legacy SHA-256 hashes are migrated"""
    print("Test 4: Testing legacy hash migration...")

    # Manually insert a user with legacy SHA-256 hash
    legacy_pwd_hash = database.hash_credential("LegacyPassword123")
    legacy_pin_hash = database.hash_credential("123456")

    conn = database.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO users (username, password_hash, pin_hash, role, mfa_enabled, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
        ("legacy_user", legacy_pwd_hash, legacy_pin_hash, "QUANT_TRADER", 1),
    )
    conn.commit()
    conn.close()

    print(f"  ✓ Created legacy user with SHA-256 hash: {legacy_pwd_hash[:16]}...")

    # Verify with legacy hash (should work)
    assert database.verify_user_password(
        "legacy_user", "LegacyPassword123"
    ), "Legacy password should verify"
    print("  ✓ Legacy password verified successfully")

    # Check if hash was upgraded to bcrypt
    conn = database.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT password_hash FROM users WHERE username = ?", ("legacy_user",)
    )
    row = cursor.fetchone()
    conn.close()

    new_hash = row["password_hash"]
    if database._BCRYPT_AVAILABLE:
        assert new_hash.startswith("$2b$"), "Hash should be upgraded to bcrypt"
        assert new_hash != legacy_pwd_hash, "Hash should be different after upgrade"
        print(f"  ✓ Password automatically upgraded to bcrypt: {new_hash[:29]}...")
    else:
        print("  ! Migration skipped (bcrypt not available)")

    # Verify password still works after migration
    assert database.verify_user_password(
        "legacy_user", "LegacyPassword123"
    ), "Password should still work after migration"
    print("  ✓ Password still works after migration")
    print()


def test_migration_status():
    """Test 5: Migration status monitoring"""
    print("Test 5: Checking migration status...")

    status = database.get_credential_migration_status()

    print(f"  Total users: {status['total_users']}")
    print(f"  Bcrypt passwords: {status['bcrypt_passwords']}")
    print(f"  Legacy passwords: {status['legacy_passwords']}")
    print(f"  Bcrypt PINs: {status['bcrypt_pins']}")
    print(f"  Legacy PINs: {status['legacy_pins']}")
    print(f"  Migration complete: {status['migration_complete']}")

    if database._BCRYPT_AVAILABLE:
        # After migration, legacy_user should have bcrypt password but legacy PIN
        assert (
            status["bcrypt_passwords"] >= 2
        ), "Should have at least 2 bcrypt passwords"
        assert (
            status["legacy_pins"] >= 1
        ), "Should have at least 1 legacy PIN (not yet logged in with PIN)"
    print()


def test_unique_salts():
    """Test 6: Identical passwords produce different hashes"""
    print("Test 6: Testing unique per-credential salts...")

    # Create two users with the same password
    database.add_user("user1", "SamePassword123", "111111", role="QUANT_TRADER")
    database.add_user("user2", "SamePassword123", "111111", role="QUANT_TRADER")

    # Get their hashes
    conn = database.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT password_hash, pin_hash FROM users WHERE username IN ('user1', 'user2')"
    )
    rows = cursor.fetchall()
    conn.close()

    hash1_pwd = rows[0]["password_hash"]
    hash2_pwd = rows[1]["password_hash"]
    hash1_pin = rows[0]["pin_hash"]
    hash2_pin = rows[1]["pin_hash"]

    if database._BCRYPT_AVAILABLE:
        assert (
            hash1_pwd != hash2_pwd
        ), "Identical passwords should produce different hashes"
        assert hash1_pin != hash2_pin, "Identical PINs should produce different hashes"
        print(
            "  ✓ Identical passwords produce unique hashes (per-credential salts working)"
        )
        print(f"    User1 password: {hash1_pwd[:29]}...")
        print(f"    User2 password: {hash2_pwd[:29]}...")
    else:
        assert (
            hash1_pwd == hash2_pwd
        ), "Legacy SHA-256 produces same hash for same password"
        print("  ! Legacy SHA-256 produces identical hashes (no per-credential salt)")
    print()


def cleanup():
    """Clean up test database"""
    try:
        if os.path.exists(test_db):
            os.remove(test_db)
        salt_file = test_db + ".salt"
        if os.path.exists(salt_file):
            os.remove(salt_file)
    except Exception as e:
        print(f"Warning: Could not clean up test files: {e}")


def main():
    print("=" * 70)
    print("Password Hashing Security Fix - Test Suite")
    print("=" * 70)
    print()

    try:
        test_bcrypt_availability()
        test_new_user_creation()
        test_password_verification()
        test_legacy_migration()
        test_migration_status()
        test_unique_salts()

        print("=" * 70)
        print("✓ All tests passed!")
        print("=" * 70)

        if not database._BCRYPT_AVAILABLE:
            print()
            print("WARNING: bcrypt is not available. Install it for production use:")
            print("  pip install bcrypt")

        return 0

    except AssertionError as e:
        print()
        print("=" * 70)
        print(f"✗ Test failed: {e}")
        print("=" * 70)
        return 1

    except Exception as e:
        print()
        print("=" * 70)
        print(f"✗ Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        print("=" * 70)
        return 1

    finally:
        cleanup()


if __name__ == "__main__":
    sys.exit(main())
