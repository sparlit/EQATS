# Broker Credentials Security

## Overview

Starting with this version, EQATS uses industry-standard Fernet authenticated encryption (AES-128 in CBC mode with HMAC authentication) to protect broker credentials stored in the SQLite database. This replaces the previous XOR-based obfuscation scheme.

## Key Features

1. **Authenticated Encryption**: Uses Fernet (cryptography library) providing both confidentiality and integrity
2. **Key Derivation**: Encryption key is derived using PBKDF2-HMAC-SHA256 with 480,000 iterations (OWASP 2023 recommendation)
3. **All Credentials Encrypted**: Passwords, API keys, and API secrets are all encrypted
4. **Backward Compatibility**: Automatically handles legacy XOR-encrypted data during migration

## Setting Up Encryption

### Production Deployment (Recommended)

For production deployments, set a strong master key via environment variable:

```bash
export EQATS_MASTER_KEY="your-strong-passphrase-here-min-32-chars"
```

**Important**: 
- Use a strong, unique passphrase (minimum 32 characters recommended)
- Store this passphrase securely (password manager, secrets vault, etc.)
- **Do not commit this passphrase to version control**
- If you lose this passphrase, encrypted credentials cannot be recovered

### Development/Testing (Fallback)

If no `EQATS_MASTER_KEY` is set, the system will:
1. Derive a key from machine-specific identifiers (hostname + machine type)
2. Log a warning recommending you set `EQATS_MASTER_KEY`
3. Store a random salt in `<database_name>.salt` file

This fallback provides better security than the previous hardcoded seed but is still not suitable for production.

## Migration from Legacy Encryption

The system automatically handles migration:

1. **First Run**: Database schema is updated to rename `api_key` → `api_key_encrypted` and `api_secret` → `api_secret_encrypted`
2. **Reading Legacy Data**: If Fernet decryption fails, the system attempts legacy XOR decryption
3. **Writing New Data**: All new credentials are encrypted with Fernet
4. **Re-encryption**: To fully migrate, re-save your broker credentials through the GUI or API

### Manual Re-encryption (Optional)

To ensure all credentials use the new encryption:

```python
import database

# Get all brokers (this decrypts using legacy method if needed)
brokers = database.get_all_brokers()

# Re-save each broker (this encrypts using new Fernet method)
for broker in brokers:
    database.save_broker_credentials(
        server=broker["server"],
        account_id=broker["account_id"],
        password=broker["password"],
        leverage=broker["leverage"],
        broker_name=broker.get("broker_name", "Gateway"),
        environment=broker.get("environment", "Demo"),
        protocol_type=broker.get("protocol_type", "MT5"),
        api_key=broker.get("api_key", ""),
        api_secret=broker.get("api_secret", ""),
        rest_url=broker.get("rest_url", ""),
        ws_url=broker.get("ws_url", ""),
        terminal_path=broker.get("terminal_path", ""),
    )
```

## Security Considerations

### What This Protects Against

- **Database Theft**: Encrypted credentials cannot be read without the master key
- **Source Code Disclosure**: No hardcoded encryption keys in source code
- **Offline Attacks**: PBKDF2 with 480k iterations makes brute-force attacks computationally expensive

### What This Does NOT Protect Against

- **Runtime Memory Dumps**: Credentials are decrypted in memory during use
- **Compromised Application Server**: Attacker with root access can extract the master key from environment
- **Weak Master Keys**: If you use a weak passphrase, it can be brute-forced

### Additional Recommendations

1. **File System Permissions**: Ensure database file has restrictive permissions (0600 on Unix)
2. **Secrets Management**: Use a proper secrets management system (HashiCorp Vault, AWS Secrets Manager, etc.) for production
3. **Key Rotation**: Periodically rotate your master key and re-encrypt credentials
4. **Audit Logging**: Monitor access to broker credentials
5. **Network Security**: Use TLS/SSL for all broker API connections

## Dependencies

The new encryption requires the `cryptography` library:

```bash
pip install cryptography
```

If this library is not available, the system falls back to legacy XOR encryption with a warning.

## Troubleshooting

### "cryptography library not available" Error

Install the cryptography package:
```bash
pip install cryptography
```

### "Failed to decrypt credential" Warning

This can occur if:
1. The master key has changed since credentials were encrypted
2. The salt file was deleted or corrupted
3. Database was copied from another machine with different fallback key

**Solution**: Re-enter your broker credentials through the GUI.

### Salt File Location

The salt file is stored at: `<database_path>.salt`

For example, if your database is `scalper_brain.db`, the salt file is `scalper_brain.db.salt`

**Important**: Keep this file with your database. If you backup the database, backup the salt file too.

## API Reference

### encrypt_secret(plain_text)

Encrypts a credential string using Fernet authenticated encryption.

**Parameters:**
- `plain_text` (str): The plaintext credential to encrypt

**Returns:**
- `str`: Base64-encoded Fernet ciphertext, or empty string if input is empty

### decrypt_secret(cipher_text)

Decrypts a Fernet-encrypted credential string.

**Parameters:**
- `cipher_text` (str): The encrypted credential string

**Returns:**
- `str`: Decrypted plaintext, or empty string on failure

**Note**: Automatically falls back to legacy XOR decryption for backward compatibility.

## Security Audit Trail

- **Issue**: Broker credentials used reversible fixed-key obfuscation (XOR with hardcoded seed)
- **Risk**: Database theft + source code disclosure = credential compromise
- **Mitigation**: Implemented Fernet authenticated encryption with PBKDF2 key derivation
- **Status**: Mitigated (requires user to set EQATS_MASTER_KEY for full protection)
