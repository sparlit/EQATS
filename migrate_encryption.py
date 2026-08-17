#!/usr/bin/env python3
"""
Encryption Migration Script
Migrates data from old XOR encryption to new AES-256-GCM encryption.
"""

import os
import sys
import sqlite3
from dotenv import load_dotenv
from secure_encryption import SecureEncryption

# Load environment variables
load_dotenv()


def migrate_broker_credentials(db_path: str, old_key_seed: str):
    """
    Migrate broker credentials from XOR encryption to AES-256-GCM.
    
    Args:
        db_path: Path to the SQLite database
        old_key_seed: The old key seed used for XOR encryption
    """
    print(f"Migrating broker credentials in {db_path}...")
    
    # Initialize new encryption manager
    try:
        new_encryption = SecureEncryption()
    except ValueError as e:
        print(f"ERROR: Failed to initialize encryption: {e}")
        return False
    
    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get all broker credentials
    cursor.execute("SELECT id, broker_name, server, account_id, password_encrypted FROM broker_credentials")
    rows = cursor.fetchall()
    
    if not rows:
        print("No broker credentials found to migrate")
        conn.close()
        return True
    
    migrated_count = 0
    failed_count = 0
    
    for row in rows:
        broker_id, broker_name, server, account_id, old_encrypted = row
        
        try:
            # Re-encrypt using new AES-256-GCM
            new_encrypted = new_encryption.reencrypt_from_xor(old_encrypted, old_key_seed)
            
            # Update database
            cursor.execute(
                "UPDATE broker_credentials SET password_encrypted = ? WHERE id = ?",
                (new_encrypted, broker_id)
            )
            
            print(f"  [SUCCESS] Migrated {broker_name} (ID: {broker_id})")
            migrated_count += 1
            
        except Exception as e:
            print(f"  [FAILED] Failed to migrate {broker_name} (ID: {broker_id}): {e}")
            failed_count += 1
    
    # Commit changes
    conn.commit()
    conn.close()
    
    print(f"\nMigration complete:")
    print(f"  Successfully migrated: {migrated_count}")
    print(f"  Failed: {failed_count}")
    
    return failed_count == 0


def test_encryption():
    """Test that the new encryption works correctly."""
    print("\nTesting AES-256-GCM encryption...")
    
    try:
        encryption = SecureEncryption()
        
        # Test data
        test_plaintext = "TestPassword123!"
        
        # Encrypt
        encrypted = encryption.encrypt(test_plaintext)
        print(f"  Encrypted: {encrypted[:20]}...")
        
        # Decrypt
        decrypted = encryption.decrypt(encrypted)
        print(f"  Decrypted: {decrypted}")
        
        # Verify
        if decrypted == test_plaintext:
            print("  [SUCCESS] Encryption/decryption test passed")
            return True
        else:
            print("  [FAILED] Decryption mismatch")
            return False
            
    except Exception as e:
        print(f"  [FAILED] Encryption test failed: {e}")
        return False


def main():
    print("=" * 60)
    print("ENCRYPTION MIGRATION TOOL")
    print("=" * 60)
    print()
    
    # Check if ENCRYPTION_KEY is set
    encryption_key = os.getenv('ENCRYPTION_KEY')
    if not encryption_key:
        print("ERROR: ENCRYPTION_KEY environment variable not set")
        print("Please set it in your .env file")
        return 1
    
    print(f"ENCRYPTION_KEY is set (length: {len(encryption_key)} characters)")
    
    # Test encryption
    if not test_encryption():
        print("\nERROR: Encryption test failed. Aborting migration.")
        return 1
    
    # Check database path
    db_path = os.getenv('DB_PATH', 'scalper_brain.db')
    if not os.path.exists(db_path):
        print(f"\nWARNING: Database not found at {db_path}")
        print("No migration needed.")
        return 0
    
    print(f"\nDatabase found at: {db_path}")
    
    # Ask for old key seed for migration
    print("\nTo migrate existing XOR-encrypted data, you need the old key seed.")
    print("The old default was: EAQTS_CIPHER_KEY_2026")
    print("If you used a custom key, enter it now.")
    print("If you skip migration, existing encrypted data will become unreadable.")
    
    old_key_seed = input("\nEnter old key seed (or press Enter to skip migration): ").strip()
    
    if not old_key_seed:
        print("\nSKIPPING migration. Existing encrypted data will not be accessible.")
        print("You will need to re-enter all credentials.")
        return 0
    
    # Perform migration
    print()
    success = migrate_broker_credentials(db_path, old_key_seed)
    
    if success:
        print("\n[SUCCESS] Migration completed successfully!")
        print("Your data is now encrypted with AES-256-GCM.")
        return 0
    else:
        print("\n[WARNING] Migration completed with some failures.")
        print("Please check the messages above.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
