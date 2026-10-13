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


"""Unit and integration tests for economic calendar queries (User Story 3)."""

import pytest
from tradingview import (
    EconomicEvent,
    EconomicImportance,
    TradingViewClient,
)


def test_economic_event_model() -> None:
    evt = EconomicEvent(
        id="12345",
        title="Non-Farm Payrolls",
        country="US",
        indicator="NFP",
        ticker="USNFP",
        date=1700000000,
        importance=EconomicImportance.High,
        actual=180000.0,
        forecast=170000.0,
        previous=165000.0,
    )
    assert evt.id == "12345"
    assert evt.title == "Non-Farm Payrolls"
    assert evt.country == "US"
    assert evt.indicator == "NFP"
    assert evt.ticker == "USNFP"
    assert evt.date == 1700000000
    assert evt.importance == EconomicImportance.High
    assert evt.actual == 180000.0
    assert evt.forecast == 170000.0
    assert evt.previous == 165000.0

    d = evt.to_dict()
    assert d["id"] == "12345"
    assert d["importance"] == 1
    assert d["actual"] == 180000.0


@pytest.mark.asyncio
async def test_get_economic_calendar() -> None:
    client = TradingViewClient()
    events = await client.get_economic_calendar(
        countries=["US"],
        min_importance=EconomicImportance.High,
    )

    assert isinstance(events, list)
    for evt in events:
        assert isinstance(evt, EconomicEvent)
        assert evt.country == "US"
        assert evt.importance == EconomicImportance.High

    await client.close()


@pytest.mark.asyncio
async def test_get_economic_calendar_polars_dataframe() -> None:
    import polars as pl

    client = TradingViewClient()
    df = await client.get_economic_calendar(
        countries=["US"],
        min_importance=EconomicImportance.High,
        as_dataframe=True,
    )
    assert isinstance(df, pl.DataFrame)
    assert "id" in df.columns
    assert "country" in df.columns
    assert "importance" in df.columns
    await client.close()
