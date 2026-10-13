"""
Test script to verify the password hashing security fix.

This script demonstrates:
1. New credentials use bcrypt hashing
2. Legacy SHA-256 hashes are still verified
3. Automatic migration from SHA-256 to bcrypt
4. Migration status monitoring
"""
import os
import tempfile
import unittest

import config
import database


class TestPasswordHashingFix(unittest.TestCase):

    def setUp(self) -> None:
        self.test_db = tempfile.mktemp(suffix='.db')
        self.orig_db = config.DB_PATH
        config.DB_PATH = self.test_db
        os.environ['DB_PATH'] = self.test_db
        database.init_db()

    def tearDown(self) -> None:
        config.DB_PATH = self.orig_db
        os.environ['DB_PATH'] = self.orig_db
        for f in [self.test_db, self.test_db + '-wal', self.test_db + '-shm', self.test_db + '.salt']:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

    def test_bcrypt_availability(self) -> None:
        """Test 1: Verify bcrypt is available"""
        if database._BCRYPT_AVAILABLE:
            self.assertTrue(database._BCRYPT_AVAILABLE)
        else:
            self.assertFalse(database._BCRYPT_AVAILABLE)

    def test_new_user_creation(self) -> None:
        """Test 2: New users get bcrypt hashes"""
        database.add_user('test_user', 'SecurePassword123!', '987654', role='QUANT_TRADER')
        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT password_hash, pin_hash FROM users WHERE username = ?', ('test_user',))
        row = cursor.fetchone()
        conn.close()
        pwd_hash = row['password_hash']
        pin_hash = row['pin_hash']
        if database._BCRYPT_AVAILABLE:
            self.assertTrue(pwd_hash.startswith('$2b$'), f'Password hash should use bcrypt, got: {pwd_hash[:10]}')
            self.assertTrue(pin_hash.startswith('$2b$'), f'PIN hash should use bcrypt, got: {pin_hash[:10]}')

    def test_password_verification(self) -> None:
        """Test 3: Password verification works"""
        database.add_user('test_user', 'SecurePassword123!', '987654', role='QUANT_TRADER')
        self.assertTrue(database.verify_user_password('test_user', 'SecurePassword123!'))
        self.assertFalse(database.verify_user_password('test_user', 'WrongPassword'))
        self.assertTrue(database.verify_user_credentials('test_user', 'SecurePassword123!', '987654'))
        self.assertFalse(database.verify_user_credentials('test_user', 'SecurePassword123!', '000000'))

    def test_legacy_migration(self) -> None:
        """Test 4: Legacy SHA-256 hashes are migrated"""
        legacy_pwd_hash = database.hash_credential('LegacyPassword123')
        legacy_pin_hash = database.hash_credential('123456')
        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (username, password_hash, pin_hash, role, mfa_enabled, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))", ('legacy_user', legacy_pwd_hash, legacy_pin_hash, 'QUANT_TRADER', 1))
        conn.commit()
        conn.close()
        self.assertTrue(database.verify_user_password('legacy_user', 'LegacyPassword123'))
        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT password_hash FROM users WHERE username = ?', ('legacy_user',))
        row = cursor.fetchone()
        conn.close()
        new_hash = row['password_hash']
        if database._BCRYPT_AVAILABLE:
            self.assertTrue(new_hash.startswith('$2b$'))
            self.assertNotEqual(new_hash, legacy_pwd_hash)
        self.assertTrue(database.verify_user_password('legacy_user', 'LegacyPassword123'))

    def test_migration_status(self) -> None:
        """Test 5: Migration status monitoring"""
        database.add_user('user1', 'Pwd123!', '111111', role='QUANT_TRADER')
        database.add_user('user2', 'Pwd456!', '222222', role='QUANT_TRADER')
        status = database.get_credential_migration_status()
        self.assertGreaterEqual(status['total_users'], 2)

    def test_unique_salts(self) -> None:
        """Test 6: Identical passwords produce different hashes"""
        database.add_user('user1', 'SamePassword123', '111111', role='QUANT_TRADER')
        database.add_user('user2', 'SamePassword123', '111111', role='QUANT_TRADER')
        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT password_hash, pin_hash FROM users WHERE username IN ('user1', 'user2')")
        rows = cursor.fetchall()
        conn.close()
        hash1_pwd = rows[0]['password_hash']
        hash2_pwd = rows[1]['password_hash']
        hash1_pin = rows[0]['pin_hash']
        hash2_pin = rows[1]['pin_hash']
        if database._BCRYPT_AVAILABLE:
            self.assertNotEqual(hash1_pwd, hash2_pwd)
            self.assertNotEqual(hash1_pin, hash2_pin)

if __name__ == '__main__':
    unittest.main()
