import base64
import datetime
import hashlib
import logging
import os
import sqlite3

import config

_log = logging.getLogger("database")

# Try to import bcrypt for secure password hashing
try:
    import bcrypt
    _BCRYPT_AVAILABLE = True
    _BCRYPT_ROUNDS = 12  # 2^12 iterations, OWASP recommended minimum
except ImportError:
    _BCRYPT_AVAILABLE = False
    _log.warning(
        "bcrypt library not available. Password security is degraded. "
        "Install with: pip install bcrypt"
    )

# Encryption key management with environment variable support
_ENCRYPTION_KEY = None
_ENCRYPTION_SALT = None


def _get_encryption_key():
    """
    Retrieves or generates the encryption key for broker credentials.
    
    The key is derived from an environment variable EQATS_MASTER_KEY using PBKDF2.
    If no environment variable is set, falls back to a machine-specific derived key
    that provides better security than the previous hardcoded seed while maintaining
    backward compatibility for existing deployments.
    
    Returns:
        bytes: 32-byte encryption key suitable for Fernet symmetric encryption
    """
    global _ENCRYPTION_KEY, _ENCRYPTION_SALT
    
    if _ENCRYPTION_KEY is not None:
        return _ENCRYPTION_KEY
    
    # Check for user-provided master key in environment
    master_password = os.environ.get("EQATS_MASTER_KEY", "")
    
    if not master_password:
        # Fallback: derive from machine-specific identifiers for better security than hardcoded seed
        # This is still not ideal but significantly better than a source-embedded constant
        try:
            import platform
            machine_id = platform.node() + platform.machine()
        except Exception:
            machine_id = "EQATS_DEFAULT_MACHINE"
        
        master_password = f"EQATS_DERIVED_{machine_id}_2026"
        _log.warning(
            "No EQATS_MASTER_KEY environment variable set. Using machine-derived key. "
            "For production deployments, set EQATS_MASTER_KEY to a strong passphrase."
        )
    
    # Retrieve or generate salt
    _ENCRYPTION_SALT = _get_or_create_salt()
    
    # Derive key using PBKDF2 with 480,000 iterations (OWASP 2023 recommendation)
    _ENCRYPTION_KEY = hashlib.pbkdf2_hmac(
        'sha256',
        master_password.encode('utf-8'),
        _ENCRYPTION_SALT,
        480000,
        dklen=32
    )
    
    return _ENCRYPTION_KEY


def _get_or_create_salt():
    """
    Retrieves or creates a persistent salt for key derivation.
    
    The salt is stored in a file adjacent to the database to ensure
    consistent key derivation across application restarts.
    
    Returns:
        bytes: 32-byte salt for PBKDF2 key derivation
    """
    salt_file = config.DB_PATH + ".salt"
    
    try:
        if os.path.exists(salt_file):
            with open(salt_file, 'rb') as f:
                salt = f.read()
                if len(salt) == 32:
                    return salt
    except Exception as e:
        _log.debug("Could not read salt file: %s", e)
    
    # Generate new salt
    salt = os.urandom(32)
    
    try:
        with open(salt_file, 'wb') as f:
            f.write(salt)
        # Set restrictive permissions on Unix-like systems
        if hasattr(os, 'chmod'):
            os.chmod(salt_file, 0o600)
    except Exception as e:
        _log.warning("Could not persist salt file: %s", e)
    
    return salt


def hash_credential(secret_text, salt="EQATS_SOVEREIGN_SALT_2026"):
    """
    DEPRECATED: Legacy SHA-256 hashing for backward compatibility only.
    
    This function uses a fast, globally-salted SHA-256 digest which is vulnerable
    to offline brute-force attacks. It is retained only for verifying existing
    credentials during migration. New credentials should use hash_credential_secure().
    """
    if not secret_text:
        secret_text = ""
    salted_str = f"{secret_text}:{salt}"
    return hashlib.sha256(salted_str.encode("utf-8")).hexdigest()


def hash_credential_secure(secret_text):
    """
    Generates a cryptographically secure password hash using bcrypt with per-credential
    random salt and configurable work factor.
    
    Uses bcrypt with 12 rounds (2^12 = 4096 iterations), providing strong protection
    against offline brute-force and dictionary attacks. Each hash includes a unique
    random salt, preventing precomputation attacks and making identical credentials
    distinguishable across accounts.
    
    Args:
        secret_text: The password or PIN to hash
        
    Returns:
        str: bcrypt hash string (includes algorithm, cost, salt, and hash)
             Format: $2b$12$[22-char-salt][31-char-hash]
             Falls back to legacy SHA-256 if bcrypt unavailable (with warning)
    """
    if not secret_text:
        secret_text = ""
    
    if _BCRYPT_AVAILABLE:
        # bcrypt automatically generates a unique random salt per hash
        # and includes it in the output string along with the cost parameter
        password_bytes = secret_text.encode('utf-8')
        hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt(rounds=_BCRYPT_ROUNDS))
        return hashed.decode('utf-8')
    else:
        # Fallback to legacy method if bcrypt not available
        # This maintains functionality but logs a warning
        _log.warning(
            "Using legacy SHA-256 hashing due to missing bcrypt. "
            "Install bcrypt for proper password security: pip install bcrypt"
        )
        return hash_credential(secret_text)


def verify_credential(secret_text, stored_hash):
    """
    Verifies a password or PIN against a stored hash, supporting both legacy SHA-256
    and modern bcrypt hashes with automatic migration.
    
    This function provides backward compatibility by detecting the hash format:
    - bcrypt hashes start with '$2a$', '$2b$', or '$2y$'
    - Legacy SHA-256 hashes are 64-character hex strings
    
    Args:
        secret_text: The plaintext password/PIN to verify
        stored_hash: The hash from the database
        
    Returns:
        tuple: (is_valid: bool, needs_rehash: bool)
               is_valid: True if credential matches
               needs_rehash: True if using legacy hash and should be upgraded
    """
    if not secret_text or not stored_hash:
        return (False, False)
    
    # Detect bcrypt hash format
    if stored_hash.startswith(('$2a$', '$2b$', '$2y$')):
        if _BCRYPT_AVAILABLE:
            try:
                password_bytes = secret_text.encode('utf-8')
                hash_bytes = stored_hash.encode('utf-8')
                is_valid = bcrypt.checkpw(password_bytes, hash_bytes)
                return (is_valid, False)  # Modern hash, no rehash needed
            except Exception as e:
                _log.debug("bcrypt verification failed: %s", e)
                return (False, False)
        else:
            # bcrypt hash but library not available
            _log.error("Cannot verify bcrypt hash without bcrypt library")
            return (False, False)
    else:
        # Legacy SHA-256 hash - verify and flag for rehashing
        legacy_hash = hash_credential(secret_text)
        is_valid = (stored_hash == legacy_hash)
        return (is_valid, is_valid)  # If valid, needs rehash to bcrypt


