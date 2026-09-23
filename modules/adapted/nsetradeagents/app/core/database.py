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


from contextlib import contextmanager

import structlog
from app.core.config import settings
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

logger = structlog.get_logger()


class Base(DeclarativeBase):
    """Declarative base every model inherits from."""


engine = create_engine(
    settings.database_url,
    connect_args=({"check_same_thread": False} if "sqlite" in settings.database_url else {}),
    pool_pre_ping=True,  # hosted Postgres drops idle connections; test before use
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@contextmanager
def get_db():
    """Session context manager that commits on success and rolls back on error."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception as e:
        db.rollback()
        logger.exception("database_error", error=str(e))
        raise
    finally:
        db.close()


def init_db():
    # Importing the module registers every model on Base before create_all.
    """Create any missing tables."""
    from app.models import models

    Base.metadata.create_all(bind=engine)
    logger.info("database_initialised", url=settings.database_url)
