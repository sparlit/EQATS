"""
Password Management Module
Implements secure password hashing using bcrypt.
Replaces the weak SHA-256 based password hashing.
"""

import bcrypt
import secrets
import string
from typing import Optional


class PasswordManager:
    """
    Secure password management using bcrypt.
    
    Bcrypt features:
    - Automatic salt generation (integrated into the hash)
    - Adaptive hashing (cost factor can be increased as hardware improves)
    - Built-in resistance to rainbow table attacks
    - Slow hashing to prevent brute force attacks
    """
    
    def __init__(self, rounds: int = 12):
        """
        Initialize the password manager.
        
        Args:
            rounds: The cost factor (2^rounds iterations). Default 12 is recommended for 2024.
                  Higher values = more secure but slower.
        """
        self.rounds = rounds
    
    def hash_password(self, password: str) -> str:
        """
        Hash a password using bcrypt.
        
        Args:
            password: The plaintext password to hash
            
        Returns:
            Salted bcrypt hash (60 characters)
            
        Raises:
            ValueError: If password is empty
        """
        if not password:
            raise ValueError("Cannot hash empty password")
        
        # Bcrypt automatically generates and includes the salt
        # The rounds parameter controls the computational cost
        password_bytes = password.encode('utf-8')
        salt = bcrypt.gensalt(rounds=self.rounds)
        hashed = bcrypt.hashpw(password_bytes, salt)
        
        return hashed.decode('utf-8')
    
    def verify_password(self, password: str, hashed_password: str) -> bool:
        """
        Verify a password against a bcrypt hash.
        
        Args:
            password: The plaintext password to verify
            hashed_password: The bcrypt hash to verify against
            
        Returns:
            True if password matches, False otherwise
        """
        if not password or not hashed_password:
            return False
        
        try:
            password_bytes = password.encode('utf-8')
            hash_bytes = hashed_password.encode('utf-8')
            
            # Bcrypt.checkpw handles the salt extraction automatically
            return bcrypt.checkpw(password_bytes, hash_bytes)
            
        except Exception:
            # Return False on any error (fail-safe)
            return False
    
    def generate_strong_password(
        self, 
        length: int = 16, 
        include_uppercase: bool = True,
        include_lowercase: bool = True,
        include_digits: bool = True,
        include_symbols: bool = True
    ) -> str:
        """
        Generate a cryptographically secure random password.
        
        Args:
            length: Password length (minimum 8 recommended)
            include_uppercase: Include uppercase letters
            include_lowercase: Include lowercase letters
            include_digits: Include digits
            include_symbols: Include special characters
            
        Returns:
            Generated password string
        """
        if length < 8:
            raise ValueError("Password length must be at least 8 characters")
        
        # Build character set
        charset = ""
        if include_uppercase:
            charset += string.ascii_uppercase
        if include_lowercase:
            charset += string.ascii_lowercase
        if include_digits:
            charset += string.digits
        if include_symbols:
            charset += string.punctuation
        
        if not charset:
            raise ValueError("At least one character type must be included")
        
        # Generate password using cryptographically secure random generator
        password = ''.join(secrets.choice(charset) for _ in range(length))
        
        # Ensure at least one character from each selected type
        password_list = list(password)
        
        if include_uppercase:
            password_list[0] = secrets.choice(string.ascii_uppercase)
        if include_lowercase:
            password_list[1 % length] = secrets.choice(string.ascii_lowercase)
        if include_digits:
            password_list[2 % length] = secrets.choice(string.digits)
        if include_symbols:
            password_list[3 % length] = secrets.choice(string.punctuation)
        
        # Shuffle to avoid predictable pattern
        secrets.SystemRandom().shuffle(password_list)
        
        return ''.join(password_list)
    
    def check_password_strength(self, password: str) -> dict:
        """
        Check password strength against common requirements.
        
        Args:
            password: The password to check
            
        Returns:
            Dictionary with strength assessment and details
        """
        result = {
            'score': 0,
            'strong': False,
            'issues': [],
            'suggestions': []
        }
        
        if len(password) < 8:
            result['issues'].append('Password is too short (minimum 8 characters)')
            result['suggestions'].append('Use at least 8 characters')
        else:
            result['score'] += 1
        
        if len(password) >= 12:
            result['score'] += 1
            result['suggestions'].append('Good length (12+ characters)')
        
        if not any(c.isupper() for c in password):
            result['issues'].append('Password has no uppercase letters')
            result['suggestions'].append('Add uppercase letters')
        else:
            result['score'] += 1
        
        if not any(c.islower() for c in password):
            result['issues'].append('Password has no lowercase letters')
            result['suggestions'].append('Add lowercase letters')
        else:
            result['score'] += 1
        
        if not any(c.isdigit() for c in password):
            result['issues'].append('Password has no digits')
            result['suggestions'].append('Add numbers')
        else:
            result['score'] += 1
        
        if not any(c in string.punctuation for c in password):
            result['issues'].append('Password has no special characters')
            result['suggestions'].append('Add special characters (!@#$%^&*)')
        else:
            result['score'] += 1
        
        # Check for common patterns
        if password.lower() in ['password', '12345678', 'qwerty', 'admin']:
            result['issues'].append('Password is too common')
            result['score'] = max(0, result['score'] - 2)
        
        # Check for sequential characters
        for i in range(len(password) - 2):
            if (ord(password[i+1]) == ord(password[i]) + 1 and 
                ord(password[i+2]) == ord(password[i]) + 2):
                result['issues'].append('Password contains sequential characters')
                result['score'] = max(0, result['score'] - 1)
                break
        
        # Determine if strong
        result['strong'] = result['score'] >= 4 and len(result['issues']) == 0
        
        return result