def encrypt_secret(plain_text):
    """
    Encrypts sensitive broker credentials using Fernet authenticated encryption.
    
    This function provides confidentiality and integrity protection for broker
    passwords, API keys, and API secrets. The encryption key is derived from
    a user-provided master key (EQATS_MASTER_KEY environment variable) or a
    machine-specific fallback using PBKDF2 key derivation.
    
    Args:
        plain_text: The plaintext credential to encrypt
        
    Returns:
        str: Base64-encoded Fernet ciphertext, or empty string if input is empty
    """
    if not plain_text:
        return ""
    
    try:
        from cryptography.fernet import Fernet
        
        # Get or derive encryption key
        key = _get_encryption_key()
        
        # Fernet requires base64-encoded 32-byte key
        fernet_key = base64.urlsafe_b64encode(key)
        cipher = Fernet(fernet_key)
        
        # Encrypt and return as string
        encrypted = cipher.encrypt(plain_text.encode('utf-8'))
        return encrypted.decode('utf-8')
        
    except ImportError:
        _log.error(
            "cryptography library not available. Install with: pip install cryptography"
        )
        # Fallback to legacy XOR for backward compatibility during transition
        return _legacy_encrypt_secret(plain_text)
    except Exception as e:
        _log.error("Encryption failed: %s", e)
        return ""


def decrypt_secret(cipher_text):
    """
    Decrypts Fernet-encrypted broker credentials.
    
    Attempts to decrypt using Fernet authenticated encryption. If decryption fails
    (e.g., for legacy XOR-encrypted data), attempts legacy decryption for backward
    compatibility during migration.
    
    Args:
        cipher_text: The encrypted credential string
        
    Returns:
        str: Decrypted plaintext, or empty string on failure
    """
    if not cipher_text:
        return ""
    
    try:
        from cryptography.fernet import Fernet
        
        # Get or derive encryption key
        key = _get_encryption_key()
        
        # Fernet requires base64-encoded 32-byte key
        fernet_key = base64.urlsafe_b64encode(key)
        cipher = Fernet(fernet_key)
        
        # Decrypt and return as string
        decrypted = cipher.decrypt(cipher_text.encode('utf-8'))
        return decrypted.decode('utf-8')
        
    except ImportError:
        _log.error(
            "cryptography library not available. Install with: pip install cryptography"
        )
        # Fallback to legacy XOR for backward compatibility
        return _legacy_decrypt_secret(cipher_text)
    except Exception:
        # If Fernet decryption fails, try legacy XOR decryption for backward compatibility
        try:
            return _legacy_decrypt_secret(cipher_text)
        except Exception:
            _log.debug("Failed to decrypt credential with both Fernet and legacy methods")
            return ""


def _legacy_encrypt_secret(plain_text, key_seed="EQATS_CIPHER_KEY_2026"):
    """Legacy XOR-based encryption for backward compatibility only."""
    if not plain_text:
        return ""
    key_bytes = hashlib.sha256(key_seed.encode("utf-8")).digest()
    plain_bytes = plain_text.encode("utf-8")
    cipher_bytes = bytes(
        [b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(plain_bytes)]
    )
    return base64.b64encode(cipher_bytes).decode("utf-8")


def _legacy_decrypt_secret(cipher_text, key_seed="EQATS_CIPHER_KEY_2026"):
    """Legacy XOR-based decryption for backward compatibility only."""
    if not cipher_text:
        return ""
    try:
        key_bytes = hashlib.sha256(key_seed.encode("utf-8")).digest()
        cipher_bytes = base64.b64decode(cipher_text.encode("utf-8"))
        plain_bytes = bytes(
            [b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(cipher_bytes)]
        )
        return plain_bytes.decode("utf-8")
    except Exception:
        return ""


