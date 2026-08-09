import sqlite3
import datetime
import config

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

    conn.commit()
    conn.close()

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
