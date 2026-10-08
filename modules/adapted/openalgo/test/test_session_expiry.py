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


"""Regression tests for session expiry side effects."""

import os
import sys

from flask import Flask, session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database.auth_db as auth_db  # noqa: E402
import extensions  # noqa: E402
import utils.session as session_utils  # noqa: E402


def test_auto_expiry_broadcasts_force_logout_to_all_devices(monkeypatch):
    """3 AM auto-expiry should notify other browser sessions immediately."""
    app = Flask(__name__)
    app.secret_key = "test-secret"
    emitted = []

    class FakeSocketIO:
        def emit(self, event, payload):
            emitted.append((event, payload))

    monkeypatch.setattr(auth_db, "upsert_auth", lambda *args, **kwargs: 1)
    monkeypatch.setattr(auth_db, "clear_user_sessions", lambda username: None)
    monkeypatch.setattr(extensions, "socketio", FakeSocketIO())
    monkeypatch.setattr(
        "database.cache_invalidation.publish_all_cache_invalidation",
        lambda username: None,
    )
    monkeypatch.setattr("database.master_contract_cache_hook.clear_cache_on_logout", lambda: None)
    monkeypatch.setattr("database.settings_db.clear_settings_cache", lambda: None)
    monkeypatch.setattr("database.telegram_db.clear_telegram_cache", lambda: None)

    with app.test_request_context("/"):
        session["user"] = "rajandran"
        session_utils.revoke_user_tokens(revoke_db_tokens=True)

    assert ("active_sessions_update", {"count": 0, "sessions": []}) in emitted
    force_logout_events = [payload for event, payload in emitted if event == "force_logout"]
    assert force_logout_events
    assert "Session expired" in force_logout_events[0]["message"]
