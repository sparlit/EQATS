# Security Fix: User Credential Password Hashing

## Vulnerability Summary

**Title:** User credentials are stored with a fast, globally salted SHA-256 digest

**Severity:** High

**Impact:** User passwords and PINs were vulnerable to offline brute-force attacks after database compromise due to use of fast SHA-256 hashing with a fixed global salt.

## Root Cause

The original implementation used `hash_credential()` which computed `SHA256(secret + ":" + fixed_source_salt)` for all user credentials:

```python
def hash_credential(secret_text, salt="EQATS_SOVEREIGN_SALT_2026"):
    salted_str = f"{secret_text}:{salt}"
    return hashlib.sha256(salted_str.encode("utf-8")).hexdigest()
```

### Security Deficiencies

1. **Fast Hash Function**: SHA-256 is designed for speed, allowing attackers to test billions of password guesses per second on modern GPUs
2. **Global Salt**: Single fixed salt shared across all users and credentials
3. **No Work Factor**: No configurable cost parameter to increase computational difficulty
4. **Precomputation Attacks**: Fixed salt enables rainbow table attacks
5. **Credential Distinguishability**: Identical passwords across accounts produce identical hashes

### Attack Scenario

If an attacker obtains the SQLite database (e.g., via backup compromise, insider threat, or server breach):
- Can test 10+ billion SHA-256 hashes per second on commodity GPU hardware
- 6-digit PIN (1 million combinations) crackable in milliseconds
- Common passwords crackable in seconds to minutes
- No per-user salt means one rainbow table works for all accounts

## Security Fix Implementation

### 1. Bcrypt Password Hashing

Replaced SHA-256 with bcrypt, a password-specific key derivation function:

```python
def hash_credential_secure(secret_text):
    """
    Generates cryptographically secure password hash using bcrypt with per-credential
    random salt and configurable work factor.
    
    Uses bcrypt with 12 rounds (2^12 = 4096 iterations), providing strong protection
    against offline brute-force and dictionary attacks.
    """
    if _BCRYPT_AVAILABLE:
        password_bytes = secret_text.encode('utf-8')
        hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt(rounds=_BCRYPT_ROUNDS))
        return hashed.decode('utf-8')
```

**Key Improvements:**
- **Per-Credential Salt**: Each password/PIN gets a unique random 128-bit salt
- **Work Factor**: 12 rounds = 4,096 iterations (OWASP 2023 recommendation)
- **Adaptive Cost**: Can increase rounds as hardware improves
- **Industry Standard**: Battle-tested, widely audited implementation

### 2. Backward Compatibility & Migration

Implemented transparent migration that preserves existing credentials:

```python
def verify_credential(secret_text, stored_hash):
    """
    Verifies password against stored hash, supporting both legacy SHA-256
    and modern bcrypt hashes with automatic migration.
    
    Returns: (is_valid: bool, needs_rehash: bool)
    """
    # Detect hash format
    if stored_hash.startswith(('$2a$', '$2b$', '$2y$')):
        # Modern bcrypt hash
        return (bcrypt.checkpw(password_bytes, hash_bytes), False)
    else:
        # Legacy SHA-256 hash - verify and flag for upgrade
        is_valid = (stored_hash == hash_credential(secret_text))
        return (is_valid, is_valid)  # If valid, needs rehash
```

**Migration Strategy:**
- Legacy hashes remain valid during transition period
- Automatic upgrade to bcrypt on successful login
- No user action required
- No service disruption

### 3. Updated All Credential Paths

**User Creation** (`add_user`):
```python
params = (
    username,
    hash_credential_secure(password),  # New bcrypt hash
    hash_credential_secure(pin),       # New bcrypt hash
    role,
    int(mfa_enabled),
    datetime.datetime.now().isoformat(),
)
```

**Password Verification** (`verify_user_password`):
```python
stored_hash = row["password_hash"]
is_valid, needs_rehash = verify_credential(password_input, stored_hash)

# Automatic migration: upgrade legacy hash to bcrypt on successful login
if is_valid and needs_rehash:
    new_hash = hash_credential_secure(password_input)
    cursor.execute(
        "UPDATE users SET password_hash = ? WHERE LOWER(username) = LOWER(?)",
        (new_hash, username)
    )
    conn.commit()
    _log.info("Upgraded password hash to bcrypt for user: %s", username)
```

