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


"""Regression tests for /auth/logout session cleanup."""

import os
import sys

from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import blueprints.auth as auth_bp_module  # noqa: E402
import database.auth_db as auth_db  # noqa: E402


def _app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(auth_bp_module.auth_bp)
    return app


def test_logout_clears_half_logged_in_session():
    """A password-only session (broker OAuth unfinished) must still be cleared."""
    app = _app()
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "rajandran"

        response = client.get("/auth/logout")

        assert response.status_code == 302
        with client.session_transaction() as session:
            assert "user" not in session


def test_logout_clears_full_session(monkeypatch):
    """A fully logged-in session is also cleared."""
    monkeypatch.setattr(auth_bp_module, "upsert_auth", lambda *args, **kwargs: None)
    monkeypatch.setattr(auth_db, "clear_user_sessions", lambda *args, **kwargs: None)
    monkeypatch.setattr(auth_bp_module.socketio, "emit", lambda *args, **kwargs: None)

    app = _app()
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "rajandran"
            session["logged_in"] = True
            session["broker"] = "dhan"

        response = client.post("/auth/logout")

        assert response.status_code == 200
        with client.session_transaction() as session:
            assert "user" not in session
            assert "logged_in" not in session


def test_logout_revokes_broker_token(monkeypatch):
    """Clearing the cookie is not enough - the broker token must be revoked.

    The session-clearing assertions above would still pass if the teardown were
    skipped entirely, which would silently leave the broker session alive while
    the UI reports a successful logout.
    """
    revocations = []
    monkeypatch.setattr(
        auth_bp_module,
        "upsert_auth",
        lambda name, *args, **kwargs: revocations.append((name, kwargs.get("revoke"))),
    )
    monkeypatch.setattr(auth_db, "clear_user_sessions", lambda *args, **kwargs: None)
    monkeypatch.setattr(auth_bp_module.socketio, "emit", lambda *args, **kwargs: None)

    app = _app()
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "rajandran"
            session["logged_in"] = True
            session["broker"] = "dhan"

        assert client.post("/auth/logout").status_code == 200

    assert revocations == [("rajandran", True)]


def test_half_logged_in_logout_leaves_the_shared_feed_alone(monkeypatch):
    """The teardown must stay gated on a fully active session.

    Running it for a half-logged-in session would publish CACHE_INVALIDATE_ALL
    and call cleanup_pools_for_user, killing the live broker feed for the user's
    other, properly logged-in devices. See issue #1591.
    """
    calls = []
    monkeypatch.setattr(auth_bp_module, "upsert_auth", lambda *a, **k: calls.append("upsert_auth"))
    monkeypatch.setattr(auth_db, "clear_user_sessions", lambda *a, **k: calls.append("clear"))
    monkeypatch.setattr(auth_bp_module.socketio, "emit", lambda *a, **k: calls.append("emit"))

    app = _app()
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "rajandran"  # password step only, no logged_in

        assert client.get("/auth/logout").status_code == 302

    assert calls == []
