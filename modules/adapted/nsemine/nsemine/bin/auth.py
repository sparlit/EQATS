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
import logging
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

LOGGER = logging.getLogger(__name__)
DB_PATH = Path(__file__).resolve().parent / "nsedb.db"
SESSION_ID = "almighty"
DEFAULT_MAX_AGE_MINUTES = 60
_DB_LOCK = threading.Lock()


def _secure_db_file() -> None:
    """Best-effort restriction of the local session database to the owner."""
    try:
        if DB_PATH.exists():
            DB_PATH.chmod(0o600)
    except OSError:
        # chmod is not portable to every environment; database functionality
        # should not fail solely because the platform does not support it.
        pass


def get_db_connection():
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=10000;")
        _secure_db_file()
        return conn
    except Exception as e:
        LOGGER.warning("NSE session database connection failure: %s", e)
        return None


def initialize_database():
    conn = get_db_connection()
    if not conn:
        return

    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS credentials (
                    id TEXT PRIMARY KEY,
                    session_token TEXT NOT NULL,
                    updated_on TEXT NOT NULL
                );
                """
            )
    except Exception as e:
        LOGGER.warning("NSE session database initialization failure: %s", e)
    finally:
        conn.close()
        _secure_db_file()


def set_session_token(session_token: dict):
    """Persist the current cookie values used to bootstrap a fresh session."""
    if not isinstance(session_token, dict) or not session_token:
        return

    try:
        data = json.dumps(session_token, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as e:
        LOGGER.warning("Could not serialize NSE session state: %s", e)
        return

    now_str = datetime.now(UTC).isoformat()
    conn = get_db_connection()
    if not conn:
        return

    with _DB_LOCK:
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO credentials (id, session_token, updated_on)
                    VALUES (?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        session_token = excluded.session_token,
                        updated_on = excluded.updated_on;
                    """,
                    (SESSION_ID, data, now_str),
                )
        except Exception as e:
            LOGGER.warning("NSE session database write failure: %s", e)
        finally:
            conn.close()


def clear_session_token() -> None:
    """Delete the cached session so the next request must bootstrap a new one."""
    conn = get_db_connection()
    if not conn:
        return

    with _DB_LOCK:
        try:
            with conn:
                conn.execute("DELETE FROM credentials WHERE id = ?", (SESSION_ID,))
        except Exception as e:
            LOGGER.warning("NSE session database cleanup failure: %s", e)
        finally:
            conn.close()


def _is_fresh(updated_str: str, max_age: timedelta) -> bool:
    try:
        updated_time = datetime.fromisoformat(updated_str)
    except (TypeError, ValueError):
        return False

    # Older nsemine versions wrote naive local timestamps. Preserve compatibility
    # with those rows while using UTC-aware timestamps for new rows.
    if updated_time.tzinfo is None:
        return datetime.now() - updated_time < max_age

    now_utc = datetime.now(UTC)
    return now_utc - updated_time.astimezone(UTC) < max_age


def get_session_token(max_age_minutes: int = DEFAULT_MAX_AGE_MINUTES) -> dict | None:
    """Return cached session cookies when they are still reasonably fresh."""
    if max_age_minutes <= 0:
        return None

    conn = get_db_connection()
    if not conn:
        return None

    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT session_token, updated_on FROM credentials WHERE id = ?",
            (SESSION_ID,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        session_json, updated_str = row
        if not _is_fresh(updated_str, timedelta(minutes=max_age_minutes)):
            return None

        payload = json.loads(session_json)
        return payload if isinstance(payload, dict) and payload else None
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        LOGGER.warning("Invalid cached NSE session state: %s", e)
        return None
    except Exception as e:
        LOGGER.warning("NSE session database read failure: %s", e)
        return None
    finally:
        conn.close()


initialize_database()
_secure_db_file()
