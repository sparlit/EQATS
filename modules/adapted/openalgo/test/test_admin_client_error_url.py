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


"""Tests for server-side URL sanitization of browser error reports."""

from urllib.parse import parse_qs, urlsplit

from blueprints.admin import _sanitize_client_error_url


def test_server_redacts_sensitive_query_values_and_fragments():
    """Keep safe query context while redacting sensitive values before logging."""
    sanitized = _sanitize_client_error_url(
        "https://app.example.com/search?symbol=INFY&token=test-token-not-real&apiKey=test-token-not-real#results"
    )
    parsed = urlsplit(sanitized)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://app.example.com/search"
    assert parse_qs(parsed.query) == {
        "symbol": ["INFY"],
        "token": ["[redacted]"],
        "apiKey": ["[redacted]"],
    }
    assert parsed.fragment == ""
    assert "test-token-not-real" not in sanitized


def test_server_handles_extension_and_opaque_urls_safely():
    """Keep extension filenames but drop opaque URL content."""
    assert (
        _sanitize_client_error_url("chrome-extension://abcdef/content.js?token=test-token-not-real")
        == "chrome-extension://abcdef/content.js"
    )
    assert _sanitize_client_error_url("data:text/html;base64,PAYLOAD") == "data:"
    assert _sanitize_client_error_url("blob:http://host/uuid") == "blob:"


def test_server_falls_back_for_malformed_urls():
    """Avoid raising or retaining a fragment when URL parsing fails."""
    assert _sanitize_client_error_url("http://[?token=test-token-not-real#fragment") == "http://["
