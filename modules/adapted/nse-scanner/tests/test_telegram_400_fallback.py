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


from unittest.mock import Mock

from v2.telegram_delivery import send_messages


def _response(status: int, description: str = "") -> Mock:
    response = Mock()
    response.status_code = status
    response.text = description
    response.json.return_value = (
        {"ok": True, "result": {}} if status < 400 else {"ok": False, "error_code": status, "description": description}
    )
    return response


def test_invalid_topic_plain_fallback_stays_in_same_topic(monkeypatch):
    monkeypatch.setenv("V3_TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("V3_TELEGRAM_CHAT_ID", "-100123")
    post = Mock(
        side_effect=[
            _response(400, "Bad Request: message thread not found"),
            _response(200),
        ]
    )
    monkeypatch.setattr("v2.telegram_delivery.requests.post", post)

    result = send_messages(["hello"], enabled=True, message_thread_id=999)

    assert result.sent
    assert result.message_count == 1
    assert post.call_count == 2
    assert "message_thread_id" in post.call_args_list[0].kwargs["json"]
    assert post.call_args_list[1].kwargs["json"]["message_thread_id"] == 999


def test_delivery_failure_does_not_raise(monkeypatch):
    monkeypatch.setenv("V3_TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("V3_TELEGRAM_CHAT_ID", "-100123")
    monkeypatch.setattr(
        "v2.telegram_delivery.requests.post",
        Mock(return_value=_response(400, "Bad Request: chat not found")),
    )

    result = send_messages(["hello"], enabled=True)

    assert not result.sent
    assert result.message_count == 0
    assert "chat not found" in result.reason


def test_scheduled_delivery_adds_url_only_dashboard_keyboard(monkeypatch):
    monkeypatch.setenv("V3_TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("V3_TELEGRAM_CHAT_ID", "-100123")
    post = Mock(return_value=_response(200))
    monkeypatch.setattr("v2.telegram_delivery.requests.post", post)
    message = "ALL ACTIONABLE CANDIDATES\n" + "\n".join(f"{index}. STOCK{index}" for index in range(1, 61))

    result = send_messages([message], enabled=True)

    assert result.sent
    keyboard = post.call_args.kwargs["json"]["reply_markup"]
    button = keyboard["inline_keyboard"][0][0]
    assert button["text"] == "📊 Open Scanner Dashboard"
    assert button["url"].endswith("?startapp=v3")
    assert "callback_data" not in button
