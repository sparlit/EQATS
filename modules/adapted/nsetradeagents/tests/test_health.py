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


"""Tests for the /health endpoint and the state behind it.

Health exists for an external monitor: the box being gone shows up as no
response at all, so this endpoint's job is the other failure — the process is
alive but the scan has stopped happening.
"""

from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import patch

import pytest
from app.api.routes import app
from app.core import health
from app.core.database import Base
from app.models.models import ScanRun, utcnow
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

client = TestClient(app)


@pytest.fixture
def health_db(monkeypatch):
    """Point app.core.health at an in-memory database.

    StaticPool because TestClient runs sync endpoints on a worker thread, and
    every new connection to :memory: would otherwise open an empty database.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)

    @contextmanager
    def _get_db():
        yield session

    monkeypatch.setattr(health, "get_db", _get_db)
    yield session
    session.close()


def scanned(db, hours_ago: float) -> None:
    db.add(ScanRun(ran_at=utcnow() - timedelta(hours=hours_ago)))
    db.commit()


# ── the endpoint ─────────────────────────────────────────────────────────────


def test_503_when_no_scan_has_ever_run(health_db):
    """A fresh deploy that has never scanned is not healthy."""
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["status"] == "never_ran"


def test_200_after_a_recent_scan(health_db):
    scanned(health_db, hours_ago=2)

    r = client.get("/health")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["age_hours"] == 2.0
    assert body["last_scan"]


def test_503_when_the_last_scan_is_too_old(health_db):
    """Non-200 is the point: a plain uptime monitor needs no extra config to
    notice a scheduler that quietly stopped firing."""
    scanned(health_db, hours_ago=health.MAX_SCAN_AGE_HOURS + 1)

    r = client.get("/health")

    assert r.status_code == 503
    assert r.json()["status"] == "stale"


def test_a_long_weekend_does_not_trip_it(health_db):
    """Friday scan, Monday holiday, Tuesday check — still healthy."""
    scanned(health_db, hours_ago=95)

    assert client.get("/health").status_code == 200


def test_the_newest_run_wins(health_db):
    scanned(health_db, hours_ago=500)
    scanned(health_db, hours_ago=1)

    assert client.get("/health").json()["status"] == "ok"


# ── the caching that keeps it off the database ───────────────────────────────


def test_the_database_is_read_only_once(health_db):
    """Polling must not wake hosted Postgres on every request — that is what
    burns a metered free tier."""
    scanned(health_db, hours_ago=1)

    with patch.object(health, "get_db", wraps=health.get_db) as spy:
        for _ in range(20):
            client.get("/health")

    assert spy.call_count == 1


def test_a_never_ran_result_is_cached_too(health_db):
    """None means 'no scan yet', not 'not loaded' — without a separate flag a
    fresh box would re-query on every single poll."""
    with patch.object(health, "get_db", wraps=health.get_db) as spy:
        for _ in range(5):
            client.get("/health")

    assert spy.call_count == 1


def test_note_scan_run_updates_without_touching_the_database(health_db):
    scanned(health_db, hours_ago=500)
    assert client.get("/health").json()["status"] == "stale"

    health.note_scan_run(utcnow())

    with patch.object(health, "get_db", wraps=health.get_db) as spy:
        assert client.get("/health").json()["status"] == "ok"

    assert spy.call_count == 0


def test_head_is_accepted(health_db):
    """Uptime services default to HEAD, and FastAPI does not add it alongside
    GET the way plain Starlette routes do — without it the monitor sees 405 and
    reports the site down while it is perfectly healthy."""
    scanned(health_db, hours_ago=1)

    assert client.head("/health").status_code == 200


def test_head_reports_staleness_too(health_db):
    """The status code is all a HEAD request carries, so it has to be right."""
    scanned(health_db, hours_ago=health.MAX_SCAN_AGE_HOURS + 1)

    assert client.head("/health").status_code == 503


# ── session lifecycle ────────────────────────────────────────────────────────
#
# The fixture above yields a session that is never committed or closed, which is
# more permissive than the real get_db. That gap hid a DetachedInstanceError in
# production: get_db commits on exit, which expires the instance, so reading an
# attribute afterwards triggers a lazy reload on a detached object.


@pytest.fixture
def realistic_db(monkeypatch):
    """A get_db that commits and closes on exit, exactly like the real one."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine)

    with Session_() as seed:
        seed.add(ScanRun(ran_at=utcnow() - timedelta(hours=1)))
        seed.commit()

    @contextmanager
    def _get_db():
        db = Session_()
        try:
            yield db
            db.commit()
        finally:
            db.close()

    monkeypatch.setattr(health, "get_db", _get_db)


def test_the_cold_read_survives_the_session_closing(realistic_db):
    """Regression: a fresh process with an existing ScanRun row used to 500.

    The attribute was read after the `with get_db()` block had committed and
    closed, detaching the instance. Only reproducible with a session that
    actually closes.
    """
    assert health.last_scan_at() is not None
    assert client.get("/health").status_code == 200


def test_a_database_failure_degrades_rather_than_500s(monkeypatch):
    """A health endpoint that raises is useless in the one situation it exists
    to report on."""

    @contextmanager
    def dead_db():
        msg = "connection refused"
        raise RuntimeError(msg)
        yield  # pragma: no cover

    monkeypatch.setattr(health, "get_db", dead_db)

    r = client.get("/health")

    assert r.status_code == 503
    assert r.json()["status"] == "never_ran"