class PinManager:
    """
    PIN management using bcrypt.
    Similar to PasswordManager but optimized for PINs (typically 4-6 digits).
    """
    
    def __init__(self, rounds: int = 10):
        """
        Initialize the PIN manager.
        
        Args:
            rounds: Cost factor (PINs can use lower rounds since they're shorter)
        """
        self.rounds = rounds
    
    def hash_pin(self, pin: str) -> str:
        """
        Hash a PIN using bcrypt.
        
        Args:
            pin: The PIN to hash (string)
            
        Returns:
            Salted bcrypt hash
        """
        if not pin:
            raise ValueError("Cannot hash empty PIN")
        
        pin_bytes = pin.encode('utf-8')
        salt = bcrypt.gensalt(rounds=self.rounds)
        hashed = bcrypt.hashpw(pin_bytes, salt)
        
        return hashed.decode('utf-8')
    
    def verify_pin(self, pin: str, hashed_pin: str) -> bool:
        """
        Verify a PIN against a bcrypt hash.
        
        Args:
            pin: The PIN to verify
            hashed_pin: The bcrypt hash to verify against
            
        Returns:
            True if PIN matches, False otherwise
        """
        if not pin or not hashed_pin:
            return False
        
        try:
            pin_bytes = pin.encode('utf-8')
            hash_bytes = hashed_pin.encode('utf-8')
            return bcrypt.checkpw(pin_bytes, hash_bytes)
        except Exception:
            return False
    
    def generate_secure_pin(self, length: int = 6) -> str:
        """
        Generate a secure random PIN.
        
        Args:
            length: PIN length (typically 4-6)
            
        Returns:
            Generated PIN string
        """
        if length < 4:
            raise ValueError("PIN length must be at least 4")
        if length > 10:
            raise ValueError("PIN length should not exceed 10")
        
        return ''.join(secrets.choice(string.digits) for _ in range(length))


# Global instances for convenience
_global_password_manager = None
_global_pin_manager = None


def get_password_manager() -> PasswordManager:
    """Get or create the global password manager instance."""
    global _global_password_manager
    if _global_password_manager is None:
        _global_password_manager = PasswordManager()
    return _global_password_manager


def get_pin_manager() -> PinManager:
    """Get or create the global PIN manager instance."""
    global _global_pin_manager
    if _global_pin_manager is None:
        _global_pin_manager = PinManager()
    return _global_pin_manager
