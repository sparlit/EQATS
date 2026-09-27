from __future__ import annotations

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


from unittest.mock import Mock, patch

from v2.telegram_delivery import send_admin_messages, send_messages


def _ok_response() -> Mock:
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"ok": True}
    return response


def _error_response(status: int, description: str) -> Mock:
    response = Mock()
    response.status_code = status
    response.json.return_value = {"ok": False, "description": description}
    response.text = description
    return response


def test_admin_delivery_uses_admin_chat_id(monkeypatch) -> None:
    monkeypatch.setenv("V3_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("V3_TELEGRAM_CHAT_ID", "user-123")
    monkeypatch.setenv("V3_ADMIN_CHAT_ID", "admin-456")
    with patch("v2.telegram_delivery.requests.post", return_value=_ok_response()) as post:
        result = send_admin_messages(["admin report"], enabled=True)
    assert result.sent is True
    assert result.message_count == 1
    assert post.call_args.kwargs["json"]["chat_id"] == "admin-456"
    assert post.call_args.args[0].endswith("/sendMessage")


def test_user_delivery_remains_on_user_chat_id(monkeypatch) -> None:
    monkeypatch.setenv("V3_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("V3_TELEGRAM_CHAT_ID", "user-123")
    monkeypatch.setenv("ADMIN_CHAT_ID", "admin-456")
    with patch("v2.telegram_delivery.requests.post", return_value=_ok_response()) as post:
        result = send_messages(["user report"], enabled=True)
    assert result.sent is True
    assert post.call_args.kwargs["json"]["chat_id"] == "user-123"


def test_topic_delivery_preserves_topic_with_url_only_dashboard_button(monkeypatch) -> None:
    monkeypatch.setenv("V3_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("V3_TELEGRAM_CHAT_ID", "group-123")
    message = (
        "🚀 ACTION CANDIDATES\n1 Fresh Actionable Stocks\n\n"
        "━━━━━━━━━━━━━━━━━━\n🥇 ABC\n3M • TREND CONTINUATION\nScore: 88/100\n\n"
        "Entry       ₹100.00\nSL          ₹94.00\nT1          ₹109.00\nT2          ₹118.00"
    )
    with patch("v2.telegram_delivery.requests.post", return_value=_ok_response()) as post:
        result = send_messages([message], enabled=True, message_thread_id=321)
    assert result.sent is True
    payload = post.call_args.kwargs["json"]
    assert payload["message_thread_id"] == 321
    button = payload["reply_markup"]["inline_keyboard"][0][0]
    assert button["url"].endswith("?startapp=v3")
    assert "callback_data" not in button


def test_v3_transport_does_not_generate_pine_controls(monkeypatch) -> None:
    monkeypatch.setenv("V3_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("V3_TELEGRAM_CHAT_ID", "group-123")
    message = (
        "📐 PINE HULL SIGNALS\n1 Fresh Paper Entries • 0 Watch\n\n"
        "━━━━━━━━━━━━━━━━━━\n🥇 RELIANCE\nPINE HULL • READY LONG\n\n"
        "Entry       ₹1,500.00\nSL          ₹1,450.00\nT1          ₹1,575.00\nT2          ₹1,650.00"
    )
    with patch("v2.telegram_delivery.requests.post", return_value=_ok_response()) as post:
        result = send_messages([message], enabled=True)
    assert result.sent is True
    button = post.call_args.kwargs["json"]["reply_markup"]["inline_keyboard"][0][0]
    assert button["url"].endswith("?startapp=v3")
    assert "callback_data" not in button


def test_html_failure_falls_back_to_plain_text(monkeypatch) -> None:
    monkeypatch.setenv("V3_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("V3_TELEGRAM_CHAT_ID", "group-123")
    responses = [_error_response(400, "Bad Request: rich message invalid"), _ok_response()]
    with patch("v2.telegram_delivery.requests.post", side_effect=responses) as post:
        result = send_messages(["plain-compatible report"], enabled=True)
    assert result.sent is True
    assert post.call_count == 2
    assert post.call_args_list[0].args[0].endswith("/sendMessage")
    assert post.call_args_list[1].args[0].endswith("/sendMessage")
    assert "sent_plain_text_fallback" in result.reason


def test_topic_html_fallback_never_crosses_to_general(monkeypatch) -> None:
    monkeypatch.setenv("V3_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("V3_TELEGRAM_CHAT_ID", "group-123")
    responses = [_error_response(400, "Bad Request: message thread not found"), _ok_response()]
    with patch("v2.telegram_delivery.requests.post", side_effect=responses) as post:
        result = send_messages(["report"], enabled=True, message_thread_id=999)
    assert result.sent is True
    assert post.call_count == 2
    assert post.call_args_list[0].kwargs["json"]["message_thread_id"] == 999
    assert post.call_args_list[1].kwargs["json"]["message_thread_id"] == 999
    assert "sent_plain_text_fallback" in result.reason


def test_missing_admin_chat_id_does_not_raise(monkeypatch) -> None:
    monkeypatch.setenv("V3_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.delenv("ADMIN_CHAT_ID", raising=False)
    monkeypatch.delenv("V2_ADMIN_CHAT_ID", raising=False)
    monkeypatch.delenv("V3_ADMIN_CHAT_ID", raising=False)
    monkeypatch.delenv("V3_TELEGRAM_CHAT_ID", raising=False)
    result = send_admin_messages(["admin report"], enabled=True)
    assert result.sent is False
    assert result.reason == "admin_telegram_credentials_missing"


def test_admin_delivery_dry_run(monkeypatch) -> None:
    monkeypatch.setenv("V3_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_CHAT_ID", "admin-456")
    result = send_admin_messages(["admin report"], enabled=False)
    assert result.sent is False
    assert result.reason == "dry_run"
