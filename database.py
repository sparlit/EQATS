import sqlite3
import datetime
import hashlib
import hmac
import base64
import config
import os
from dotenv import load_dotenv
from secure_encryption import encrypt_text, decrypt_text, get_encryption_manager
from password_manager import get_password_manager, get_pin_manager
from mfa_manager import get_mfa_manager, get_mfa_storage
from input_validation import get_validator

# Load environment variables from .env file
load_dotenv()

def hash_credential(secret_text, salt=None, credential_type='password'):
    """
    Generates a secure hash for passwords and PINs using bcrypt.
    
    SECURITY: Upgraded from SHA-256 to bcrypt for password hashing.
    Bcrypt provides automatic salting and is resistant to rainbow table attacks.
    
    Args:
        secret_text: The credential to hash (password or PIN)
        salt: Legacy parameter for backward compatibility (ignored, bcrypt handles salting)
        credential_type: Type of credential ('password' or 'pin')
        
    Returns:
        Bcrypt hash (60 characters)
    """
    if not secret_text:
        secret_text = ""
    
    try:
        if credential_type == 'pin':
            # Use PIN manager for PINs (faster, optimized for short strings)
            pin_manager = get_pin_manager()
            return pin_manager.hash_pin(secret_text)
        else:
            # Use password manager for passwords (more secure)
            password_manager = get_password_manager()
            return password_manager.hash_password(secret_text)
    except Exception as e:
        print(f"ERROR: Failed to hash credential: {e}")
        # Fallback to empty string on error
        return ""


def verify_credential(secret_text, hashed_credential, credential_type='password'):
    """
    Verifies a credential against a bcrypt hash.
    
    Args:
        secret_text: The credential to verify
        hashed_credential: The bcrypt hash to verify against
        credential_type: Type of credential ('password' or 'pin')
        
    Returns:
        True if credential matches, False otherwise
    """
    if not secret_text or not hashed_credential:
        return False
    
    try:
        if credential_type == 'pin':
            pin_manager = get_pin_manager()
            return pin_manager.verify_pin(secret_text, hashed_credential)
        else:
            password_manager = get_password_manager()
            return password_manager.verify_password(secret_text, hashed_credential)
    except Exception as e:
        print(f"ERROR: Failed to verify credential: {e}")
        return False

def encrypt_secret(plain_text, key_seed=None):
    """
    Encrypts a string using AES-256-GCM encryption for broker passwords.
    
    SECURITY: Upgraded from weak XOR encryption to AES-256-GCM.
    
    Args:
        plain_text: The text to encrypt
        key_seed: Legacy parameter for backward compatibility (ignored)
        
    Returns:
        Base64-encoded AES-256-GCM encrypted string
    """
    if not plain_text:
        return ""
    
    try:
        return encrypt_text(plain_text)
    except Exception as e:
        print(f"ERROR: Encryption failed: {e}")
        # Fallback to empty string on error
        return ""

def decrypt_secret(cipher_text, key_seed=None):
    """
    Decrypts an AES-256-GCM encrypted string back to plaintext.
    
    SECURITY: Upgraded from weak XOR encryption to AES-256-GCM.
    
    Args:
        cipher_text: Base64-encoded encrypted string
        key_seed: Legacy parameter for backward compatibility (ignored)
        
    Returns:
        Decrypted plaintext, or empty string on failure
    """
    if not cipher_text:
        return ""
    
    try:
        return decrypt_text(cipher_text)
    except Exception as e:
        print(f"ERROR: Decryption failed: {e}")
        # Return empty string on failure for backward compatibility
        return ""

