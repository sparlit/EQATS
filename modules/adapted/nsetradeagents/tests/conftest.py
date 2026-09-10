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
from unittest.mock import patch

import pytest
from app.core.database import Base
from app.models import models
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(autouse=True)
def reset_health_state():
    """Clear the cached last-scan time between tests.

    app.core.health keeps it in module state so /health never queries, which
    means it leaks across tests unless reset.
    """
    from app.core import health

    health._last_scan = None
    health._loaded = False
    yield
    health._last_scan = None
    health._loaded = False


@pytest.fixture
def mock_db(db_session):
    @contextmanager
    def _get_db():
        yield db_session

    with patch("app.portfolio.simulator.get_db", _get_db):
        yield db_session
