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


import os
import sys

from dotenv import load_dotenv
from sqlalchemy import text

# Add parent directory to path so we can import from the project
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(parent_dir)

# Load environment variables from .env file
dotenv_path = os.path.join(parent_dir, ".env")
load_dotenv(dotenv_path)

import logging
from datetime import datetime

# Register the app's SQLite pragmas on this process's engines, so a migration
# waits the same 15s for a write lock the running app does instead of the
# sqlite3 default of 5s (GitHub issue #1726).
import _pragmas  # noqa: F401,E402
from sqlalchemy import Boolean, Column, DateTime, String, Text, create_engine, inspect
from sqlalchemy.ext.declarative import declarative_base

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define Base and Auth classes locally
Base = declarative_base()


class Auth(Base):
    """Class for the auth table - defined locally to avoid import issues"""

    __tablename__ = "auth"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    broker = Column(String, nullable=False)
    auth = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    modified_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_revoked = Column(Boolean, default=False)
    # We'll be adding feed_token column


def add_feed_token_column():
    """
    Script to add feed_token column to the auth table if it doesn't exist.
    """
    # Get the database URL from environment
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL environment variable not set")
        return False

    # If the database is SQLite, ensure we use the absolute path
    if database_url.startswith("sqlite:///"):
        # Extract the relative path part after sqlite:///
        db_path = database_url.replace("sqlite:///", "")
        # Convert to absolute path if not already
        if not os.path.isabs(db_path):
            abs_db_path = os.path.abspath(os.path.join(parent_dir, db_path))
            database_url = f"sqlite:///{abs_db_path}"

    logger.info(f"Using database: {database_url}")

    # Ensure the directory exists for SQLite
    if database_url.startswith("sqlite:///"):
        db_path = database_url.replace("sqlite:///", "")
        db_dir = os.path.dirname(db_path)
        if not os.path.exists(db_dir):
            logger.error(f"Database directory does not exist: {db_dir}")
            return False

    engine = create_engine(database_url)

    try:
        # Connect to the database
        conn = engine.connect()

        # Check if the feed_token column already exists
        inspector = inspect(engine)
        columns = [col["name"] for col in inspector.get_columns("auth")]

        if "feed_token" not in columns:
            logger.info("Adding feed_token column to auth table...")

            # Add the column - use SQLAlchemy 2.0 compatible execution
            conn.execute(text("ALTER TABLE auth ADD COLUMN feed_token TEXT"))
            conn.commit()  # Commit the transaction
            logger.info("feed_token column added successfully.")
        else:
            logger.info("feed_token column already exists in auth table. No action needed.")

        conn.close()
        return True

    except Exception as e:
        logger.error(f"Error adding feed_token column: {e}")
        logger.error(f"Database URL being used: {database_url}")
        return False


if __name__ == "__main__":
    success = add_feed_token_column()
    if success:
        logger.info("Migration completed successfully!")
    else:
        logger.error("Migration failed!")
        sys.exit(1)