def get_connection():
    """Returns a thread-safe connection to the SQLite database with WAL journal mode and 60-second busy timeout."""
    if config.DB_PATH == ":memory:":
        conn = sqlite3.connect("file::memory:?cache=shared", uri=True, timeout=60.0)
    else:
        conn = sqlite3.connect(config.DB_PATH, timeout=60.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=60000;")
    except sqlite3.OperationalError as e:
        _log.debug("SQLite PRAGMA WAL mode fallback: %s", e)
        try:
            conn.execute("PRAGMA journal_mode=DELETE;")
            conn.execute("PRAGMA busy_timeout=60000;")
        except Exception:
            pass
    return conn


_tick_write_counter = 0


def checkpoint_wal(force=False):
    """Performs a passive WAL checkpoint to optimize SQLite database size and flush log entries."""
    global _tick_write_counter
    try:
        # Rollover counter bounded at 1,000,000 to prevent unbounded integer growth over 24x7 periods (Round 2 FLAW-001)
        _tick_write_counter = (_tick_write_counter + 1) % 1000000
        if force or (_tick_write_counter % 100 == 0):
            conn = get_connection()
            conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
            conn.close()
            if force or (_tick_write_counter % 1000 == 0):
                print(
                    f"🧹 SQLite WAL Checkpoint executed at write count {_tick_write_counter}."
                )
        return True
    except Exception as e:
        print(f"⚠️ WAL Checkpoint note: {e}")
        return False


def init_db():
    """Initializes database tables if they do not exist."""
    max_retries = 5
    for attempt in range(max_retries):
        try:
            conn = get_connection()
            cursor = conn.cursor()

            # Table for storing market assessments made by the brain
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                trend_direction TEXT,
                rsi_val REAL,
                atr_val REAL,
                decision TEXT NOT NULL,
                explanation TEXT NOT NULL
            )
            """)

            # Table for storing all trades taken
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket TEXT UNIQUE,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL, -- 'BUY' or 'SELL'
                open_price REAL NOT NULL,
                open_time TEXT NOT NULL,
                sl REAL NOT NULL,
                tp REAL NOT NULL,
                lot_size REAL NOT NULL,
                status TEXT NOT NULL, -- 'OPEN', 'CLOSED'
                close_price REAL,
                close_time TEXT,
                profit REAL,
                close_reason TEXT, -- 'SL', 'TP', 'MANUAL', 'DAILY_LIMIT'
                strategy TEXT DEFAULT '',
                method TEXT DEFAULT ''
            )
            """)

            # Alter table if existing schema lacks strategy or method columns
            for col_def in [("strategy TEXT DEFAULT ''", "strategy"), ("method TEXT DEFAULT ''", "method"), ("product TEXT DEFAULT ''", "product")]:
                try:
                    cursor.execute(f"ALTER TABLE trades ADD COLUMN {col_def[0]}")
                except sqlite3.OperationalError:
                    pass

            # Table for performance metrics tracker
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS performance_metrics (
                date TEXT PRIMARY KEY,
                initial_balance REAL NOT NULL,
                final_balance REAL NOT NULL,
                trades_taken INTEGER DEFAULT 0,
                win_rate REAL DEFAULT 0.0,
                net_profit REAL DEFAULT 0.0
            )
            """)

            # Table for news sentiment indexing
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                headline TEXT NOT NULL,
                sentiment TEXT NOT NULL -- 'BULLISH', 'BEARISH', 'NEUTRAL'
            )
            """)

            # Table for storing user access accounts with cryptographic hash credentials
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                pin_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'SOVEREIGN_ADMIN',
                mfa_enabled INTEGER DEFAULT 1,
                login_style TEXT DEFAULT 'MATRIX_NEON',
                created_at TEXT NOT NULL
            )
            """)

            # Alter table if existing schema lacks login_style
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN login_style TEXT DEFAULT 'MATRIX_NEON'")
            except sqlite3.OperationalError:
                pass

            # Table for storing broker gateway connection details with encrypted secrets
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS broker_credentials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                broker_name TEXT DEFAULT 'PRIMARY GATEWAY',
                server TEXT NOT NULL,
                account_id TEXT NOT NULL,
                password_encrypted TEXT NOT NULL,
                leverage TEXT NOT NULL,
                environment TEXT DEFAULT 'Demo',
                protocol_type TEXT DEFAULT 'MT5',
                api_key_encrypted TEXT DEFAULT '',
                api_secret_encrypted TEXT DEFAULT '',
                rest_url TEXT DEFAULT '',
                ws_url TEXT DEFAULT '',
                terminal_path TEXT DEFAULT '',
                is_active INTEGER DEFAULT 1,
                updated_at TEXT NOT NULL
            )
            """)

            # Table for persisting daily circuit breaker state across process restarts
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS circuit_breaker_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                trading_date TEXT NOT NULL,
                daily_start_balance REAL NOT NULL,
                is_halted INTEGER NOT NULL DEFAULT 0,
                halt_timestamp TEXT,
                halt_reason TEXT,
                updated_at TEXT NOT NULL
            )
            """)
            
            # Migrate legacy schema: rename api_key to api_key_encrypted and api_secret to api_secret_encrypted
            try:
                cursor.execute("SELECT api_key FROM broker_credentials LIMIT 1")
                # If we get here, old schema exists - need to migrate
                _log.info("Migrating broker_credentials schema to encrypt api_key field")
                cursor.execute("ALTER TABLE broker_credentials RENAME COLUMN api_key TO api_key_encrypted")
            except sqlite3.OperationalError:
                # New schema already in place or table doesn't exist yet
                pass

            try:
                cursor.execute("ALTER TABLE broker_credentials RENAME COLUMN api_secret TO api_secret_encrypted")
            except sqlite3.OperationalError:
                pass

            # Alter table if existing schema lacks new multi-broker columns
            _SCHEMA_ALTERS = [
                (
                    "ALTER TABLE broker_credentials ADD COLUMN broker_name TEXT DEFAULT 'PRIMARY GATEWAY'",
                    "broker_name",
                ),
                (
                    "ALTER TABLE broker_credentials ADD COLUMN environment TEXT DEFAULT 'Demo'",
                    "environment",
                ),
                (
                    "ALTER TABLE broker_credentials ADD COLUMN is_active INTEGER DEFAULT 1",
                    "is_active",
                ),
                (
                    "ALTER TABLE broker_credentials ADD COLUMN protocol_type TEXT DEFAULT 'MT5'",
                    "protocol_type",
                ),
                (
                    "ALTER TABLE broker_credentials ADD COLUMN api_key TEXT DEFAULT ''",
                    "api_key",
                ),
                (
                    "ALTER TABLE broker_credentials ADD COLUMN api_secret TEXT DEFAULT ''",
                    "api_secret",
                ),
                (
                    "ALTER TABLE broker_credentials ADD COLUMN rest_url TEXT DEFAULT ''",
                    "rest_url",
                ),
                ("ALTER TABLE broker_credentials ADD COLUMN ws_url TEXT DEFAULT ''", "ws_url"),
                (
                    "ALTER TABLE broker_credentials ADD COLUMN terminal_path TEXT DEFAULT ''",
                    "terminal_path",
                ),
            ]
            for _sql, _col in _SCHEMA_ALTERS:
                try:
                    cursor.execute(_sql)
                except sqlite3.OperationalError:
                    # Column already exists — expected when migrating existing DBs
                    _log.debug("Schema column %s already present, skipping.", _col)

            # Prepopulate default admin operator account if empty
            cursor.execute("SELECT COUNT(*) FROM users")
            if cursor.fetchone()[0] == 0:
                cursor.execute(
                    """
                INSERT OR IGNORE INTO users (username, password_hash, pin_hash, role, mfa_enabled, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (
                        "QUANT_OPERATOR",
                        hash_credential_secure("admin"),
                        hash_credential_secure("741295"),
                        "SOVEREIGN_ADMIN",
                        1,
                        datetime.datetime.now().isoformat(),
                    ),
                )

            # SECURITY: Do not prepopulate broker credentials with hardcoded values
            # Users must explicitly configure broker credentials via add_broker_account()
            # or save_broker_credentials() to ensure deployment-specific secret provisioning
            # This implements fail-closed behavior as required by security policy

            conn.commit()
            conn.close()
            return
        except Exception as e:
            _log.warning("init_db attempt %d failed: %s", attempt + 1, e)
            if attempt < max_retries - 1:
                time.sleep(0.1 * (2**attempt))
            else:
                _log.error("init_db retry exhausted: %s", e)


def verify_user_password(username, password_input):
    """
    Verifies a user's password against the stored hash in SQLite (case-insensitive username).
    
    Supports both legacy SHA-256 and modern bcrypt hashes. Automatically upgrades
    legacy hashes to bcrypt upon successful authentication (transparent migration).
    
    Returns:
        bool: True if password is valid, False otherwise
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT password_hash FROM users WHERE LOWER(username) = LOWER(?)", (username,)
    )
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return False
    
    stored_hash = row["password_hash"]
    is_valid, needs_rehash = verify_credential(password_input, stored_hash)
    
    # Automatic migration: upgrade legacy hash to bcrypt on successful login
    if is_valid and needs_rehash:
        try:
            new_hash = hash_credential_secure(password_input)
            cursor.execute(
                "UPDATE users SET password_hash = ? WHERE LOWER(username) = LOWER(?)",
                (new_hash, username)
            )
            conn.commit()
            _log.info("Upgraded password hash to bcrypt for user: %s", username)
        except Exception as e:
            _log.warning("Failed to upgrade password hash for %s: %s", username, e)
    
    conn.close()
    return is_valid


def verify_user_credentials(username, password_input, pin_input=None):
    """
    Validates a user's login credentials (username, password, and optional PIN/MFA)
    against stored hashes in SQLite database.
    
    Supports both legacy SHA-256 and modern bcrypt hashes with automatic migration
    to bcrypt upon successful authentication. Each credential is verified independently
    and upgraded if needed.
    
    Args:
        username: User account name (case-insensitive)
        password_input: Plaintext password to verify
        pin_input: Optional plaintext PIN for MFA verification
        
    Returns:
        bool: True if authentication succeeds, False otherwise
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT password_hash, pin_hash FROM users WHERE LOWER(username) = LOWER(?)",
        (username,),
    )
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return False

    # Verify password with automatic migration
    stored_password_hash = row["password_hash"]
    pwd_valid, pwd_needs_rehash = verify_credential(password_input, stored_password_hash)
    
    if not pwd_valid:
        conn.close()
        return False
    
    # Upgrade password hash if needed
    if pwd_needs_rehash:
        try:
            new_hash = hash_credential_secure(password_input)
            cursor.execute(
                "UPDATE users SET password_hash = ? WHERE LOWER(username) = LOWER(?)",
                (new_hash, username)
            )
            conn.commit()
            _log.info("Upgraded password hash to bcrypt for user: %s", username)
        except Exception as e:
            _log.warning("Failed to upgrade password hash for %s: %s", username, e)

    # Verify PIN if provided
    if pin_input is not None and str(pin_input).strip():
        typed_pin = str(pin_input).strip()
        stored_pin_hash = row["pin_hash"]
        pin_valid, pin_needs_rehash = verify_credential(typed_pin, stored_pin_hash)
        
        # Upgrade PIN hash if needed
        if pin_valid and pin_needs_rehash:
            try:
                new_pin_hash = hash_credential_secure(typed_pin)
                cursor.execute(
                    "UPDATE users SET pin_hash = ? WHERE LOWER(username) = LOWER(?)",
                    (new_pin_hash, username)
                )
                conn.commit()
                _log.info("Upgraded PIN hash to bcrypt for user: %s", username)
            except Exception as e:
                _log.warning("Failed to upgrade PIN hash for %s: %s", username, e)
        
        conn.close()
        return pin_valid

    conn.close()
    return True