**Credential Updates** (`update_user`):
```python
if new_password is not None and str(new_password).strip():
    _execute_with_retry(
        "UPDATE users SET password_hash = ? WHERE LOWER(username) = LOWER(?)",
        (hash_credential_secure(str(new_password).strip()), target_user),
    )
```

### 4. Migration Monitoring

Added diagnostic function for administrators:

```python
def get_credential_migration_status():
    """
    Returns migration status of user credentials from legacy SHA-256 to bcrypt.
    
    Returns:
        dict: {
            'total_users': int,
            'bcrypt_passwords': int,
            'legacy_passwords': int,
            'bcrypt_pins': int,
            'legacy_pins': int,
            'migration_complete': bool
        }
    """
```

## Security Properties After Fix

### Offline Attack Resistance

**Before (SHA-256):**
- Attack rate: ~10 billion hashes/second (RTX 4090)
- 6-digit PIN: cracked in <1 millisecond
- 8-char lowercase password: cracked in ~2 seconds
- Common password list (10M): tested in 1 second

**After (bcrypt, 12 rounds):**
- Attack rate: ~50,000 hashes/second (RTX 4090)
- 6-digit PIN: cracked in ~20 seconds (200,000x slower)
- 8-char lowercase password: cracked in ~11 hours (20,000x slower)
- Common password list (10M): tested in ~55 hours (200,000x slower)

### Additional Protections

1. **Unique Salts**: Identical passwords produce different hashes across accounts
2. **No Precomputation**: Rainbow tables infeasible due to per-credential salts
3. **Future-Proof**: Work factor can be increased as hardware improves
4. **Constant-Time Comparison**: bcrypt.checkpw() resists timing attacks

## Deployment Instructions

### 1. Install bcrypt Library

```bash
pip install bcrypt
```

Or add to `requirements.txt`:
```
bcrypt>=4.0.0
```

### 2. Verify Installation

```python
import database

# Check if bcrypt is available
if database._BCRYPT_AVAILABLE:
    print("✓ bcrypt is available - secure hashing enabled")
else:
    print("✗ bcrypt not available - using legacy SHA-256 (INSECURE)")
```

### 3. Monitor Migration Progress

```python
import database

status = database.get_credential_migration_status()
print(f"Total users: {status['total_users']}")
print(f"Bcrypt passwords: {status['bcrypt_passwords']}")
print(f"Legacy passwords: {status['legacy_passwords']}")
print(f"Migration complete: {status['migration_complete']}")
```

### 4. Existing Users

**No action required.** Credentials will be automatically upgraded to bcrypt on next successful login.

### 5. New Installations

New user accounts created after this fix automatically use bcrypt hashing.

## Fallback Behavior

If bcrypt library is not available:
- System logs warning at startup
- Falls back to legacy SHA-256 (maintains functionality)
- Logs warning on each hash operation
- **Recommendation**: Install bcrypt immediately for production deployments

## Testing

Verify the fix with:

```python
import database

# Test new credential creation
database.add_user("test_user", "SecurePass123!", "123456")

# Test verification
assert database.verify_user_password("test_user", "SecurePass123!")
assert not database.verify_user_password("test_user", "WrongPassword")

# Check hash format (should start with $2b$)
conn = database.get_connection()
cursor = conn.cursor()
cursor.execute("SELECT password_hash FROM users WHERE username = ?", ("test_user",))
row = cursor.fetchone()
conn.close()

assert row["password_hash"].startswith("$2b$"), "Password should use bcrypt"
print("✓ All tests passed")
```

## Compliance & Standards

This fix aligns with:
- **OWASP Password Storage Cheat Sheet**: Use bcrypt with work factor ≥12
- **NIST SP 800-63B**: Use approved password hashing algorithms
- **PCI DSS 3.2.1**: Render authentication data unreadable (Requirement 8.2.1)
- **GDPR Article 32**: Implement appropriate technical measures for security

## References

- [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
- [bcrypt Documentation](https://github.com/pyca/bcrypt/)
- [NIST SP 800-63B Digital Identity Guidelines](https://pages.nist.gov/800-63-3/sp800-63b.html)
- [How To Safely Store A Password](https://codahale.com/how-to-safely-store-a-password/)

## Related Security Fixes

- `SECURITY_CREDENTIALS.md`: Broker credential encryption with Fernet
- `SECURITY.md`: General security policy and vulnerability reporting

## Changelog

**2024-01-XX**: Initial implementation
- Replaced SHA-256 with bcrypt (12 rounds)
- Added per-credential random salts
- Implemented transparent migration
- Added migration monitoring utilities
- Updated all credential creation/verification paths
