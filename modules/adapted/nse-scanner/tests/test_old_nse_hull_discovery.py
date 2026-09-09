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

import pandas as pd
from old_nse_hull.delivery import send_radar, send_trades
from old_nse_hull.discovery import discover
from old_nse_hull.engine import render_paper_trades, render_radar


def test_discovery_uses_acceleration_shortlist_without_paper_entry():
    days = pd.bdate_range("2025-01-01", periods=70)
    rows = []
    for symbol, start in (("AAA", 100), ("BBB", 80)):
        for index, day in enumerate(days):
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": day,
                    "close": start + index * (2 if symbol == "AAA" else 1),
                    "volume": 100_000,
                }
            )
    result = discover(pd.DataFrame(rows))
    assert set(result.shortlist["symbol"]) == {"AAA", "BBB"}
    assert {"rs_acceleration", "price_acceleration", "early_signal_count"}.issubset(result.shortlist.columns)


def test_discovery_can_surface_fresh_acceleration_without_positive_1m_return():
    days = pd.bdate_range("2025-01-01", periods=80)
    close = pd.Series(
        [100 - index * 0.12 for index in range(70)] + [91.6, 91.7, 91.8, 91.9, 92.0, 92.1, 92.25, 92.4, 92.6, 92.8]
    )
    frame = pd.DataFrame(
        {"symbol": "TURN", "trade_date": days, "close": close, "volume": [100_000] * 75 + [140_000] * 5}
    )
    result = discover(frame)
    assert not result.shortlist.empty
    row = result.shortlist.iloc[0]
    assert row["momentum_1m"] < 0
    assert row["early_signal_count"] >= 4


def test_paper_radar_identifies_the_active_python_hull_rules():
    report = {
        "generated_at": "2026-08-19T06:00:00+05:30",
        "as_of_date": "2026-08-18",
        "eligible": 2,
        "discovery_qualified": 1,
        "ready": 0,
        "watch": 1,
        "shortlist": [{"symbol": "AAA", "discovery_score": 90.0}],
    }
    text = render_radar(report)
    assert "DAILY WATCHLIST" in text
    assert "SIMULATED WATCHLIST" in text
    assert "Watch for entry: 0" in text


def test_old_hull_delivery_uses_its_own_optional_topic(monkeypatch):
    monkeypatch.setenv("LADDER_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("LADDER_TELEGRAM_CHAT_ID", "group-123")
    monkeypatch.setenv("LADDER_DAILY_TOPIC_ID", "88")
    response = Mock()
    response.raise_for_status.return_value = None
    with patch("old_nse_hull.delivery.requests.post", return_value=response) as post:
        result = send_radar("<b>PAPER SYSTEM</b>")
    assert result.sent
    assert post.call_args.kwargs["json"]["message_thread_id"] == 88


def test_ladder_portfolio_never_uses_retired_pine_topic(monkeypatch):
    monkeypatch.setenv("LADDER_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("LADDER_TELEGRAM_CHAT_ID", "group-123")
    monkeypatch.setenv("LADDER_PORTFOLIO_TOPIC_ID", "99")
    response = Mock()
    response.raise_for_status.return_value = None
    with patch("old_nse_hull.delivery.requests.post", return_value=response) as post:
        result = send_trades("<b>PAPER</b>")
    assert result.sent
    assert post.call_args.kwargs["json"]["message_thread_id"] == 99


def test_paper_trade_topic_never_treats_ready_as_entered():
    report = {
        "as_of_date": "2026-08-18",
        "shortlist": [{"symbol": "AAA", "discovery_score": 90.0, "discovery_rank": 1, "hull_state": "READY"}],
    }
    text = render_paper_trades(report)
    assert "PORTFOLIO" in text
    assert "No simulated positions" in text
