import sqlite3
import datetime
import hashlib
import hmac
import base64
import config

def hash_credential(secret_text, salt="EAQTS_SOVEREIGN_SALT_2026"):
    """Generates a salt-based SHA-256 cryptographic digest for passwords and PINs."""
    if not secret_text:
        secret_text = ""
    salted_str = f"{secret_text}:{salt}"
    return hashlib.sha256(salted_str.encode('utf-8')).hexdigest()

def encrypt_secret(plain_text, key_seed="EAQTS_CIPHER_KEY_2026"):
    """Encrypts a string using reversible XOR-base64 ciphering for broker passwords."""
    if not plain_text:
        return ""
    key_bytes = hashlib.sha256(key_seed.encode('utf-8')).digest()
    plain_bytes = plain_text.encode('utf-8')
    cipher_bytes = bytes([b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(plain_bytes)])
    return base64.b64encode(cipher_bytes).decode('utf-8')

def decrypt_secret(cipher_text, key_seed="EAQTS_CIPHER_KEY_2026"):
    """Decrypts a base64-XOR encrypted string back to plaintext."""
    if not cipher_text:
        return ""
    try:
        key_bytes = hashlib.sha256(key_seed.encode('utf-8')).digest()
        cipher_bytes = base64.b64decode(cipher_text.encode('utf-8'))
        plain_bytes = bytes([b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(cipher_bytes)])
        return plain_bytes.decode('utf-8')
    except Exception:
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
        mfa_enabled INTEGER DEFAULT 1,
        created_at TEXT NOT NULL
    )
    """)

    # Table for storing broker gateway connection details with encrypted secrets
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS broker_credentials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server TEXT NOT NULL,
        account_id TEXT NOT NULL,
        password_encrypted TEXT NOT NULL,
        leverage TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)

    # Prepopulate default admin operator account if empty
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
        INSERT INTO users (username, password_hash, pin_hash, role, mfa_enabled, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (
            "QUANT_OPERATOR",
            hash_credential("admin"),
            hash_credential("741295"),
            "SOVEREIGN_ADMIN",
            1,
            datetime.datetime.now().isoformat()
        ))

    # Prepopulate default broker credentials if empty
    cursor.execute("SELECT COUNT(*) FROM broker_credentials")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
        INSERT INTO broker_credentials (server, account_id, password_encrypted, leverage, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """, (
            "EAQTS-Demo-Server",
            "10928471",
            encrypt_secret("demoPass123!"),
            "1:100",
            datetime.datetime.now().isoformat()
        ))

    conn.commit()
    conn.close()

def verify_user_password(username, password_input):
    """Verifies a user's password against the encrypted hash stored in SQLite."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return False
    return row['password_hash'] == hash_credential(password_input)

def verify_user_pin(pin_input):
    """Verifies a secondary security PIN against active operators in SQLite."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT pin_hash FROM users")
    rows = cursor.fetchall()
    conn.close()

    target_hash = hash_credential(pin_input)
    return any(r['pin_hash'] == target_hash for r in rows)

def get_all_users():
    """Retrieves all registered user profiles."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, role, mfa_enabled, created_at FROM users ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_user(username, password, pin, role="QUANT_TRADER", mfa_enabled=1):
    """Adds a new operator account with salt-hashed password and PIN."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO users (username, password_hash, pin_hash, role, mfa_enabled, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        username,
        hash_credential(password),
        hash_credential(pin),
        role,
        int(mfa_enabled),
        datetime.datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()

def update_user(username, new_password=None, new_pin=None, new_role=None):
    """Updates password, PIN, or role for an existing user account."""
    conn = get_connection()
    cursor = conn.cursor()
    if new_password:
        cursor.execute("UPDATE users SET password_hash = ? WHERE username = ?", (hash_credential(new_password), username))
    if new_pin:
        cursor.execute("UPDATE users SET pin_hash = ? WHERE username = ?", (hash_credential(new_pin), username))
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

def save_broker_credentials(server, account_id, password, leverage):
    """Saves broker gateway parameters with encrypted password into SQLite."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM broker_credentials")
    cursor.execute("""
    INSERT INTO broker_credentials (server, account_id, password_encrypted, leverage, updated_at)
    VALUES (?, ?, ?, ?, ?)
    """, (
        server,
        account_id,
        encrypt_secret(password),
        leverage,
        datetime.datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()

def get_broker_credentials():
    """Retrieves broker connection parameters and decrypts the password."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT server, account_id, password_encrypted, leverage FROM broker_credentials ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()

    if not row:
        return {
            "server": "EAQTS-Demo-Server",
            "account_id": "10928471",
            "password": "demoPass123!",
            "leverage": "1:100"
        }

    return {
        "server": row["server"],
        "account_id": row["account_id"],
        "password": decrypt_secret(row["password_encrypted"]),
        "leverage": row["leverage"]
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
