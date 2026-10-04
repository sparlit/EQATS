"""
EQATS Credential Re-encryption Migration Script

This script helps migrate broker credentials from the legacy XOR-based encryption
to the new Fernet authenticated encryption system.

Usage:
    python migrate_credentials.py

Before running:
    1. Backup your database file (scalper_brain.db)
    2. Set EQATS_MASTER_KEY environment variable (recommended)
    3. Ensure cryptography library is installed: pip install cryptography

The script will:
    - Read all broker credentials (decrypting with legacy method if needed)
    - Re-save them using the new Fernet encryption
    - Verify the migration was successful
"""

import os
import shutil
import sys
from datetime import datetime
from typing import Any

try:
    import config
    import database
except ImportError:
    print("Error: Could not import database module. Run this script from the EQATS root directory.")
    sys.exit(1)


def backup_database() -> Any:
    """Create a backup of the database before migration."""
    db_path = config.DB_PATH
    if not os.path.exists(db_path):
        print(f"Database file not found: {db_path}")
        return False
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{db_path}.backup_{timestamp}"
    try:
        shutil.copy2(db_path, backup_path)
        print(f"✓ Database backed up to: {backup_path}")
        return True
    except Exception as e:
        print(f"✗ Failed to backup database: {e}")
        return False


def check_cryptography() -> Any:
    """Check if cryptography library is available."""
    try:
        from cryptography.fernet import Fernet

        print("✓ cryptography library is available")
        return True
    except ImportError:
        print("✗ cryptography library not found")
        print("  Install with: pip install cryptography")
        return False


def check_master_key() -> Any:
    """Check if EQATS_MASTER_KEY is set."""
    if os.environ.get("EQATS_MASTER_KEY"):
        print("✓ EQATS_MASTER_KEY environment variable is set")
        return True
    print("⚠ EQATS_MASTER_KEY environment variable is NOT set")
    print("  The system will use a machine-derived key as fallback")
    print("  For production, set EQATS_MASTER_KEY to a strong passphrase")
    response = input("  Continue anyway? (y/N): ")
    return response.lower() == "y"


def migrate_credentials() -> Any:
    """Migrate all broker credentials to new encryption."""
    print("\n" + "=" * 60)
    print("Starting credential migration...")
    print("=" * 60 + "\n")
    try:
        brokers = database.get_all_brokers()
        if not brokers:
            print("No broker credentials found in database.")
            return True
        print(f"Found {len(brokers)} broker credential(s) to migrate\n")
        for i, broker in enumerate(brokers, 1):
            broker_name = broker.get("broker_name", "Unknown")
            account_id = broker.get("account_id", "Unknown")
            print(f"[{i}/{len(brokers)}] Migrating: {broker_name} (Account: {account_id})")
            try:
                is_active = broker.get("is_active", 0)
                if is_active:
                    database.save_broker_credentials(
                        server=broker.get("server", ""),
                        account_id=broker.get("account_id", ""),
                        password=broker.get("password", ""),
                        leverage=broker.get("leverage", "1:100"),
                        broker_name=broker.get("broker_name", "Gateway"),
                        environment=broker.get("environment", "Demo"),
                        protocol_type=broker.get("protocol_type", "MT5"),
                        api_key=broker.get("api_key", ""),
                        api_secret=broker.get("api_secret", ""),
                        rest_url=broker.get("rest_url", ""),
                        ws_url=broker.get("ws_url", ""),
                        terminal_path=broker.get("terminal_path", ""),
                    )
                else:
                    database.delete_broker_account(broker["id"])
                    database.add_broker_account(
                        broker_name=broker.get("broker_name", "Gateway"),
                        server=broker.get("server", ""),
                        account_id=broker.get("account_id", ""),
                        password=broker.get("password", ""),
                        leverage=broker.get("leverage", "1:100"),
                        environment=broker.get("environment", "Demo"),
                        protocol_type=broker.get("protocol_type", "MT5"),
                        api_key=broker.get("api_key", ""),
                        api_secret=broker.get("api_secret", ""),
                        rest_url=broker.get("rest_url", ""),
                        ws_url=broker.get("ws_url", ""),
                        terminal_path=broker.get("terminal_path", ""),
                        is_active=0,
                    )
                print("    ✓ Successfully migrated")
            except Exception as e:
                print(f"    ✗ Failed to migrate: {e}")
                return False
        print("\n" + "=" * 60)
        print("Migration completed successfully!")
        print("=" * 60 + "\n")
        print("Verifying migration...")
        brokers_after = database.get_all_brokers()
        if len(brokers_after) == len(brokers):
            print(f"✓ All {len(brokers)} broker credential(s) verified")
            return True
        print(f"⚠ Warning: Broker count mismatch (before: {len(brokers)}, after: {len(brokers_after)})")
        return False
    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def main() -> Any:
    """Main migration workflow."""
    print("\n" + "=" * 60)
    print("EQATS Credential Re-encryption Migration")
    print("=" * 60 + "\n")
    print("Running pre-flight checks...\n")
    if not check_cryptography():
        return 1
    if not check_master_key():
        print("\nMigration cancelled by user.")
        return 1
    print("\nBacking up database...")
    if not backup_database():
        print("\nMigration cancelled due to backup failure.")
        return 1
    if not migrate_credentials():
        print("\n✗ Migration failed. Restore from backup if needed.")
        return 1
    print("\n✓ Migration completed successfully!")
    print("\nNext steps:")
    print("  1. Test your application to ensure credentials work")
    print("  2. If everything works, you can delete the backup file")
    print("  3. Keep the .salt file with your database")
    print("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