def verify_user_pin(pin_input):
    """
    Verifies a secondary security PIN against active operators in SQLite.
    
    Supports both legacy SHA-256 and modern bcrypt hashes. Note: This function
    checks against all users' PINs and does not perform automatic migration
    since it doesn't identify a specific user.
    
    Returns:
        bool: True if PIN matches any user's stored PIN hash
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT pin_hash FROM users")
    rows = cursor.fetchall()
    conn.close()

    # Check against all stored PIN hashes
    for row in rows:
        stored_hash = row["pin_hash"]
        is_valid, _ = verify_credential(pin_input, stored_hash)
        if is_valid:
            return True
    
    return False


def get_all_users():
    """Retrieves all registered user profiles."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, username, role, mfa_enabled, created_at FROM users ORDER BY id ASC"
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


import time


def _execute_with_retry(query, params=(), commit=True):
    """Executes a database write query using connection context manager with automatic retries and exponential backoff."""
    max_retries = 5
    for attempt in range(max_retries):
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                if commit:
                    conn.commit()
            return True
        except sqlite3.IntegrityError as e:
            # IntegrityError indicates constraint violation (e.g., duplicate ticket, UNIQUE constraint)
            # This is not a transient error and should not be retried
            _log.error(
                "Database integrity constraint violation: %s. Query: %s, Params: %s",
                e,
                query[:100],  # Log first 100 chars of query for diagnostics
                params if len(str(params)) < 200 else str(params)[:200] + "..."
            )
            return False
        except sqlite3.OperationalError as e:
            if "no such table" in str(e).lower():
                init_db()
                try:
                    with get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute(query, params)
                        if commit:
                            conn.commit()
                    return True
                except Exception:
                    pass
            if attempt < max_retries - 1:
                time.sleep(0.1 * (2**attempt))
            else:
                _log.debug("Database write retry exhausted: %s", e)
                return False


def _fetch_with_retry(query, params=(), fetch_all=True):
    """Executes a database read query using connection context manager with automatic retries and exponential backoff."""
    max_retries = 5
    for attempt in range(max_retries):
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                res = cursor.fetchall() if fetch_all else cursor.fetchone()
            return res
        except sqlite3.OperationalError as e:
            if "no such table" in str(e).lower():
                init_db()
                try:
                    with get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute(query, params)
                        res = cursor.fetchall() if fetch_all else cursor.fetchone()
                    return res
                except Exception:
                    pass
            if attempt < max_retries - 1:
                time.sleep(0.1 * (2**attempt))
            else:
                _log.debug("Database read retry exhausted: %s", e)
                return [] if fetch_all else None


def add_user(username, password, pin, role="QUANT_TRADER", mfa_enabled=1):
    """
    Adds a new operator account with cryptographically secure bcrypt-hashed password and PIN.
    
    Uses bcrypt with per-credential random salts and configurable work factor (12 rounds)
    to protect against offline brute-force attacks. Each credential receives a unique
    salt automatically embedded in the bcrypt hash.
    
    Args:
        username: Unique username for the account
        password: Plaintext password (will be hashed with bcrypt)
        pin: Plaintext PIN (will be hashed with bcrypt)
        role: User role (default: QUANT_TRADER)
        mfa_enabled: Whether MFA is enabled (default: 1/True)
    """
    query = """
    INSERT INTO users (username, password_hash, pin_hash, role, mfa_enabled, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """
    params = (
        username,
        hash_credential_secure(password),
        hash_credential_secure(pin),
        role,
        int(mfa_enabled),
        datetime.datetime.now().isoformat(),
    )
    _execute_with_retry(query, params)


def update_user(username, new_password=None, new_pin=None, new_role=None, original_username=None, login_style=None):
    """
    Updates username, password, PIN, role, or login_style for an existing user account.
    
    Password and PIN updates use cryptographically secure bcrypt hashing with unique
    per-credential random salts and 12-round work factor. This replaces any legacy
    SHA-256 hashes with modern bcrypt hashes.
    
    Args:
        username: New username (if changing username)
        new_password: New plaintext password (will be hashed with bcrypt)
        new_pin: New plaintext PIN (will be hashed with bcrypt)
        new_role: New role assignment
        original_username: Original username (if changing username)
        login_style: Preferred login screen style
    """
    target_user = original_username if original_username else username

    if username and target_user and username.lower() != target_user.lower():
        _execute_with_retry(
            "UPDATE users SET username = ? WHERE LOWER(username) = LOWER(?)",
            (username, target_user),
        )
        target_user = username

    if new_password is not None and str(new_password).strip():
        _execute_with_retry(
            "UPDATE users SET password_hash = ? WHERE LOWER(username) = LOWER(?)",
            (hash_credential_secure(str(new_password).strip()), target_user),
        )
    if new_pin is not None and str(new_pin).strip():
        _execute_with_retry(
            "UPDATE users SET pin_hash = ? WHERE LOWER(username) = LOWER(?)",
            (hash_credential_secure(str(new_pin).strip()), target_user),
        )
    if new_role is not None and str(new_role).strip():
        _execute_with_retry(
            "UPDATE users SET role = ? WHERE LOWER(username) = LOWER(?)",
            (str(new_role).strip(), target_user),
        )
    if login_style is not None and str(login_style).strip():
        _execute_with_retry(
            "UPDATE users SET login_style = ? WHERE LOWER(username) = LOWER(?)",
            (str(login_style).strip(), target_user),
        )


