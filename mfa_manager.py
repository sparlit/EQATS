"""
Multi-Factor Authentication Module
Implements TOTP-based (Time-based One-Time Password) two-factor authentication.
"""

import pyotp
import qrcode
import io
import base64
from typing import Optional, Dict
from dataclasses import dataclass
import secrets


@dataclass
class MFAConfig:
    """Configuration for MFA settings."""
    enabled: bool = True
    issuer: str = "ForexScalper"
    token_length: int = 6
    interval: int = 30  # TOTP refresh interval in seconds
    backup_codes_count: int = 10


class MFAManager:
    """
    Multi-Factor Authentication Manager using TOTP (Time-based One-Time Password).
    
    Implements RFC 6238 TOTP standard compatible with Google Authenticator,
    Authy, Microsoft Authenticator, and other 2FA apps.
    """
    
    def __init__(self, config: Optional[MFAConfig] = None):
        """
        Initialize the MFA manager.
        
        Args:
            config: MFA configuration (uses defaults if not provided)
        """
        self.config = config or MFAConfig()
        self._secrets: Dict[str, str] = {}  # username -> secret key mapping
        self._backup_codes: Dict[str, list] = {}  # username -> backup codes
        self._verified_tokens: Dict[str, set] = {}  # username -> used backup codes
        
        # Initialize verified_tokens for new users
        self._verified_tokens = {}
    
    def generate_secret(self) -> str:
        """
        Generate a new random secret key for TOTP.
        
        Returns:
            Base32-encoded secret key (typically 16-32 characters)
        """
        return pyotp.random_base32()
    
    def setup_user_mfa(self, username: str) -> Dict:
        """
        Set up MFA for a user by generating a secret and QR code.
        
        Args:
            username: The username to set up MFA for
            
        Returns:
            Dictionary containing:
            - secret: The secret key (keep this secure!)
            - qr_code: Base64-encoded QR code image
            - backup_codes: List of backup codes
            - issuer: The issuer name
        """
        # Generate secret
        secret = self.generate_secret()
        self._secrets[username] = secret
        
        # Generate TOTP object
        totp = pyotp.TOTP(secret)
        
        # Generate provisioning URI for QR code
        provisioning_uri = totp.provisioning_uri(
            name=username,
            issuer_name=self.config.issuer
        )
        
        # Generate QR code
        qr = qrcode.make(provisioning_uri)
        buffer = io.BytesIO()
        qr.save(buffer, format='PNG')
        qr_code_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        # Generate backup codes
        backup_codes = self._generate_backup_codes(self.config.backup_codes_count)
        self._backup_codes[username] = backup_codes
        
        return {
            'secret': secret,
            'qr_code': f"data:image/png;base64,{qr_code_base64}",
            'provisioning_uri': provisioning_uri,
            'backup_codes': backup_codes,
            'issuer': self.config.issuer,
            'token_length': self.config.token_length,
            'interval': self.config.interval
        }
    
    def _generate_backup_codes(self, count: int) -> list:
        """
        Generate one-time backup codes for account recovery.
        
        Args:
            count: Number of backup codes to generate
            
        Returns:
            List of backup code strings
        """
        codes = []
        for _ in range(count):
            # Generate 8-character alphanumeric codes
            code = ''.join(secrets.choice('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ') for _ in range(8))
            codes.append(code)
        return codes
    
    def verify_token(self, username: str, token: str, valid_window: int = 1) -> bool:
        """
        Verify a TOTP token for a user.
        
        Args:
            username: The username to verify the token for
            token: The TOTP token to verify
            valid_window: Number of time steps to allow (for clock skew)
            
        Returns:
            True if token is valid, False otherwise
        """
        if username not in self._secrets:
            return False
        
        secret = self._secrets[username]
        totp = pyotp.TOTP(secret)
        
        try:
            return totp.verify(token, valid_window=valid_window)
        except Exception:
            return False
    
    def verify_backup_code(self, username: str, backup_code: str) -> bool:
        """
        Verify a backup code for a user.
        
        Args:
            username: The username to verify the backup code for
            backup_code: The backup code to verify
            
        Returns:
            True if backup code is valid and not used, False otherwise
        """
        if username not in self._backup_codes:
            return False
        
        if backup_code not in self._backup_codes[username]:
            return False
        
        # Initialize verified_tokens set if not exists
        if username not in self._verified_tokens:
            self._verified_tokens[username] = set()
        
        if backup_code in self._verified_tokens[username]:
            # Backup code already used
            return False
        
        # Mark as used
        self._verified_tokens[username].add(backup_code)
        return True
    
    def get_current_token(self, username: str) -> str:
        """
        Get the current valid TOTP token for a user (for testing).
        
        Args:
            username: The username to get the token for
            
        Returns:
            Current TOTP token
        """
        if username not in self._secrets:
            raise ValueError(f"MFA not set up for user: {username}")
        
        secret = self._secrets[username]
        totp = pyotp.TOTP(secret)
        return totp.now()
    
    def disable_user_mfa(self, username: str):
        """
        Disable MFA for a user (removes secret and backup codes).
        
        Args:
            username: The username to disable MFA for
        """
        if username in self._secrets:
            del self._secrets[username]
        if username in self._backup_codes:
            del self._backup_codes[username]
        if username in self._verified_tokens:
            del self._verified_tokens[username]
    
    def is_mfa_enabled(self, username: str) -> bool:
        """
        Check if MFA is enabled for a user.
        
        Args:
            username: The username to check
            
        Returns:
            True if MFA is enabled, False otherwise
        """
        return username in self._secrets
    
    def regenerate_backup_codes(self, username: str) -> list:
        """
        Regenerate backup codes for a user (invalidates old ones).
        
        Args:
            username: The username to regenerate codes for
            
        Returns:
            New list of backup codes
        """
        if username not in self._secrets:
            raise ValueError(f"MFA not set up for user: {username}")
        
        # Generate new codes
        new_codes = self._generate_backup_codes(self.config.backup_codes_count)
        self._backup_codes[username] = new_codes
        self._verified_tokens[username] = set()  # Clear used codes
        
        return new_codes
    
    def get_remaining_backup_codes(self, username: str) -> int:
        """
        Get the number of remaining (unused) backup codes for a user.
        
        Args:
            username: The username to check
            
        Returns:
            Number of remaining backup codes
        """
        if username not in self._backup_codes:
            return 0
        
        used_count = len(self._verified_tokens.get(username, set()))
        total_count = len(self._backup_codes[username])
        
        return total_count - used_count


