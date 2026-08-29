"""
Unit and Integration Tests for RCNewsFeeder Engine.
"""

from datetime import datetime
import pytest

from institutional_integrations.rc_news_feeder import (
    RCNewsFeederEngine,
    NewsImpact,
)


def test_rc_news_feeder_json_parsing_and_blackout():
    engine = RCNewsFeederEngine(high_impact_blackout_minutes_before=15.0, high_impact_blackout_minutes_after=15.0)

    raw_events = [
        {"title": "Consumer Price Index (CPI)", "country": "USD", "date": "2026-07-16T12:30:00Z", "impact": "High"},
        {"title": "ECB Interest Rate Decision", "country": "EUR", "date": "2026-07-16T13:45:00Z", "impact": "High"},
        {"title": "Retail Sales", "country": "GBP", "date": "2026-07-16T08:00:00Z", "impact": "Medium"},
    ]

    count = engine.load_events_from_json(raw_events)
    assert count == 3

    # 1. USD Blackout active (5 mins before CPI)
    check_usd = engine.check_currency_news_blackout("USD", datetime(2026, 7, 16, 12, 25, 0))
    assert check_usd.blackout_active is True
    assert check_usd.event_title == "Consumer Price Index (CPI)"
    assert check_usd.minutes_until_event == 5.0

    # 2. USD Blackout inactive (1 hour before CPI)
    check_usd_safe = engine.check_currency_news_blackout("USD", datetime(2026, 7, 16, 11, 30, 0))
    assert check_usd_safe.blackout_active is False