def get_credential_migration_status():
    """
    Returns the migration status of user credentials from legacy SHA-256 to bcrypt.
    
    This diagnostic function helps administrators understand which users still have
    legacy hashes that need migration. Migration happens automatically on next login,
    but this function provides visibility into the migration progress.
    
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
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash, pin_hash FROM users")
    rows = cursor.fetchall()
    conn.close()
    
    total = len(rows)
    bcrypt_passwords = 0
    legacy_passwords = 0
    bcrypt_pins = 0
    legacy_pins = 0
    
    for row in rows:
        # Check password hash format
        pwd_hash = row["password_hash"]
        if pwd_hash and pwd_hash.startswith(('$2a$', '$2b$', '$2y$')):
            bcrypt_passwords += 1
        else:
            legacy_passwords += 1
        
        # Check PIN hash format
        pin_hash = row["pin_hash"]
        if pin_hash and pin_hash.startswith(('$2a$', '$2b$', '$2y$')):
            bcrypt_pins += 1
        else:
            legacy_pins += 1
    
    return {
        'total_users': total,
        'bcrypt_passwords': bcrypt_passwords,
        'legacy_passwords': legacy_passwords,
        'bcrypt_pins': bcrypt_pins,
        'legacy_pins': legacy_pins,
        'migration_complete': (legacy_passwords == 0 and legacy_pins == 0)
    }


def get_user_login_style(username="QUANT_OPERATOR"):
    """Retrieves the preferred login screen style for a user."""
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT login_style FROM users WHERE LOWER(username) = LOWER(?)", (username,))
        row = cursor.fetchone()
        conn.close()
        if row and row["login_style"]:
            return row["login_style"]
    except Exception:
        pass
    return "MATRIX_NEON"


def delete_user(username):
    """Deletes a user account from SQLite with lock retries."""
    _execute_with_retry("DELETE FROM users WHERE username = ?", (username,))


def get_all_brokers():
    """Retrieves all registered broker profiles from SQLite."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM broker_credentials ORDER BY id ASC")
        rows = cursor.fetchall()
        conn.close()
    except sqlite3.OperationalError:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM broker_credentials ORDER BY id ASC")
        rows = cursor.fetchall()
        conn.close()

    brokers = []
    for r in rows:
        b = dict(r)
        b["password"] = decrypt_secret(b.get("password_encrypted", ""))
        
        # Handle both old schema (api_key) and new schema (api_key_encrypted)
        keys = r.keys() if hasattr(r, "keys") else []
        if "api_key_encrypted" in keys:
            b["api_key"] = decrypt_secret(b.get("api_key_encrypted", ""))
        elif "api_key" in keys:
            # Legacy plaintext field - keep as is for now
            b["api_key"] = b.get("api_key", "")
        else:
            b["api_key"] = ""
            
        if "api_secret_encrypted" in keys:
            b["api_secret"] = decrypt_secret(b.get("api_secret_encrypted", ""))
        elif "api_secret" in keys:
            # Legacy field - might be encrypted with old XOR
            b["api_secret"] = decrypt_secret(b.get("api_secret", ""))
        else:
            b["api_secret"] = ""
        
        brokers.append(b)
    return brokers


def normalize_leverage(leverage_str: str) -> str:
    """
    Normalizes leverage string input into standard '1:N' format.
    E.g. '1:888' -> '1:888', '888' -> '1:888', '1:10000' -> '1:10000'.
    Fallback to '1:100' if invalid or unparseable.
    """
    if not leverage_str:
        return "1:100"
    s = str(leverage_str).strip()
    if ":" in s:
        parts = s.split(":")
        if len(parts) == 2 and parts[1].isdigit() and int(parts[1]) > 0:
            return f"1:{int(parts[1])}"
    elif s.isdigit() and int(s) > 0:
        return f"1:{int(s)}"
    return "1:100"


def validate_terminal_path(terminal_path: str) -> str:
    """
    Validates and sanitizes MT5 terminal executable path to prevent arbitrary code execution.
    
    SECURITY: This function enforces strict validation to prevent database-controlled
    terminal paths from selecting arbitrary executables. Only legitimate MT5 terminal
    executables in standard installation directories are permitted.
    
    Validation rules:
    1. Path must end with 'terminal64.exe' or 'terminal.exe' (case-insensitive)
    2. Path must be an absolute path (not relative)
    3. Path must not contain directory traversal sequences (..)
    4. If the file exists, it must be a regular file (not a directory or symlink)
    5. Path must be within common MT5 installation directories or explicitly allowed paths
    
    Args:
        terminal_path: The terminal path to validate
        
    Returns:
        str: Validated and normalized terminal path, or empty string if invalid
        
    Raises:
        ValueError: If the path fails validation checks
    """
    if not terminal_path or not str(terminal_path).strip():
        return ""
    
    path_str = str(terminal_path).strip()
    
    # Normalize path separators and resolve to absolute path
    try:
        import pathlib
        if '\\' in path_str or (len(path_str) > 1 and path_str[1] == ':'):
            path_obj = pathlib.PureWindowsPath(path_str)
        else:
            path_obj = pathlib.Path(path_str)
        
        # Check 1: Must end with terminal64.exe or terminal.exe (case-insensitive)
        filename_lower = path_obj.name.lower()
        if filename_lower not in ('terminal64.exe', 'terminal.exe', 'terminal64', 'terminal'):
            _log.warning(
                "Terminal path validation failed: filename must be 'terminal64.exe' or 'terminal.exe', got '%s'",
                path_obj.name
            )
            raise ValueError(f"Invalid MT5 terminal filename: {path_obj.name}")
        
        # Check 2: Must be absolute path (not relative)
        if not path_obj.is_absolute():
            _log.warning(
                "Terminal path validation failed: path must be absolute, got '%s'",
                path_str
            )
            raise ValueError("Terminal path must be an absolute path")
        
        # Check 3: Must not contain directory traversal sequences
        if hasattr(path_obj, "resolve"):
            normalized_str = str(path_obj.resolve())
        else:
            normalized_str = str(path_obj)

        if ".." in path_str or ".." in normalized_str:
            _log.warning(
                "Terminal path validation failed: directory traversal detected in '%s'",
                path_str,
            )
            raise ValueError("Terminal path must not contain directory traversal sequences")

        # Check 4: If file exists, verify it's a regular file
        if hasattr(path_obj, "exists") and path_obj.exists():
            if not path_obj.is_file():
                _log.warning(
                    "Terminal path validation failed: path exists but is not a regular file: '%s'",
                    normalized_str,
                )
                raise ValueError("Terminal path must point to a regular file")

            # Additional check: resolve symlinks and verify final target
            try:
                resolved_path = path_obj.resolve(strict=True)
                resolved_filename = resolved_path.name.lower()
                if resolved_filename not in ("terminal64.exe", "terminal.exe", "terminal64", "terminal"):
                    _log.warning(
                        "Terminal path validation failed: resolved path does not point to MT5 terminal: '%s'",
                        str(resolved_path),
                    )
                    raise ValueError("Resolved terminal path does not point to a valid MT5 terminal executable")
            except Exception as e:
                _log.warning(
                    "Terminal path validation failed: could not resolve path '%s': %s",
                    path_str,
                    e
                )
                raise ValueError(f"Could not resolve terminal path: {e}")
        
        # Check 5: Path must be in approved directories (common MT5 installation locations)
        # This is a defense-in-depth measure - we check common installation paths
        normalized_lower = normalized_str.lower()
        
        # Common MT5 installation directories (Windows)
        approved_patterns = [
            'program files',
            'program files (x86)',
            'programdata',
            'users',
            'mt5',
            'metatrader',
            'metatrader 5',
            'alpari',
            'roboforex',
            'xm',
            'fxpro',
            'ic markets',
            'pepperstone',
            'oanda',
            'forex.com',
            'fxcm',
        ]
        
        # Check if path contains any approved pattern
        path_approved = any(pattern in normalized_lower for pattern in approved_patterns)
        
        if not path_approved:
            _log.warning(
                "Terminal path validation warning: path '%s' is not in a recognized MT5 installation directory. "
                "This may be legitimate for custom installations, but could indicate a security issue.",
                normalized_str
            )
            # Log warning but don't reject - some users may have custom installation paths
            # The filename and file type checks above are the primary security controls
        
        # Return the normalized absolute path
        return normalized_str
        
    except ValueError:
        # Re-raise validation errors
        raise
    except Exception as e:
        _log.error(
            "Terminal path validation failed with unexpected error for '%s': %s",
            path_str,
            e
        )
        raise ValueError(f"Terminal path validation error: {e}")


