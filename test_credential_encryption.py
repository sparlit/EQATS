#!/usr/bin/env python3
"""
Test script to verify the new Fernet encryption implementation.

This script tests:
1. Encryption and decryption of credentials
2. Backward compatibility with legacy XOR encryption
3. Environment variable key derivation
4. Salt file generation and persistence
"""

import os
import sys
import tempfile

# Test with a temporary database
import config

test_db = tempfile.mktemp(suffix=".db")
config.DB_PATH = test_db

import database


def test_fernet_encryption():
    """Test basic Fernet encryption and decryption."""
    print("Test 1: Fernet Encryption/Decryption")

    test_password = "MySecurePassword123!"
    test_api_key = "sk_test_1234567890abcdef"
    test_api_secret = "secret_abcdefghijklmnop"

    # Encrypt
    enc_password = database.encrypt_secret(test_password)
    enc_api_key = database.encrypt_secret(test_api_key)
    enc_api_secret = database.encrypt_secret(test_api_secret)

    print(f"  Original password: {test_password}")
    print(f"  Encrypted: {enc_password[:50]}...")

    # Decrypt
    dec_password = database.decrypt_secret(enc_password)
    dec_api_key = database.decrypt_secret(enc_api_key)
    dec_api_secret = database.decrypt_secret(enc_api_secret)

    # Verify
    assert dec_password == test_password, "Password decryption failed"
    assert dec_api_key == test_api_key, "API key decryption failed"
    assert dec_api_secret == test_api_secret, "API secret decryption failed"

    print("  ✓ Encryption/Decryption successful\n")


def test_legacy_compatibility():
    """Test backward compatibility with legacy XOR encryption."""
    print("Test 2: Legacy XOR Compatibility")

    test_text = "LegacyPassword123"

    # Encrypt with legacy method
    legacy_encrypted = database._legacy_encrypt_secret(test_text)
    print(f"  Legacy encrypted: {legacy_encrypted}")

    # Decrypt with new method (should fall back to legacy)
    decrypted = database.decrypt_secret(legacy_encrypted)

    assert decrypted == test_text, "Legacy decryption failed"
    print("  ✓ Legacy compatibility verified\n")


def test_empty_strings():
    """Test handling of empty strings."""
    print("Test 3: Empty String Handling")

    assert database.encrypt_secret("") == "", "Empty string encryption failed"
    assert database.decrypt_secret("") == "", "Empty string decryption failed"
    assert database.encrypt_secret(None) == "", "None encryption failed"

    print("  ✓ Empty string handling correct\n")


def test_database_operations():
    """Test full database operations with encryption."""
    print("Test 4: Database Operations")

    # Initialize database
    database.init_db()

    # Add broker with credentials
    database.add_broker_account(
        broker_name="Test Broker",
        server="test.server.com",
        account_id="12345",
        password="TestPassword123!",
        api_key="test_api_key_xyz",
        api_secret="test_api_secret_abc",
        leverage="1:100",
        environment="Demo",
        is_active=1,
    )

    # Retrieve credentials
    creds = database.get_broker_credentials()

    # Verify decryption
    assert creds["password"] == "TestPassword123!", "Password retrieval failed"
    assert creds["api_key"] == "test_api_key_xyz", "API key retrieval failed"
    assert creds["api_secret"] == "test_api_secret_abc", "API secret retrieval failed"

    print("  ✓ Database operations successful\n")


def test_salt_persistence():
    """Test that salt file is created and persisted."""
    print("Test 5: Salt File Persistence")

    salt_file = config.DB_PATH + ".salt"

    # Force key generation
    database._ENCRYPTION_KEY = None
    database._ENCRYPTION_SALT = None
    key1 = database._get_encryption_key()

    # Check salt file exists
    assert os.path.exists(salt_file), "Salt file not created"

    # Read salt
    with open(salt_file, "rb") as f:
        salt_content = f.read()

    assert len(salt_content) == 32, "Salt file has incorrect size"

    # Generate key again - should use same salt
    database._ENCRYPTION_KEY = None
    key2 = database._get_encryption_key()

    assert key1 == key2, "Key derivation not consistent"

    print("  ✓ Salt persistence verified\n")


def test_environment_variable():
    """Test key derivation from environment variable."""
    print("Test 6: Environment Variable Key Derivation")

    # Set custom master key
    os.environ["EQATS_MASTER_KEY"] = "CustomTestKey123456789"

    # Force key regeneration
    database._ENCRYPTION_KEY = None
    database._ENCRYPTION_SALT = None

    # Encrypt with custom key
    test_text = "TestWithCustomKey"
    encrypted = database.encrypt_secret(test_text)
    decrypted = database.decrypt_secret(encrypted)

    assert decrypted == test_text, "Custom key encryption failed"

    # Clean up
    del os.environ["EQATS_MASTER_KEY"]
    database._ENCRYPTION_KEY = None

    print("  ✓ Environment variable key derivation successful\n")


def cleanup():
    """Clean up test files."""
    try:
        if os.path.exists(test_db):
            os.remove(test_db)
        salt_file = test_db + ".salt"
        if os.path.exists(salt_file):
            os.remove(salt_file)
    except Exception as e:
        print(f"Warning: Could not clean up test files: {e}")


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("EQATS Credential Encryption Test Suite")
    print("=" * 60 + "\n")

    try:
        test_fernet_encryption()
        test_legacy_compatibility()
        test_empty_strings()
        test_database_operations()
        test_salt_persistence()
        test_environment_variable()

        print("=" * 60)
        print("✓ All tests passed!")
        print("=" * 60 + "\n")

        return 0

    except AssertionError as e:
        print(f"\n✗ Test failed: {e}\n")
        return 1
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}\n")
        import traceback

        traceback.print_exc()
        return 1
    finally:
        cleanup()


if __name__ == "__main__":
    sys.exit(main())
