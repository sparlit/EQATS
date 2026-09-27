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


from telegram_dashboard import dashboard_keyboard, dashboard_url, status_label


def test_plain_language_status_contract():
    assert status_label("EARLY_RADAR") == "Early watchlist"
    assert status_label("CONFIRMING") == "Watchlist—wait for confirmation"
    assert status_label("READY") == "Watch for entry"
    assert status_label("NEW_TRIGGER") == "New simulated position"
    assert status_label("EXTENDED") == "Wait for pullback"
    assert status_label("CIRCUIT_LOCKED") == "No entry—circuit risk"
    assert status_label("WAIT") == "No action yet"


def test_dashboard_link_selects_scanner(monkeypatch):
    monkeypatch.delenv("NSE_MINI_APP_URL", raising=False)
    assert dashboard_url("ladder").endswith("?startapp=ladder")
    button = dashboard_keyboard("penny")["inline_keyboard"][0][0]
    assert button["url"].endswith("?startapp=penny")
    assert set(button) == {"text", "url"}
