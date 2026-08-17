"""
Secure Encryption Module
Implements AES-256-GCM encryption for credential and data protection.
Replaces the weak XOR-based encryption.
"""

import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.backends import default_backend
from typing import Optional


class SecureEncryption:
    """
    AES-256-GCM encryption for secure credential storage.
    
    This class provides industry-standard encryption using:
    - AES-256 algorithm (256-bit key)
    - GCM mode (Galois/Counter Mode) for authenticated encryption
    - 96-bit nonce for each encryption operation
    """
    
    def __init__(self, key: Optional[str] = None):
        """
        Initialize the encryption manager.
        
        Args:
            key: 256-bit (32-byte) hex key. If None, loads from ENCRYPTION_KEY env var.
        """
        if key is None:
            key = os.getenv('ENCRYPTION_KEY')
            if not key:
                raise ValueError(
                    "ENCRYPTION_KEY environment variable not set. "
                    "Please set it in your .env file."
                )
        
        # Convert hex string to bytes
        try:
            self.key = bytes.fromhex(key)
        except ValueError:
            raise ValueError(
                "ENCRYPTION_KEY must be a 64-character hex string (256 bits). "
                f"Got length: {len(key) if key else 0}"
            )
        
        # Validate key length (must be 32 bytes for AES-256)
        if len(self.key) != 32:
            raise ValueError(
                f"ENCRYPTION_KEY must be 32 bytes (256 bits). Got {len(self.key)} bytes."
            )
        
        self.aesgcm = AESGCM(self.key)
    
    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt plaintext using AES-256-GCM.
        
        Args:
            plaintext: The text to encrypt
            
        Returns:
            Base64-encoded string containing nonce + ciphertext
            
        Raises:
            ValueError: If plaintext is empty
        """
        if not plaintext:
            raise ValueError("Cannot encrypt empty plaintext")
        
        # Generate a random 96-bit (12-byte) nonce
        nonce = os.urandom(12)
        
        # Encrypt with AES-256-GCM
        # No additional data (associated data) for now
        ciphertext = self.aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)
        
        # Return base64-encoded nonce + ciphertext
        combined = nonce + ciphertext
        return base64.b64encode(combined).decode('utf-8')
    
    def decrypt(self, ciphertext_b64: str) -> str:
        """
        Decrypt ciphertext using AES-256-GCM.
        
        Args:
            ciphertext_b64: Base64-encoded string containing nonce + ciphertext
            
        Returns:
            Decrypted plaintext
            
        Raises:
            ValueError: If decryption fails or ciphertext is invalid
        """
        if not ciphertext_b64:
            raise ValueError("Cannot decrypt empty ciphertext")
        
        try:
            # Decode base64
            combined = base64.b64decode(ciphertext_b64)
            
            # Extract nonce (first 12 bytes) and ciphertext (remaining bytes)
            nonce = combined[:12]
            actual_ciphertext = combined[12:]
            
            # Decrypt with AES-256-GCM
            plaintext = self.aesgcm.decrypt(nonce, actual_ciphertext, None)
            
            return plaintext.decode('utf-8')
            
        except Exception as e:
            raise ValueError(f"Decryption failed: {str(e)}")
    
    def reencrypt_from_xor(self, old_ciphertext_b64: str, old_key_seed: str) -> str:
        """
        Migrate data from old XOR encryption to new AES-256-GCM encryption.
        
        Args:
            old_ciphertext_b64: Base64-encoded XOR-encrypted data
            old_key_seed: The old key seed used for XOR encryption
            
        Returns:
            Base64-encoded AES-256-GCM encrypted data
        """
        import hashlib
        import base64
        
        # Decrypt using old XOR method
        key_bytes = hashlib.sha256(old_key_seed.encode('utf-8')).digest()
        cipher_bytes = base64.b64decode(old_ciphertext_b64.encode('utf-8'))
        plain_bytes = bytes([
            b ^ key_bytes[i % len(key_bytes)] 
            for i, b in enumerate(cipher_bytes)
        ])
        plaintext = plain_bytes.decode('utf-8')
        
        # Encrypt using new AES-256-GCM method
        return self.encrypt(plaintext)


# Global instance for backward compatibility
_global_encryption_instance = None


def get_encryption_manager() -> SecureEncryption:
    """
    Get or create the global encryption manager instance.
    
    Returns:
        SecureEncryption instance
    """
    global _global_encryption_instance
    
    if _global_encryption_instance is None:
        _global_encryption_instance = SecureEncryption()
    
    return _global_encryption_instance


def encrypt_text(plaintext: str) -> str:
    """
    Convenience function to encrypt text using the global encryption manager.
    
    Args:
        plaintext: Text to encrypt
        
    Returns:
        Base64-encoded encrypted string
    """
    manager = get_encryption_manager()
    return manager.encrypt(plaintext)


def decrypt_text(ciphertext_b64: str) -> str:
    """
    Convenience function to decrypt text using the global encryption manager.
    
    Args:
        ciphertext_b64: Base64-encoded encrypted string
        
    Returns:
        Decrypted plaintext
    """
    manager = get_encryption_manager()
    return manager.decrypt(ciphertext_b64)