def get_connection():
    """Returns a connection to the SQLite database."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes database tables if they do not exist."""
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
        close_reason TEXT -- 'SL', 'TP', 'MANUAL', 'DAILY_LIMIT'
    )
    """)

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
        mfa_enabled INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """)

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
        is_active INTEGER DEFAULT 1,
        updated_at TEXT NOT NULL
    )
    """)

    # Alter table if existing schema lacks new multi-broker columns
    try:
        cursor.execute("ALTER TABLE broker_credentials ADD COLUMN broker_name TEXT DEFAULT 'PRIMARY GATEWAY'")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE broker_credentials ADD COLUMN environment TEXT DEFAULT 'Demo'")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE broker_credentials ADD COLUMN is_active INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass

    # Prepopulate default admin operator account if empty
    # SECURITY: Now loads from environment variables instead of hardcoded values
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        admin_username = os.getenv('ADMIN_USERNAME')
        admin_password = os.getenv('ADMIN_PASSWORD')
        admin_pin = os.getenv('ADMIN_PIN')
        
        if not admin_username or not admin_password or not admin_pin:
            print("WARNING: ADMIN_USERNAME, ADMIN_PASSWORD, or ADMIN_PIN not set in environment variables")
            print("Please set these in your .env file or environment")
            print("Skipping default admin account creation")
        else:
            cursor.execute("""
            INSERT INTO users (username, password_hash, pin_hash, role, mfa_enabled, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (
                admin_username,
                hash_credential(admin_password, credential_type='password'),
                hash_credential(admin_pin, credential_type='pin'),
                "SOVEREIGN_ADMIN",
                0,  # MFA disabled by default, user can enable later
                datetime.datetime.now().isoformat()
            ))

    # Prepopulate default broker credentials if empty
    # SECURITY: Now loads from environment variables instead of hardcoded values
    cursor.execute("SELECT COUNT(*) FROM broker_credentials")
    if cursor.fetchone()[0] == 0:
        mt5_server = os.getenv('MT5_SERVER')
        mt5_account_id = os.getenv('MT5_ACCOUNT_ID')
        mt5_password = os.getenv('MT5_PASSWORD')
        mt5_leverage = os.getenv('MT5_LEVERAGE', '1:100')
        mt5_environment = os.getenv('MT5_ENVIRONMENT', 'Demo')
        
        if not mt5_server or not mt5_account_id or not mt5_password:
            print("WARNING: MT5_SERVER, MT5_ACCOUNT_ID, or MT5_PASSWORD not set in environment variables")
            print("Please set these in your .env file or environment")
            print("Skipping default broker credentials creation")
        else:
            cursor.execute("""
            INSERT INTO broker_credentials (broker_name, server, account_id, password_encrypted, leverage, environment, is_active, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "Primary MetaTrader Gateway",
                mt5_server,
                mt5_account_id,
                encrypt_secret(mt5_password),
                mt5_leverage,
                mt5_environment,
                1,
                datetime.datetime.now().isoformat()
            ))

    conn.commit()
    conn.close()

def verify_user_password(username, password_input):
    """Verifies a user's password against the bcrypt hash stored in SQLite."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return False
    return verify_credential(password_input, row['password_hash'], 'password')

def verify_user_pin(pin_input):
    """Verifies a secondary security PIN against active operators in SQLite."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT pin_hash FROM users")
    rows = cursor.fetchall()
    conn.close()

    # Check PIN against all users
    for r in rows:
        if verify_credential(pin_input, r['pin_hash'], 'pin'):
            return True
    return False

def get_all_users():
    """Retrieves all registered user profiles."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, role, mfa_enabled, created_at FROM users ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_user(username, password, pin, role="QUANT_TRADER", mfa_enabled=0):
    """Adds a new operator account with bcrypt-hashed password and PIN."""
    validator = get_validator()
    
    # Validate inputs
    try:
        validated_username = validator.validate_username(username)
        validated_password = validator.validate_password(password)
        validated_pin = validator.validate_pin(pin)
    except Exception as e:
        raise ValueError(f"Input validation failed: {e}")
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO users (username, password_hash, pin_hash, role, mfa_enabled, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        validated_username,
        hash_credential(validated_password, credential_type='password'),
        hash_credential(validated_pin, credential_type='pin'),
        role,
        int(mfa_enabled),
        datetime.datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()

def update_user(username, new_password=None, new_pin=None, new_role=None):
    """Updates password, PIN, or role for an existing user account."""
    validator = get_validator()
    
    # Validate inputs if provided
    if new_password is not None:
        try:
            new_password = validator.validate_password(new_password)
        except Exception as e:
            raise ValueError(f"Password validation failed: {e}")
    
    if new_pin is not None:
        try:
            new_pin = validator.validate_pin(new_pin)
        except Exception as e:
            raise ValueError(f"PIN validation failed: {e}")
    
    conn = get_connection()
    cursor = conn.cursor()
    if new_password:
        cursor.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?", 
            (hash_credential(new_password, credential_type='password'), username)
        )
    if new_pin:
        cursor.execute(
            "UPDATE users SET pin_hash = ? WHERE username = ?", 
            (hash_credential(new_pin, credential_type='pin'), username)
        )
    if new_role:
        cursor.execute("UPDATE users SET role = ? WHERE username = ?", (new_role, username))
    conn.commit()
    conn.close()

def delete_user(username):
    """Deletes a user account from SQLite."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE username = ?", (username,))
    conn.commit()
    conn.close()

def setup_user_mfa(username):
    """
    Set up multi-factor authentication for a user.
    
    Args:
        username: The username to set up MFA for
        
    Returns:
        Dictionary with secret, QR code, and backup codes
    """
    mfa_manager = get_mfa_manager()
    mfa_storage = get_mfa_storage()
    
    # Generate MFA setup data
    mfa_data = mfa_manager.setup_user_mfa(username)
    
    # Save to database
    mfa_storage.save_mfa_secret(
        username,
        mfa_data['secret'],
        mfa_data['issuer']
    )
    
    # Save backup codes
    mfa_storage.save_backup_codes(username, mfa_data['backup_codes'])
    
    return mfa_data

def verify_user_mfa(username, mfa_token):
    """
    Verify a user's MFA token.
    
    Args:
        username: The username to verify
        mfa_token: The TOTP token or backup code
        
    Returns:
        True if MFA token is valid, False otherwise
    """
    mfa_manager = get_mfa_manager()
    mfa_storage = get_mfa_storage()
    
    # First try as TOTP token
    if mfa_manager.verify_token(username, mfa_token):
        return True
    
    # Then try as backup code
    if mfa_storage.verify_backup_code(username, mfa_token):
        return True
    
    return False

def disable_user_mfa(username):
    """
    Disable MFA for a user.
    
    Args:
        username: The username to disable MFA for
    """
    mfa_manager = get_mfa_manager()
    mfa_storage = get_mfa_storage()
    
    # Remove from manager
    mfa_manager.disable_user_mfa(username)
    
    # Remove from database
    mfa_storage.delete_user_mfa(username)

def is_user_mfa_enabled(username):
    """
    Check if MFA is enabled for a user.
    
    Args:
        username: The username to check
        
    Returns:
        True if MFA is enabled, False otherwise
    """
    mfa_manager = get_mfa_manager()
    return mfa_manager.is_mfa_enabled(username)

def regenerate_user_backup_codes(username):
    """
    Regenerate backup codes for a user.
    
    Args:
        username: The username to regenerate codes for
        
    Returns:
        List of new backup codes
    """
    mfa_manager = get_mfa_manager()
    mfa_storage = get_mfa_storage()
    
    # Generate new codes
    new_codes = mfa_manager.regenerate_backup_codes(username)
    
    # Save to database
    mfa_storage.save_backup_codes(username, new_codes)
    
    return new_codes

def get_all_brokers():
    """Retrieves all registered broker profiles from SQLite."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, broker_name, server, account_id, password_encrypted, leverage, environment, is_active, updated_at FROM broker_credentials ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()

    brokers = []
    for r in rows:
        b = dict(r)
        b["password"] = decrypt_secret(b["password_encrypted"])
        brokers.append(b)
    return brokers

def add_broker_account(broker_name, server, account_id, password, leverage="1:100", environment="Demo", is_active=0):
    """Adds a new broker gateway configuration into SQLite."""
    conn = get_connection()
    cursor = conn.cursor()
    if is_active:
        cursor.execute("UPDATE broker_credentials SET is_active = 0")
    cursor.execute("""
    INSERT INTO broker_credentials (broker_name, server, account_id, password_encrypted, leverage, environment, is_active, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        broker_name,
        server,
        account_id,
        encrypt_secret(password),
        leverage,
        environment,
        1 if is_active else 0,
        datetime.datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()

def set_active_broker(broker_id):
    """Sets a specific broker account as the active primary gateway."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE broker_credentials SET is_active = 0")
    cursor.execute("UPDATE broker_credentials SET is_active = 1 WHERE id = ?", (broker_id,))
    conn.commit()
    conn.close()

def delete_broker_account(broker_id):
    """Deletes a broker profile from SQLite."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM broker_credentials WHERE id = ?", (broker_id,))
    conn.commit()
    conn.close()

def save_broker_credentials(server, account_id, password, leverage, broker_name="Primary Gateway", environment="Demo"):
    """Saves or updates primary active broker parameters in SQLite."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM broker_credentials WHERE is_active = 1 LIMIT 1")
    row = cursor.fetchone()
    if row:
        cursor.execute("""
        UPDATE broker_credentials
        SET broker_name = ?, server = ?, account_id = ?, password_encrypted = ?, leverage = ?, environment = ?, updated_at = ?
        WHERE id = ?
        """, (broker_name, server, account_id, encrypt_secret(password), leverage, environment, datetime.datetime.now().isoformat(), row['id']))
    else:
        cursor.execute("""
        INSERT INTO broker_credentials (broker_name, server, account_id, password_encrypted, leverage, environment, is_active, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?)
        """, (broker_name, server, account_id, encrypt_secret(password), leverage, environment, datetime.datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_broker_credentials():
    """Retrieves active broker connection parameters and decrypts the password."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT broker_name, server, account_id, password_encrypted, leverage, environment FROM broker_credentials WHERE is_active = 1 LIMIT 1")
    row = cursor.fetchone()
    if not row:
        cursor.execute("SELECT broker_name, server, account_id, password_encrypted, leverage, environment FROM broker_credentials ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
    conn.close()

    if not row:
        # SECURITY: Return empty dict instead of hardcoded credentials
        # User must configure broker credentials via environment variables or GUI
        print("WARNING: No active broker credentials found in database")
        print("Please configure broker credentials using the GUI or environment variables")
        return {
            "broker_name": None,
            "server": None,
            "account_id": None,
            "password": None,
            "leverage": None,
            "environment": None
        }

    return {
        "broker_name": row["broker_name"] if "broker_name" in row.keys() and row["broker_name"] else "Primary Gateway",
        "server": row["server"],
        "account_id": row["account_id"],
        "password": decrypt_secret(row["password_encrypted"]),
        "leverage": row["leverage"],
        "environment": row["environment"] if "environment" in row.keys() and row["environment"] else "Demo"
    }

def log_assessment(symbol, trend_direction, rsi_val, atr_val, decision, explanation):
    """Logs an analysis assessment made by the brain."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO assessments (timestamp, symbol, trend_direction, rsi_val, atr_val, decision, explanation)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.datetime.now().isoformat(),
        symbol,
        trend_direction,
        rsi_val,
        atr_val,
        decision,
        explanation
    ))
    conn.commit()
    conn.close()

