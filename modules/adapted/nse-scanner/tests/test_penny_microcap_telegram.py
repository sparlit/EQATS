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


from unittest.mock import patch

from penny_microcap.telegram import render_topic_messages, send_messages


class Response:
    def raise_for_status(self):
        return None


def test_dedicated_penny_route(monkeypatch):
    monkeypatch.setenv("PENNY_TELEGRAM_BOT_TOKEN", "penny-token")
    monkeypatch.setenv("PENNY_TELEGRAM_CHAT_ID", "-100444")
    monkeypatch.setenv("PENNY_TOPIC_EARLY_RADAR", "601")
    with patch("penny_microcap.telegram.requests.post", return_value=Response()) as post:
        result = send_messages(["hello"], "early_radar", enabled=True)
    assert result.sent
    assert post.call_args.args[0] == "https://api.telegram.org/botpenny-token/sendMessage"
    assert post.call_args.kwargs["json"]["chat_id"] == "-100444"
    assert post.call_args.kwargs["json"]["message_thread_id"] == 601


def test_missing_penny_secrets_fail_closed(monkeypatch):
    for name in ("PENNY_TELEGRAM_BOT_TOKEN", "PENNY_TELEGRAM_CHAT_ID", "PENNY_TOPIC_CIRCUIT_RISK"):
        monkeypatch.delenv(name, raising=False)
    assert send_messages(["hello"], "circuit_risk", enabled=True).reason == "credentials_not_configured"


def test_missing_topic_is_reported_by_name(monkeypatch):
    monkeypatch.setenv("PENNY_TELEGRAM_BOT_TOKEN", "penny-token")
    monkeypatch.setenv("PENNY_TELEGRAM_CHAT_ID", "-100444")
    monkeypatch.delenv("PENNY_TOPIC_READY", raising=False)
    result = send_messages(["hello"], "ready", enabled=True)
    assert not result.sent
    assert result.reason == "topic_not_configured:ready"


def test_all_six_topics_use_their_own_thread(monkeypatch):
    monkeypatch.setenv("PENNY_TELEGRAM_BOT_TOKEN", "penny-token")
    monkeypatch.setenv("PENNY_TELEGRAM_CHAT_ID", "-100444")
    routes = {
        "early_radar": ("PENNY_TOPIC_EARLY_RADAR", 601),
        "confirming": ("PENNY_TOPIC_CONFIRMING", 602),
        "ready": ("PENNY_TOPIC_READY", 603),
        "circuit_risk": ("PENNY_TOPIC_CIRCUIT_RISK", 604),
        "portfolio": ("PENNY_TOPIC_PORTFOLIO", 605),
        "system": ("PENNY_TOPIC_SYSTEM", 606),
    }
    for variable, thread_id in routes.values():
        monkeypatch.setenv(variable, str(thread_id))
    with patch("penny_microcap.telegram.requests.post", return_value=Response()) as post:
        for route, (_, thread_id) in routes.items():
            assert send_messages([route], route, enabled=True).sent
            assert post.call_args.kwargs["json"]["message_thread_id"] == thread_id


def test_each_candidate_state_renders_only_in_its_topic():
    report = {
        "as_of_date": "2026-08-25",
        "universe_symbols": 3,
        "selected": 3,
        "counts": {"EARLY_RADAR": 1, "CONFIRMING": 1, "READY": 1},
        "candidates": [
            {"symbol": "EARLY", "state": "EARLY_RADAR", "score": 40, "close": 10, "metrics": {}},
            {"symbol": "CONFIRM", "state": "CONFIRMING", "score": 60, "close": 20, "metrics": {}},
            {
                "symbol": "READYONE",
                "state": "READY",
                "score": 80,
                "close": 30,
                "stop": 27,
                "target1": 36,
                "target2": 39,
                "metrics": {},
            },
        ],
    }
    early = "\n".join(render_topic_messages(report, "early_radar"))
    confirming = "\n".join(render_topic_messages(report, "confirming"))
    ready = "\n".join(render_topic_messages(report, "ready"))
    assert "EARLY" in early
    assert "CONFIRM" not in early
    assert "READYONE" not in early
    assert "CONFIRM" in confirming
    assert "EARLY" not in confirming
    assert "READYONE" not in confirming
    assert "READYONE" in ready
    assert "EARLY" not in ready
    assert "CONFIRM" not in ready


def test_portfolio_and_system_have_dedicated_summaries():
    report = {
        "as_of_date": "2026-08-25",
        "strategy_version": "v1",
        "universe_symbols": 10,
        "selected": 0,
        "counts": {},
        "candidates": [],
    }
    assert "No simulated positions" in render_topic_messages(report, "portfolio")[0]
    assert "HEALTHY" in render_topic_messages(report, "system")[0]
