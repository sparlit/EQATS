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
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


def initialize_database():
    try:
        db_path = Path(__file__).resolve().parent
        conn = sqlite3.connect(database=os.path.join(db_path, "nsedb.db"))
        cur = conn.cursor()
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS credentials (
                        id TEXT,
                        session_token TEXT,
                        updated_on TEXT
                        );
                    """)
        conn.commit()
        conn.close()
    except (sqlite3.OperationalError, Exception):
        conn.close()
    finally:
        if conn:
            conn.close()


def get_db_connection():
    try:
        db_path = Path(__file__).resolve().parent
        conn = sqlite3.connect(os.path.join(db_path, "nsedb.db"))
        return conn, conn.cursor()
    except Exception:
        conn.close()
        return None


def set_session_token(session_token):
    if not isinstance(session_token, dict):
        return
    nsit = session_token.get("nsit")
    nseappid = session_token.get("nseappid")
    if not nsit and not nseappid:
        return
    data = json.dumps({"nsit": nsit, "nseappid": nseappid})
    try:
        conn, cursor = get_db_connection()
        cursor.execute("SELECT * FROM credentials WHERE id=?", ("almighty",))
        existing_row = cursor.fetchone()
        if existing_row:
            cursor.execute(
                "UPDATE credentials SET session_token=?, updated_on=? WHERE id=?",
                (data, str(datetime.now()), "almighty"),
            )
        else:
            cursor.execute(
                "INSERT INTO credentials (id, session_token, updated_on) VALUES (?, ?, ?)",
                ("almighty", data, str(datetime.now())),
            )
        conn.commit()
    except Exception as e:
        print(e)
        conn.close()
    finally:
        if conn:
            conn.close()


def get_session_token():
    try:
        conn, cursor = get_db_connection()
        cursor.execute("SELECT * FROM credentials WHERE id=?", ("almighty",))
        data = cursor.fetchone()
        if data:
            offset = datetime.now() - datetime.strptime(data[2], "%Y-%m-%d %H:%M:%S.%f")
            if offset < timedelta(hours=1, minutes=30):
                conn.close()
                return json.loads(data[1])
        if conn:
            conn.close()
        return None
    except Exception:
        if conn:
            conn.close()
        return None


# database initialization
initialize_database()