def log_trade_open(ticket, symbol, direction, open_price, sl, tp, lot_size):
    """Logs the initiation of a trade."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO trades (ticket, symbol, direction, open_price, open_time, sl, tp, lot_size, status)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        str(ticket),
        symbol,
        direction,
        open_price,
        datetime.datetime.now().isoformat(),
        sl,
        tp,
        lot_size,
        'OPEN'
    ))
    conn.commit()
    conn.close()

def log_trade_close(ticket, close_price, profit, reason):
    """Updates the trade record when a trade is closed."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE trades
    SET status = 'CLOSED', close_price = ?, close_time = ?, profit = ?, close_reason = ?
    WHERE ticket = ?
    """, (
        close_price,
        datetime.datetime.now().isoformat(),
        profit,
        reason,
        str(ticket)
    ))
    conn.commit()
    conn.close()

def get_open_trades():
    """Returns all open trades."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trades WHERE status = 'OPEN'")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def log_news_headline(headline, sentiment):
    """Logs a macro headline with its parsed sentiment classification."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO news (timestamp, headline, sentiment)
    VALUES (?, ?, ?)
    """, (
        datetime.datetime.now().isoformat(),
        headline,
        sentiment.upper()
    ))
    conn.commit()
    conn.close()

def get_prevailing_news_sentiment():
    """
    Computes prevailing sentiment across recent news headlines.
    Returns: 'BULLISH' | 'BEARISH' | 'NEUTRAL'
    """
    conn = get_connection()
    cursor = conn.cursor()
    # Get last 15 headlines logged
    cursor.execute("SELECT sentiment FROM news ORDER BY timestamp DESC LIMIT 15")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return "NEUTRAL"

    sentiments = [r['sentiment'] for r in rows]
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
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT profit FROM trades
        WHERE status = 'CLOSED'
        ORDER BY close_time DESC
        LIMIT ?
    """, (count,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_daily_profit(date_str=None):
    """Calculates total profits for closed trades on a specific date (YYYY-MM-DD)."""
    if date_str is None:
        date_str = datetime.date.today().isoformat()

    conn = get_connection()
    cursor = conn.cursor()
    # Match the prefix of close_time with date_str
    cursor.execute("""
    SELECT SUM(profit) FROM trades
    WHERE status = 'CLOSED' AND close_time LIKE ?
    """, (f"{date_str}%",))
    row = cursor.fetchone()
    profit = row[0] if row[0] is not None else 0.0
    conn.close()
    return profit

def update_performance_metrics(date_str, current_balance):
    """
    Autonomously analyzes trading performance for a specific date and
    upserts metrics into the performance_metrics table.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Query closed trades for the date
    cursor.execute("""
        SELECT profit FROM trades
        WHERE status = 'CLOSED' AND close_time LIKE ?
    """, (f"{date_str}%",))
    rows = cursor.fetchall()

    trades_taken = len(rows)
    net_profit = sum(row['profit'] for row in rows) if trades_taken > 0 else 0.0
    wins = sum(1 for row in rows if row['profit'] > 0)
    win_rate = (wins / trades_taken) * 100.0 if trades_taken > 0 else 0.0

    # Check if record exists
    cursor.execute("SELECT 1 FROM performance_metrics WHERE date = ?", (date_str,))
    exists = cursor.fetchone() is not None

    if exists:
        cursor.execute("""
            UPDATE performance_metrics
            SET final_balance = ?, trades_taken = ?, win_rate = ?, net_profit = ?
            WHERE date = ?
        """, (current_balance, trades_taken, win_rate, net_profit, date_str))
    else:
        cursor.execute("""
            INSERT INTO performance_metrics (date, initial_balance, final_balance, trades_taken, win_rate, net_profit)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (date_str, current_balance - net_profit, current_balance, trades_taken, win_rate, net_profit))

    conn.commit()
    conn.close()

def get_all_time_performance():
    """Computes all-time trading performance summary metrics."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT profit FROM trades
        WHERE status = 'CLOSED'
    """)
    rows = cursor.fetchall()
    conn.close()

    total_trades = len(rows)
    net_profit = sum(row['profit'] for row in rows) if total_trades > 0 else 0.0
    wins = sum(1 for row in rows if row['profit'] > 0)
    win_rate = (wins / total_trades) * 100.0 if total_trades > 0 else 0.0

    return {
        'total_trades': total_trades,
        'win_rate': round(win_rate, 2),
        'net_profit': round(net_profit, 2)
    }

def get_all_trades():
    """Returns all trades (open and closed)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trades ORDER BY open_time DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]
