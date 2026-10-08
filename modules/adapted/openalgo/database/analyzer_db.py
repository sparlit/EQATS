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


# database/analyzer_db.py

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import func
from utils.logging import get_logger

logger = get_logger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

# Conditionally create engine based on DB type
if DATABASE_URL and "sqlite" in DATABASE_URL:
    # SQLite: Use NullPool to prevent connection pool exhaustion
    engine = create_engine(
        DATABASE_URL, poolclass=NullPool, connect_args={"check_same_thread": False}
    )
else:
    # For other databases like PostgreSQL, use connection pooling
    engine = create_engine(DATABASE_URL, pool_size=50, max_overflow=100, pool_timeout=10)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class AnalyzerLog(Base):
    __tablename__ = "analyzer_logs"
    id = Column(Integer, primary_key=True)
    api_type = Column(String(50), nullable=False)  # placeorder, cancelorder, etc.
    request_data = Column(Text, nullable=False)
    response_data = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=func.now())

    # Performance indexes for analyzer queries
    __table_args__ = (
        Index("idx_analyzer_api_type", "api_type"),  # Speeds up filtering by API type
        Index(
            "idx_analyzer_created_at", "created_at"
        ),  # Speeds up time-based queries and log retrieval
        Index(
            "idx_analyzer_type_time", "api_type", "created_at"
        ),  # Composite for API type + time range queries
    )

    def to_dict(self):
        """Convert log entry to dictionary"""
        try:
            request_data = (
                json.loads(self.request_data)
                if isinstance(self.request_data, str)
                else self.request_data
            )
            response_data = (
                json.loads(self.response_data)
                if isinstance(self.response_data, str)
                else self.response_data
            )
        except json.JSONDecodeError:
            request_data = self.request_data
            response_data = self.response_data

        return {
            "id": self.id,
            "api_type": self.api_type,
            "request_data": request_data,
            "response_data": response_data,
            "created_at": self.created_at.astimezone(pytz.UTC).isoformat(),
        }


def init_db():
    """Initialize the analyzer table"""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Analyzer DB", logger)


# Executor for asynchronous tasks
executor = ThreadPoolExecutor(10)  # Increased from 2 to 10 for better concurrency


def async_log_analyzer(request_data, response_data, api_type="placeorder"):
    """Asynchronously log analyzer request"""
    try:
        # Serialize JSON data for storage
        request_json = json.dumps(request_data)
        response_json = json.dumps(response_data)

        # Get current time in IST
        ist = pytz.timezone("Asia/Kolkata")
        now_ist = datetime.now(ist)

        analyzer_log = AnalyzerLog(
            api_type=api_type,
            request_data=request_json,
            response_data=response_json,
            created_at=now_ist,
        )
        db_session.add(analyzer_log)
        db_session.commit()
    except Exception as e:
        logger.exception(f"Error saving analyzer log: {e}")
        db_session.rollback()
    finally:
        db_session.remove()