def add_broker_account(
    broker_name,
    server,
    account_id,
    password,
    leverage="1:100",
    environment="Demo",
    protocol_type="MT5",
    api_key="",
    api_secret="",
    rest_url="",
    ws_url="",
    terminal_path="",
    is_active=0,
):
    """
    Adds a new broker gateway configuration into SQLite with lock retries.
    
    SECURITY: Validates terminal_path to prevent arbitrary executable selection.
    Only legitimate MT5 terminal executables are permitted.
    """
    leverage = normalize_leverage(leverage)
    
    # SECURITY: Validate terminal_path before persisting to database
    validated_terminal_path = ""
    if terminal_path and str(terminal_path).strip():
        try:
            validated_terminal_path = validate_terminal_path(terminal_path)
            _log.info("Terminal path validated successfully: %s", validated_terminal_path)
        except ValueError as e:
            _log.error(
                "Terminal path validation failed for add_broker_account: %s. "
                "Terminal path will be cleared for security. Error: %s",
                terminal_path,
                e
            )
            # Clear invalid terminal path rather than rejecting the entire operation
            # This allows the broker account to be added with other valid credentials
            validated_terminal_path = ""
    
    if is_active:
        _execute_with_retry("UPDATE broker_credentials SET is_active = 0")
    _execute_with_retry(
        """
    INSERT INTO broker_credentials (broker_name, server, account_id, password_encrypted, leverage, environment, protocol_type, api_key_encrypted, api_secret_encrypted, rest_url, ws_url, terminal_path, is_active, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            broker_name,
            server,
            account_id,
            encrypt_secret(password),
            leverage,
            environment,
            protocol_type,
            encrypt_secret(api_key) if api_key else "",
            encrypt_secret(api_secret) if api_secret else "",
            rest_url,
            ws_url,
            validated_terminal_path,
            1 if is_active else 0,
            datetime.datetime.now().isoformat(),
        ),
    )


def set_active_broker(broker_id):
    """Sets a specific broker account as the active primary gateway with lock retries."""
    _execute_with_retry("UPDATE broker_credentials SET is_active = 0")
    _execute_with_retry(
        "UPDATE broker_credentials SET is_active = 1 WHERE id = ?", (broker_id,)
    )


def delete_broker_account(broker_id):
    """Deletes a broker profile from SQLite with lock retries."""
    _execute_with_retry("DELETE FROM broker_credentials WHERE id = ?", (broker_id,))


def save_broker_credentials(
    server,
    account_id,
    password,
    leverage,
    broker_name="Primary Gateway",
    environment="Demo",
    protocol_type="MT5",
    api_key="",
    api_secret="",
    rest_url="",
    ws_url="",
    terminal_path="",
):
    """
    Saves or updates primary active broker parameters in SQLite with lock retries.
    
    SECURITY: Validates terminal_path to prevent arbitrary executable selection.
    Only legitimate MT5 terminal executables are permitted.
    """
    leverage = normalize_leverage(leverage)
    
    # SECURITY: Validate terminal_path before persisting to database
    validated_terminal_path = ""
    if terminal_path and str(terminal_path).strip():
        try:
            validated_terminal_path = validate_terminal_path(terminal_path)
            _log.info("Terminal path validated successfully: %s", validated_terminal_path)
        except ValueError as e:
            _log.error(
                "Terminal path validation failed for save_broker_credentials: %s. "
                "Terminal path will be cleared for security. Error: %s",
                terminal_path,
                e
            )
            # Clear invalid terminal path rather than rejecting the entire operation
            # This allows the broker credentials to be saved with other valid data
            validated_terminal_path = ""
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM broker_credentials WHERE is_active = 1 ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()

    enc_pwd = encrypt_secret(password)
    enc_key = encrypt_secret(api_key) if api_key else ""
    enc_secret = encrypt_secret(api_secret) if api_secret else ""

    if row:
        _execute_with_retry(
            """
        UPDATE broker_credentials
        SET broker_name = ?, server = ?, account_id = ?, password_encrypted = ?, leverage = ?, environment = ?, protocol_type = ?, api_key_encrypted = ?, api_secret_encrypted = ?, rest_url = ?, ws_url = ?, terminal_path = ?, is_active = 1, updated_at = ?
        WHERE id = ?
        """,
            (
                broker_name,
                server,
                account_id,
                enc_pwd,
                leverage,
                environment,
                protocol_type,
                enc_key,
                enc_secret,
                rest_url,
                ws_url,
                validated_terminal_path,
                datetime.datetime.now().isoformat(),
                row["id"],
            ),
        )
    else:
        _execute_with_retry("UPDATE broker_credentials SET is_active = 0")
        _execute_with_retry(
            """
        INSERT INTO broker_credentials (broker_name, server, account_id, password_encrypted, leverage, environment, protocol_type, api_key_encrypted, api_secret_encrypted, rest_url, ws_url, terminal_path, is_active, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """,
            (
                broker_name,
                server,
                account_id,
                enc_pwd,
                leverage,
                environment,
                protocol_type,
                enc_key,
                enc_secret,
                rest_url,
                ws_url,
                validated_terminal_path,
                datetime.datetime.now().isoformat(),
            ),
        )


def get_broker_credentials():
    """
    Retrieves active broker connection parameters and decrypts secrets.
    
    SECURITY: Implements fail-closed behavior. Returns None when no credentials
    are configured, requiring explicit deployment-specific secret provisioning.
    Callers must handle None return value and fail safely.
    
    Returns:
        dict: Broker credentials with decrypted secrets, or None if not configured
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM broker_credentials WHERE is_active = 1 ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        if not row:
            cursor.execute("SELECT * FROM broker_credentials ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
        conn.close()
        conn = None
    except sqlite3.OperationalError:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
            conn = None
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM broker_credentials WHERE is_active = 1 ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        if not row:
            cursor.execute("SELECT * FROM broker_credentials ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
        conn.close()

    if not row:
        # SECURITY: Fail-closed behavior - do not return hardcoded credentials
        # Users must explicitly configure broker credentials before connecting
        _log.error(
            "No broker credentials configured in database. "
            "Please configure credentials using add_broker_account() or save_broker_credentials() "
            "before attempting to connect to a broker."
        )
        return None

    keys = row.keys() if hasattr(row, "keys") else []
    
    # Handle both old schema (api_key) and new schema (api_key_encrypted)
    api_key_field = "api_key_encrypted" if "api_key_encrypted" in keys else "api_key"
    api_secret_field = "api_secret_encrypted" if "api_secret_encrypted" in keys else "api_secret"
    
    # Decrypt api_key if it's in the encrypted field, otherwise use plaintext (legacy)
    if api_key_field == "api_key_encrypted" and row[api_key_field]:
        api_key_value = decrypt_secret(row[api_key_field])
    elif api_key_field == "api_key" and row[api_key_field]:
        # Legacy plaintext - encrypt it on next save
        api_key_value = row[api_key_field]
    else:
        api_key_value = ""
    
    # Decrypt api_secret
    if api_secret_field == "api_secret_encrypted" and row[api_secret_field]:
        api_secret_value = decrypt_secret(row[api_secret_field])
    elif api_secret_field == "api_secret" and row[api_secret_field]:
        # Legacy - might be encrypted with old XOR or plaintext
        api_secret_value = decrypt_secret(row[api_secret_field]) if row[api_secret_field] else ""
    else:
        api_secret_value = ""
    
    # SECURITY: Return actual database values without hardcoded fallbacks
    # Empty/missing fields return empty strings, not hardcoded demo credentials
    return {
        "broker_name": row["broker_name"]
        if "broker_name" in keys and row["broker_name"]
        else "Primary Gateway",
        "server": row["server"] if "server" in keys and row["server"] else "",
        "account_id": row["account_id"] if "account_id" in keys and row["account_id"] else "",
        "password": decrypt_secret(row["password_encrypted"])
        if "password_encrypted" in keys and row["password_encrypted"]
        else "",
        "leverage": row["leverage"] if "leverage" in keys else "1:100",
        "environment": row["environment"]
        if "environment" in keys and row["environment"]
        else "Demo",
        "protocol_type": row["protocol_type"]
        if "protocol_type" in keys and row["protocol_type"]
        else "MT5",
        "api_key": api_key_value,
        "api_secret": api_secret_value,
        "rest_url": row["rest_url"] if "rest_url" in keys and row["rest_url"] else "",
        "ws_url": row["ws_url"] if "ws_url" in keys and row["ws_url"] else "",
        "terminal_path": row["terminal_path"]
        if "terminal_path" in keys and row["terminal_path"]
        else "",
    }


def log_assessment(symbol, trend_direction, rsi_val, atr_val, decision, explanation):
    """Logs an analysis assessment made by the brain with lock retries."""
    _execute_with_retry(
        """
    INSERT INTO assessments (timestamp, symbol, trend_direction, rsi_val, atr_val, decision, explanation)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
        (
            datetime.datetime.now().isoformat(),
            symbol,
            trend_direction,
            rsi_val,
            atr_val,
            decision,
            explanation,
        ),
    )


def log_trade_open(ticket, symbol, direction, open_price, sl, tp, lot_size, strategy="", method="", product=""):
    """
    Logs the initiation of a trade with lock retries.
    
    Returns:
        bool: True if trade was successfully logged, False if database write failed
              (e.g., due to duplicate ticket constraint violation)
    """
    # Validate ticket is non-empty before attempting database write
    if not ticket or str(ticket).strip() == "":
        _log.error(
            "log_trade_open: Rejected attempt to log trade with empty ticket. "
            "Symbol: %s, Direction: %s, Price: %s",
            symbol,
            direction,
            open_price
        )
        return False
    
    result = _execute_with_retry(
        """
    INSERT INTO trades (ticket, symbol, direction, open_price, open_time, sl, tp, lot_size, status, strategy, method, product)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            str(ticket),
            symbol,
            direction,
            open_price,
            datetime.datetime.now().isoformat(),
            sl,
            tp,
            lot_size,
            "OPEN",
            strategy,
            method,
            product,
        ),
    )
    
    if not result:
        _log.error(
            "log_trade_open: Failed to log trade to database. "
            "Ticket: %s, Symbol: %s, Direction: %s, Price: %s. "
            "This may indicate a duplicate ticket or database constraint violation.",
            ticket,
            symbol,
            direction,
            open_price
        )
    
    return result


def log_trade_close(ticket, close_price, profit, reason):
    """Updates the trade record when a trade is closed with lock retries."""
    _execute_with_retry(
        """
    UPDATE trades
    SET status = 'CLOSED', close_price = ?, close_time = ?, profit = ?, close_reason = ?
    WHERE ticket = ?
    """,
        (close_price, datetime.datetime.now().isoformat(), profit, reason, str(ticket)),
    )


def get_open_trades():
    """Returns all open trades, auto-initializing database if table does not exist."""
    init_db()
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM trades WHERE status = 'OPEN'")
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        _log.debug("get_open_trades error: %s", e)
        return []


def log_news_headline(headline, sentiment):
    """Logs a macro headline with its parsed sentiment classification with lock retries."""
    _execute_with_retry(
        """
    INSERT INTO news (timestamp, headline, sentiment)
    VALUES (?, ?, ?)
    """,
        (datetime.datetime.now().isoformat(), headline, sentiment.upper()),
    )


def get_prevailing_news_sentiment():
    """
    Computes prevailing sentiment across recent news headlines,
    auto-initializing database if table does not exist.
    Returns: 'BULLISH' | 'BEARISH' | 'NEUTRAL'
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT sentiment FROM news ORDER BY timestamp DESC LIMIT 15")
        rows = cursor.fetchall()
        conn.close()
    except sqlite3.OperationalError:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT sentiment FROM news ORDER BY timestamp DESC LIMIT 15")
        rows = cursor.fetchall()
        conn.close()

    if not rows:
        return "NEUTRAL"

    sentiments = [r["sentiment"] for r in rows]
    bullish_count = sentiments.count("BULLISH")
    bearish_count = sentiments.count("BEARISH")

    if bullish_count > bearish_count:
        return "BULLISH"
    elif bearish_count > bullish_count:
        return "BEARISH"
    else:
        return "NEUTRAL"


def get_recent_performance(count=5):
    """Retrieves the last N closed trades to analyze performance trends."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT profit FROM trades
            WHERE status = 'CLOSED'
            ORDER BY close_time DESC
            LIMIT ?
        """,
            (count,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except sqlite3.OperationalError:
        init_db()
        return []


def get_daily_profit(date_str=None):
    """Calculates total profits for closed trades on a specific date (YYYY-MM-DD)."""
    if date_str is None:
        date_str = datetime.date.today().isoformat()

    conn = get_connection()
    cursor = conn.cursor()
    # Match the prefix of close_time with date_str
    cursor.execute(
        """
    SELECT SUM(profit) FROM trades
    WHERE status = 'CLOSED' AND close_time LIKE ?
    """,
        (f"{date_str}%",),
    )
    row = cursor.fetchone()
    profit = row[0] if row[0] is not None else 0.0
    conn.close()
    return profit


def update_performance_metrics(date_str, current_balance):
    """
    Autonomously analyzes trading performance for a specific date and
    upserts metrics into the performance_metrics table with lock retries.
    """
    rows = _fetch_with_retry(
        """
        SELECT profit FROM trades
        WHERE status = 'CLOSED' AND close_time LIKE ?
    """,
        (f"{date_str}%",),
        fetch_all=True,
    ) or []

    trades_taken = len(rows)
    net_profit = sum(row["profit"] for row in rows) if trades_taken > 0 else 0.0
    wins = sum(1 for row in rows if row["profit"] > 0)
    win_rate = (wins / trades_taken) * 100.0 if trades_taken > 0 else 0.0

    # Check if record exists
    exists_row = _fetch_with_retry("SELECT 1 FROM performance_metrics WHERE date = ?", (date_str,), fetch_all=False)
    exists = exists_row is not None

    if exists:
        _execute_with_retry(
            """
            UPDATE performance_metrics
            SET final_balance = ?, trades_taken = ?, win_rate = ?, net_profit = ?
            WHERE date = ?
        """,
            (current_balance, trades_taken, win_rate, net_profit, date_str),
        )
    else:
        _execute_with_retry(
            """
            INSERT INTO performance_metrics (date, initial_balance, final_balance, trades_taken, win_rate, net_profit)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (
                date_str,
                current_balance - net_profit,
                current_balance,
                trades_taken,
                win_rate,
                net_profit,
            ),
        )


def get_all_time_performance():
    """Computes all-time trading performance summary metrics."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT profit FROM trades
            WHERE status = 'CLOSED'
        """)
        rows = cursor.fetchall()
        conn.close()
    except sqlite3.OperationalError:
        init_db()
        rows = []

    total_trades = len(rows)
    net_profit = sum(row["profit"] for row in rows) if total_trades > 0 else 0.0
    wins = sum(1 for row in rows if row["profit"] > 0)
    win_rate = (wins / total_trades) * 100.0 if total_trades > 0 else 0.0

    return {
        "total_trades": total_trades,
        "win_rate": round(win_rate, 2),
        "net_profit": round(net_profit, 2),
    }


def get_all_trades():
    """Returns all trades (open and closed)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trades ORDER BY open_time DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def save_circuit_breaker_state(trading_date, daily_start_balance, is_halted=False, halt_reason=None):
    """
    Persists the daily circuit breaker state to SQLite for recovery across process restarts.
    
    This function ensures that the daily drawdown baseline and halt status survive
    supervisor restarts, crashes, maintenance restarts, or operator restarts.
    
    Args:
        trading_date: ISO format date string (YYYY-MM-DD)
        daily_start_balance: The account balance at the start of the trading day
        is_halted: Boolean indicating if the circuit breaker has been triggered
        halt_reason: Optional string describing why the circuit breaker was triggered
    """
    halt_timestamp = datetime.datetime.now().isoformat() if is_halted else None
    
    _execute_with_retry(
        """
        INSERT OR REPLACE INTO circuit_breaker_state 
        (id, trading_date, daily_start_balance, is_halted, halt_timestamp, halt_reason, updated_at)
        VALUES (1, ?, ?, ?, ?, ?, ?)
        """,
        (
            trading_date,
            daily_start_balance,
            1 if is_halted else 0,
            halt_timestamp,
            halt_reason or "",
            datetime.datetime.now().isoformat(),
        ),
    )


def load_circuit_breaker_state():
    """
    Loads the persisted circuit breaker state from SQLite.
    
    Returns a dictionary with:
        - trading_date: The date for which the state was saved
        - daily_start_balance: The baseline balance for drawdown calculations
        - is_halted: Boolean indicating if trading is halted
        - halt_timestamp: When the halt was triggered (if applicable)
        - halt_reason: Why the halt was triggered (if applicable)
    
    Returns None if no state exists in the database.
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM circuit_breaker_state WHERE id = 1")
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "trading_date": row["trading_date"],
                "daily_start_balance": row["daily_start_balance"],
                "is_halted": bool(row["is_halted"]),
                "halt_timestamp": row["halt_timestamp"],
                "halt_reason": row["halt_reason"],
            }
        return None
    except sqlite3.OperationalError:
        # Table doesn't exist yet - will be created by init_db
        return None


