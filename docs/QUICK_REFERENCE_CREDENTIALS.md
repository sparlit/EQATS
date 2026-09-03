# Quick Reference: Secure Credential Management

## For System Administrators

### Initial Setup (New Installation)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set master encryption key (IMPORTANT!)
export EQATS_MASTER_KEY="YourStrongPassphrase-MinimumLength32Characters!"

# 3. Start application
python main.py
```

### Upgrading from Previous Version

```bash
# 1. Backup your database
cp scalper_brain.db scalper_brain.db.backup_$(date +%Y%m%d)

# 2. Install new dependencies
pip install cryptography

# 3. Set master encryption key
export EQATS_MASTER_KEY="YourStrongPassphrase-MinimumLength32Characters!"

# 4. Run migration (optional but recommended)
python migrate_credentials.py

# 5. Start application
python main.py
```

### Environment Variable Setup

**Linux/Mac (bash/zsh):**
```bash
# Temporary (current session only)
export EQATS_MASTER_KEY="your-passphrase"

# Permanent (add to ~/.bashrc or ~/.zshrc)
echo 'export EQATS_MASTER_KEY="your-passphrase"' >> ~/.bashrc
source ~/.bashrc
```

**Windows (PowerShell):**
```powershell
# Temporary (current session only)
$env:EQATS_MASTER_KEY="your-passphrase"

# Permanent (system-wide)
[System.Environment]::SetEnvironmentVariable('EQATS_MASTER_KEY', 'your-passphrase', 'User')
```

**Windows (Command Prompt):**
```cmd
# Temporary (current session only)
set EQATS_MASTER_KEY=your-passphrase

# Permanent (system-wide)
setx EQATS_MASTER_KEY "your-passphrase"
```

### Docker Deployment

```dockerfile
# In Dockerfile
ENV EQATS_MASTER_KEY="your-passphrase"

# Or via docker-compose.yml
services:
  eqats:
    environment:
      - EQATS_MASTER_KEY=your-passphrase
    # Or use secrets (recommended)
    secrets:
      - eqats_master_key
```

### Kubernetes Deployment

```yaml
# Create secret
apiVersion: v1
kind: Secret
metadata:
  name: eqats-credentials
type: Opaque
stringData:
  master-key: "your-passphrase"

---
# Use in deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: eqats
spec:
  template:
    spec:
      containers:
      - name: eqats
        env:
        - name: EQATS_MASTER_KEY
          valueFrom:
            secretKeyRef:
              name: eqats-credentials
              key: master-key
```

## For Developers

### Adding New Encrypted Fields

```python
import database

# Encrypt before storing
encrypted_value = database.encrypt_secret("sensitive_data")

# Store in database
cursor.execute("INSERT INTO table (encrypted_field) VALUES (?)", (encrypted_value,))

# Decrypt when retrieving
encrypted_value = row["encrypted_field"]
decrypted_value = database.decrypt_secret(encrypted_value)
```

### Testing Encryption

```python
# Run test suite
python test_credential_encryption.py

# Manual test
import database

# Test encryption
plain = "test_password"
encrypted = database.encrypt_secret(plain)
decrypted = database.decrypt_secret(encrypted)
assert plain == decrypted, "Encryption test failed"
```

## Troubleshooting

### Issue: "cryptography library not available"

**Solution:**
```bash
pip install cryptography
```

### Issue: "Failed to decrypt credential"

**Possible Causes:**
1. Master key changed
2. Salt file deleted
3. Database copied from different machine

**Solution:**
Re-enter credentials through GUI or:
```python
import database

database.save_broker_credentials(
    server="your-server",
    account_id="your-account",
    password="your-password",
    leverage="1:100",
    api_key="your-api-key",
    api_secret="your-api-secret",
)
```

### Issue: Warning about machine-derived key

**Cause:** `EQATS_MASTER_KEY` environment variable not set

**Solution:**
```bash
export EQATS_MASTER_KEY="your-strong-passphrase"
```

### Issue: Salt file missing after database restore

**Solution:**
Restore the `.salt` file along with the database, or re-enter credentials.

## Security Best Practices

### ✓ DO

- Set `EQATS_MASTER_KEY` to a strong, unique passphrase (32+ characters)
- Store master key in a password manager or secrets vault
- Backup both database AND salt file together
- Use restrictive file permissions (0600 on Unix)
- Rotate master key periodically
- Use environment variables or secrets management systems

### ✗ DON'T

- Hardcode master key in source code
- Commit master key to version control
- Share master key via insecure channels (email, chat)
- Use weak or common passphrases
- Store master key in the same location as database
- Forget to backup the salt file

## File Locations

| File | Purpose | Backup? |
|------|---------|---------|
| `scalper_brain.db` | Main database | ✓ Yes |
| `scalper_brain.db.salt` | Encryption salt | ✓ Yes |
| `scalper_brain.db-wal` | SQLite write-ahead log | Optional |
| `scalper_brain.db-shm` | SQLite shared memory | No |

## Quick Commands

```bash
# Check if cryptography is installed
python -c "import cryptography; print(cryptography.__version__)"

# Check if master key is set
python -c "import os; print('Set' if os.getenv('EQATS_MASTER_KEY') else 'Not set')"

# View encrypted data in database (should be unreadable)
sqlite3 scalper_brain.db "SELECT password_encrypted FROM broker_credentials LIMIT 1;"

# Check salt file exists
ls -la scalper_brain.db.salt

# Run encryption tests
python test_credential_encryption.py

# Migrate existing credentials
python migrate_credentials.py

# Backup database and salt
tar -czf eqats_backup_$(date +%Y%m%d).tar.gz scalper_brain.db scalper_brain.db.salt
```

## Support Resources

- **Full Documentation:** `SECURITY_CREDENTIALS.md`
- **Fix Summary:** `SECURITY_FIX_SUMMARY.md`
- **Migration Script:** `migrate_credentials.py`
- **Test Suite:** `test_credential_encryption.py`

## Emergency Recovery

If you lose your master key:

1. **Credentials are NOT recoverable** - this is by design for security
2. You must re-enter all broker credentials through the GUI
3. Set a new `EQATS_MASTER_KEY` before re-entering credentials
4. Document your new master key in a secure location

## Compliance Notes

This implementation meets:
- ✓ OWASP Cryptographic Storage guidelines
- ✓ NIST SP 800-132 (PBKDF2 with 480k iterations)
- ✓ PCI DSS 3.2.1 Requirement 3.4 (encryption at rest)
- ✓ GDPR Article 32 (appropriate security measures)