class MFADatabaseStorage:
    """
    Database storage for MFA secrets and backup codes.
    Stores encrypted secrets in the database.
    """
    
    def __init__(self, db_path: str):
        """
        Initialize MFA database storage.
        
        Args:
            db_path: Path to the SQLite database
        """
        self.db_path = db_path
        self._init_tables()
    
    def _init_tables(self):
        """Initialize MFA-related database tables."""
        import sqlite3
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Table for MFA secrets (encrypted)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS mfa_secrets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            secret_encrypted TEXT NOT NULL,
            issuer TEXT DEFAULT 'ForexScalper',
            created_at TEXT NOT NULL,
            last_used_at TEXT
        )
        """)
        
        # Table for backup codes (hashed)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS mfa_backup_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            code_hash TEXT NOT NULL,
            used INTEGER DEFAULT 0,
            used_at TEXT,
            created_at TEXT NOT NULL
        )
        """)
        
        conn.commit()
        conn.close()
    
    def save_mfa_secret(self, username: str, secret: str, issuer: str = 'ForexScalper'):
        """
        Save an MFA secret for a user (encrypted).
        
        Args:
            username: The username
            secret: The TOTP secret key
            issuer: The issuer name
        """
        from secure_encryption import encrypt_text
        import datetime
        
        encrypted_secret = encrypt_text(secret)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
        INSERT OR REPLACE INTO mfa_secrets (username, secret_encrypted, issuer, created_at)
        VALUES (?, ?, ?, ?)
        """, (username, encrypted_secret, issuer, datetime.datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
    
    def load_mfa_secret(self, username: str) -> Optional[str]:
        """
        Load an MFA secret for a user (decrypted).
        
        Args:
            username: The username
            
        Returns:
            The secret key, or None if not found
        """
        from secure_encryption import decrypt_text
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT secret_encrypted FROM mfa_secrets WHERE username = ?",
            (username,)
        )
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        try:
            return decrypt_text(row[0])
        except Exception:
            return None
    
    def save_backup_codes(self, username: str, backup_codes: list):
        """
        Save backup codes for a user (hashed).
        
        Args:
            username: The username
            backup_codes: List of backup codes
        """
        import hashlib
        import datetime
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Delete old codes for this user
        cursor.execute("DELETE FROM mfa_backup_codes WHERE username = ?", (username,))
        
        # Insert new codes
        for code in backup_codes:
            code_hash = hashlib.sha256(code.encode('utf-8')).hexdigest()
            cursor.execute("""
            INSERT INTO mfa_backup_codes (username, code_hash, created_at)
            VALUES (?, ?, ?)
            """, (username, code_hash, datetime.datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
    
    def verify_backup_code(self, username: str, backup_code: str) -> bool:
        """
        Verify a backup code and mark it as used.
        
        Args:
            username: The username
            backup_code: The backup code to verify
            
        Returns:
            True if valid and not used, False otherwise
        """
        import hashlib
        import datetime
        
        code_hash = hashlib.sha256(backup_code.encode('utf-8')).hexdigest()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, used FROM mfa_backup_codes
            WHERE username = ? AND code_hash = ?
        """, (username, code_hash))
        
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return False
        
        if row[1] == 1:  # Already used
            conn.close()
            return False
        
        # Mark as used
        cursor.execute(
            "UPDATE mfa_backup_codes SET used = 1, used_at = ? WHERE id = ?",
            (datetime.datetime.now().isoformat(), row[0])
        )
        
        conn.commit()
        conn.close()
        
        return True
    
    def delete_user_mfa(self, username: str):
        """
        Delete all MFA data for a user.
        
        Args:
            username: The username
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM mfa_secrets WHERE username = ?", (username,))
        cursor.execute("DELETE FROM mfa_backup_codes WHERE username = ?", (username,))
        
        conn.commit()
        conn.close()


# Global instance
_global_mfa_manager = None
_global_mfa_storage = None


def get_mfa_manager() -> MFAManager:
    """Get or create the global MFA manager instance."""
    global _global_mfa_manager
    if _global_mfa_manager is None:
        _global_mfa_manager = MFAManager()
    return _global_mfa_manager


def get_mfa_storage() -> MFADatabaseStorage:
    """Get or create the global MFA storage instance."""
    global _global_mfa_storage
    if _global_mfa_storage is None:
        from config import DB_PATH
        _global_mfa_storage = MFADatabaseStorage(DB_PATH)
    return _global_mfa_storage