def clear_circuit_breaker_halt():
    """
    Clears the halt status while preserving the daily baseline.
    
    This should only be called by an operator who has manually reviewed
    the situation and decided to resume trading for the current day.
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT trading_date, daily_start_balance FROM circuit_breaker_state WHERE id = 1")
        row = cursor.fetchone()
        conn.close()
        
        if row:
            _execute_with_retry(
                """
                UPDATE circuit_breaker_state 
                SET is_halted = 0, halt_timestamp = NULL, halt_reason = NULL, updated_at = ?
                WHERE id = 1
                """,
                (datetime.datetime.now().isoformat(),),
            )
            return True
        return False
    except sqlite3.OperationalError:
        return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="EQATS Database Administrative CLI Utility")
    parser.add_argument("--reset-admin", action="store_true", help="Reset default QUANT_OPERATOR admin user")
    parser.add_argument("--username", type=str, default="QUANT_OPERATOR", help="Target username")
    parser.add_argument("--password", type=str, help="New password for user")
    parser.add_argument("--pin", type=str, help="New secondary MFA PIN for user")
    parser.add_argument("--role", type=str, default="SOVEREIGN_ADMIN", help="Role for user")

    args = parser.parse_args()
    init_db()

    if args.reset_admin or args.password or args.pin:
        target_user = args.username
        new_pass = args.password or "admin"
        new_pin = args.pin or "741295"
        update_user(target_user, new_password=new_pass, new_pin=new_pin, new_role=args.role)
        print("================================================================================")
        print("  EQATS LOCAL ADMINISTRATIVE RECOVERY TOOL")
        print("================================================================================")
        print(f"  User Credentials Updated for: '{target_user}'")
        print(f"  Password:                     '{new_pass}'")
        print(f"  Secondary MFA PIN:            '{new_pin}'")
        print(f"  Role:                         '{args.role}'")
        print("================================================================================")
    else:
        parser.print_help()
