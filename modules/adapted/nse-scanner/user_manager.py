import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = "nse_scanner.db"
USER_JSON = "user_data.json"
LOG_FILE = "logs/user_activity.log"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            name TEXT,
            phone TEXT,
            join_date TEXT,
            last_active TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            action TEXT,
            timestamp TEXT
        )
    """)
    conn.commit()
    conn.close()


def register_user(user_id, name, phone=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        """
        INSERT INTO users (user_id, name, phone, join_date, last_active)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            name=excluded.name,
            phone=excluded.phone,
            last_active=excluded.last_active
    """,
        (user_id, name, phone, now, now),
    )
    conn.commit()
    conn.close()
    sync_json()


def log_action(user_id, action):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO user_logs (user_id, action, timestamp) VALUES (?, ?, ?)", (user_id, action, now))
    conn.commit()
    conn.close()

    Path("logs").mkdir(exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:  # <-- force UTF-8
        f.write(f"[{now}] {user_id} -> {action}\n")  # <-- replace arrow with ASCII


def sync_json():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    users = []
    for row in c.execute("SELECT * FROM users"):
        users.append({"id": row[0], "name": row[1], "phone": row[2], "join_date": row[3], "last_active": row[4]})
    logs = []
    for row in c.execute("SELECT user_id, action, timestamp FROM user_logs ORDER BY log_id DESC LIMIT 100"):
        logs.append({"user_id": row[0], "action": row[1], "timestamp": row[2]})
    conn.close()
    data = {"users": users, "logs": logs}
    Path(USER_JSON).write_text(json.dumps(data, indent=2), encoding="utf-8")


init_db()
