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


"""Quality engine tests."""

from datetime import UTC, date, datetime

from indian_quant.quality import run_quality_suite
from indian_quant.schemas import MarketBar, Timeframe


def bar(day: str, close: float, *, instrument_id="NSE_EQ|TEST", high=None, low=None):
    d = datetime.fromisoformat(day).replace(tzinfo=UTC)
    return MarketBar(
        instrument_id=instrument_id,
        exchange="NSE",
        timestamp=d,
        timeframe=Timeframe.DAY,
        open=close * 0.99,
        high=high if high is not None else close * 1.01,
        low=low if low is not None else close * 0.98,
        close=close,
        volume=1000.0,
        source="NSE",
    )


def weekdays(start: str, count: int):
    from datetime import timedelta

    d = date.fromisoformat(start)
    out = []
    while len(out) < count:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


class TestQualitySuite:
    def test_clean_series_passes(self):
        days = weekdays("2025-06-02", 10)
        bars = [bar(d.isoformat() + "T00:00:00+00:00", 100 + i) for i, d in enumerate(days)]
        report, unique = run_quality_suite(bars, dataset="test")
        assert report.passed
        assert len(unique) == len(bars)

    def test_duplicate_detected(self):
        b = bar("2025-06-02T00:00:00+00:00", 100)
        report, _ = run_quality_suite([b, b], dataset="test")
        assert not report.passed or any(i.code == "DUPLICATE" for i in report.issues)

    def test_price_jump_flagged(self):
        bars = [
            bar("2025-06-02T00:00:00+00:00", 100),
            bar("2025-06-03T00:00:00+00:00", 200),
        ]
        report, _ = run_quality_suite(bars, dataset="test")
        assert any(i.code == "PRICE_JUMP" for i in report.issues)

    def test_missing_sessions_flagged(self):
        bars = [
            bar("2025-06-02T00:00:00+00:00", 100),
            bar("2025-06-13T00:00:00+00:00", 101),
        ]
        report, _ = run_quality_suite(bars, dataset="test", max_gap_days=15)
        assert any(i.code == "MISSING_SESSIONS" for i in report.issues)

    def test_holidays_suppress_gap_warnings(self):
        bars = [
            bar("2025-06-02T00:00:00+00:00", 100),
            bar("2025-06-09T00:00:00+00:00", 101),
        ]
        holidays = set(weekdays("2025-06-03", 4))
        report, _ = run_quality_suite(bars, dataset="test", holidays=holidays)
        assert not any(i.code == "MISSING_SESSIONS" for i in report.issues)

    def test_report_dict_shape(self):
        report, _ = run_quality_suite([], dataset="empty")
        payload = report.to_dict()
        assert {"dataset", "n_rows", "n_errors", "n_warnings", "issues"} <= set(payload)
