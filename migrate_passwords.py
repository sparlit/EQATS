#!/usr/bin/env python3
"""
Password Hashing Migration Script
Migrates user passwords and PINs from SHA-256 to bcrypt.
"""

import os
import sys
import sqlite3
from dotenv import load_dotenv
from password_manager import get_password_manager, get_pin_manager

# Load environment variables
load_dotenv()


def migrate_user_passwords(db_path: str, old_salt: str):
    """
    Migrate user passwords from SHA-256 to bcrypt.
    
    Args:
        db_path: Path to the SQLite database
        old_salt: The old salt used for SHA-256 hashing
    """
    print(f"Migrating user passwords in {db_path}...")
    
    # Initialize password managers
    password_manager = get_password_manager()
    pin_manager = get_pin_manager()
    
    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get all users
    cursor.execute("SELECT id, username, password_hash, pin_hash FROM users")
    rows = cursor.fetchall()
    
    if not rows:
        print("No users found to migrate")
        conn.close()
        return True
    
    migrated_passwords = 0
    migrated_pins = 0
    failed_passwords = 0
    failed_pins = 0
    
    for row in rows:
        user_id, username, old_password_hash, old_pin_hash = row
        
        # Verify if we can decrypt/migrate the old hash
        # For SHA-256, we can't directly migrate without the original password
        # So we'll need to ask users to reset their passwords
        
        print(f"  [INFO] User: {username} (ID: {user_id})")
        print(f"         Password hash: {old_password_hash[:20]}...")
        print(f"         PIN hash: {old_pin_hash[:20]}...")
        print(f"         Action: Password reset required (cannot migrate from SHA-256)")
        
        # Set a temporary flag that password needs reset
        cursor.execute(
            "UPDATE users SET role = ? WHERE id = ?",
            (f"PASSWORD_RESET_REQUIRED|{{cursor.fetchone()[4]}}", user_id)
        )
    
    conn.commit()
    conn.close()
    
    print(f"\nPassword migration requires user action:")
    print(f"  - SHA-256 cannot be reversed to get original passwords")
    print(f"  - Users will need to reset their passwords")
    print(f"  - New passwords will be hashed with bcrypt")
    
    return True


def create_migration_instructions():
    """Create instructions for users to reset passwords."""
    instructions = """
# Password Reset Instructions

Due to the security upgrade from SHA-256 to bcrypt hashing,
all users need to reset their passwords.

## Why is this necessary?

SHA-256 is a fast hashing algorithm that is vulnerable to:
- Rainbow table attacks
- Brute force attacks with modern hardware
- GPU-accelerated cracking

Bcrypt is a slow, adaptive hashing algorithm designed specifically for passwords:
- Automatically includes salt
- Resistant to rainbow table attacks
- Can increase computational cost as hardware improves
- Widely recommended by security experts (NIST, OWASP)

## How to reset your password:

1. Log in with your username and PIN
2. The system will prompt you to create a new password
3. Choose a strong password (12+ characters, mixed case, numbers, symbols)
4. Your new password will be hashed with bcrypt

## Password Requirements:

- Minimum 8 characters (12+ recommended)
- At least one uppercase letter
- At least one lowercase letter
- At least one digit
- At least one special character (!@#$%^&*)
- Not a common password (password, 12345678, qwerty, etc.)

## Security Benefits:

- Bcrypt hashes are much harder to crack
- Automatic salting prevents rainbow table attacks
- Slower hashing prevents brute force attacks
- Meets modern security standards
"""
    
    with open('PASSWORD_RESET_INSTRUCTIONS.md', 'w') as f:
        f.write(instructions)
    
    print("Created PASSWORD_RESET_INSTRUCTIONS.md")


def test_bcrypt_hashing():
    """Test that bcrypt hashing works correctly."""
    print("\nTesting bcrypt password hashing...")
    
    try:
        password_manager = get_password_manager()
        pin_manager = get_pin_manager()
        
        # Test password
        test_password = "TestPassword123!"
        hashed = password_manager.hash_password(test_password)
        print(f"  Password hash: {hashed[:40]}...")
        
        verified = password_manager.verify_password(test_password, hashed)
        print(f"  Password verification: {'PASS' if verified else 'FAIL'}")
        
        # Test PIN
        test_pin = "123456"
        pin_hashed = pin_manager.hash_pin(test_pin)
        print(f"  PIN hash: {pin_hashed[:40]}...")
        
        pin_verified = pin_manager.verify_pin(test_pin, pin_hashed)
        print(f"  PIN verification: {'PASS' if pin_verified else 'FAIL'}")
        
        # Test wrong password
        wrong_verified = password_manager.verify_password("WrongPassword", hashed)
        print(f"  Wrong password rejected: {'PASS' if not wrong_verified else 'FAIL'}")
        
        # Test strong password generation
        strong_password = password_manager.generate_strong_password(16)
        print(f"  Generated password: {strong_password}")
        
        strength = password_manager.check_password_strength(strong_password)
        print(f"  Password strength: {strength['score']}/5, Strong: {strength['strong']}")
        
        return verified and pin_verified and not wrong_verified
        
    except Exception as e:
        print(f"  [FAIL] Bcrypt test failed: {e}")
        return False


def main():
    print("=" * 60)
    print("PASSWORD HASHING MIGRATION TOOL")
    print("=" * 60)
    print()
    
    # Test bcrypt hashing
    if not test_bcrypt_hashing():
        print("\nERROR: Bcrypt hashing test failed. Aborting migration.")
        return 1
    
    # Check database path
    db_path = os.getenv('DB_PATH', 'scalper_brain.db')
    if not os.path.exists(db_path):
        print(f"\nWARNING: Database not found at {db_path}")
        print("No migration needed.")
        return 0
    
    print(f"\nDatabase found at: {db_path}")
    
    # Check for old salt
    old_salt = os.getenv('SALT')
    if not old_salt:
        print("\nWARNING: SALT environment variable not set")
        print("Using default old salt for reference: EAQTS_SOVEREIGN_SALT_2026")
        old_salt = "EAQTS_SOVEREIGN_SALT_2026"
    
    print(f"Old salt: {old_salt[:20]}...")
    
    # Perform migration
    print()
    success = migrate_user_passwords(db_path, old_salt)
    
    # Create user instructions
    create_migration_instructions()
    
    if success:
        print("\n[SUCCESS] Migration setup complete!")
        print("Please review PASSWORD_RESET_INSTRUCTIONS.md")
        print("Users will need to reset their passwords on next login.")
        return 0
    else:
        print("\n[WARNING] Migration completed with warnings.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
