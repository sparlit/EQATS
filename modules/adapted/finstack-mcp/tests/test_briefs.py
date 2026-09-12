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


from finstack.briefs import generate_daily_brief


def test_generate_daily_brief_shapes_output(monkeypatch):
    monkeypatch.setattr("finstack.briefs.get_market_status", lambda: {"status": "OPEN"})
    monkeypatch.setattr("finstack.briefs.get_index_data", lambda name: {"index": name, "value": 100})
    monkeypatch.setattr(
        "finstack.briefs.get_market_movers",
        lambda kind: {"stocks": [{"symbol": f"{kind.upper()}1", "change_pct": 1.5}]},
    )
    monkeypatch.setattr(
        "finstack.briefs.get_sector_performance",
        lambda: {"leaders": [{"sector": "IT", "change_pct": 2.1}]},
    )
    monkeypatch.setattr("finstack.briefs.get_fii_dii_data", lambda: {"data": "ok"})
    monkeypatch.setattr("finstack.briefs.get_bulk_deals", lambda: {"deals": []})
    monkeypatch.setattr(
        "finstack.briefs.get_quarterly_results",
        lambda symbol: {"latest_quarter": "2025-12-31", "quarters": [{"revenue": 10}]},
    )
    monkeypatch.setattr(
        "finstack.briefs.get_corporate_actions",
        lambda symbol: {"actions": [{"date": "2026-03-25", "type": "DIVIDEND"}]},
    )
    monkeypatch.setattr(
        "finstack.briefs.get_earnings_calendar",
        lambda symbol: {"symbol": symbol, "earnings_date": "2026-04-15"},
    )

    brief = generate_daily_brief(["RELIANCE", "TCS"], brief_date="2026-03-25")

    assert brief["brief_type"] == "indian_market_daily_brief"
    assert brief["brief_date"] == "2026-03-25"
    assert brief["indices"]["nifty50"]["index"] == "NIFTY50"
    assert len(brief["watchlist"]) == 2
    assert "Market status: OPEN." in brief["summary"]
    assert "delivery_formats" in brief
    assert "FinStack Brief | 2026-03-25" in brief["delivery_formats"]["plain_text"]
    assert "*FinStack Brief*" in brief["delivery_formats"]["telegram_markdown"]
    assert brief["delivery_formats"]["email"]["subject"].startswith("FinStack Brief | 2026-03-25")
