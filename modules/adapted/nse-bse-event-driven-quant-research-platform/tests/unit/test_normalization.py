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


"""Normalization tests: dedupe, corporate-action adjustment, resampling."""

from datetime import UTC, date, datetime

import pandas as pd
import pytest
from indian_quant.normalization import (
    apply_corporate_action_adjustment,
    deduplicate_bars,
    ist_session_close_utc,
    resample_bars,
    to_utc,
)
from indian_quant.schemas import (
    CorporateAction,
    CorporateActionType,
    MarketBar,
    Timeframe,
)


def bar(day: str, close: float, *, instrument_id="NSE_EQ|TEST", volume=1000.0):
    d = datetime.fromisoformat(day).replace(tzinfo=UTC)
    return MarketBar(
        instrument_id=instrument_id,
        exchange="NSE",
        timestamp=d,
        timeframe=Timeframe.DAY,
        open=close * 0.99,
        high=close * 1.01,
        low=close * 0.98,
        close=close,
        volume=volume,
        source="NSE",
    )


class TestDeduplicate:
    def test_keeps_first_of_exact_duplicates(self):
        b1 = bar("2025-06-02T00:00:00+00:00", 100)
        b2 = bar("2025-06-02T00:00:00+00:00", 100)
        assert len(deduplicate_bars([b1, b2])) == 1

    def test_sorts_by_time(self):
        late = bar("2025-06-03T00:00:00+00:00", 101)
        early = bar("2025-06-02T00:00:00+00:00", 100)
        out = deduplicate_bars([late, early])
        assert [b.timestamp for b in out] == sorted(b.timestamp for b in out)


class TestCorporateActionAdjustment:
    def test_split_back_adjustment(self):
        action = CorporateAction(
            instrument_id="NSE_EQ|TEST",
            action_type=CorporateActionType.SPLIT,
            old_value=10.0,
            new_value=2.0,
            ex_date=date(2025, 6, 10),
            source="NSE",
        )
        before = bar("2025-06-05T00:00:00+00:00", 5000)
        after = bar("2025-06-12T00:00:00+00:00", 1000)
        adjusted = apply_corporate_action_adjustment([before, after], [action])
        assert adjusted[0].close == pytest.approx(1000.0)
        assert adjusted[0].adjustment_status.value == "FULLY_ADJUSTED"
        assert adjusted[1].close == pytest.approx(1000.0)
        assert adjusted[1].adjustment_status.value == "UNADJUSTED"

    def test_volume_scales_inverse(self):
        action = CorporateAction(
            instrument_id="NSE_EQ|TEST",
            action_type=CorporateActionType.SPLIT,
            old_value=10.0,
            new_value=2.0,
            ex_date=date(2025, 6, 10),
            source="NSE",
        )
        before = bar("2025-06-05T00:00:00+00:00", 5000, volume=100)
        adjusted = apply_corporate_action_adjustment([before], [action])
        assert adjusted[0].volume == pytest.approx(500.0)

    def test_dividend_not_applied_by_default(self):
        action = CorporateAction(
            instrument_id="NSE_EQ|TEST",
            action_type=CorporateActionType.DIVIDEND,
            amount=10.0,
            ex_date=date(2025, 6, 10),
            source="NSE",
        )
        before = bar("2025-06-05T00:00:00+00:00", 100)
        adjusted = apply_corporate_action_adjustment([before], [action])
        assert adjusted[0].close == pytest.approx(100.0)


class TestTimestamps:
    def test_to_utc_naive_becomes_utc(self):
        naive = datetime(2025, 6, 2, 10, 0)
        assert to_utc(naive).tzinfo is UTC

    def test_ist_session_close(self):
        day = datetime(2025, 6, 2, tzinfo=UTC)
        close = ist_session_close_utc(day)
        assert close.hour == 10
        assert close.minute == 0


class TestResample:
    def test_daily_to_weekly(self):
        days = pd.date_range("2025-06-02", periods=10, freq="D", tz="UTC")
        df = pd.DataFrame(
            {
                "timestamp": days,
                "open": 100.0,
                "high": 110.0,
                "low": 95.0,
                "close": range(100, 110),
                "volume": 1000.0,
            }
        )
        weekly = resample_bars(df, Timeframe.WEEK)
        assert len(weekly) < len(df)
        assert {"open", "high", "low", "close", "volume"}.issubset(weekly.columns)
