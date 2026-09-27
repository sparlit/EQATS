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


"""Calendar tests: seeded NSE holidays incl. dates observed in the live run."""

from datetime import date

from indian_quant.instruments import NSECalendar


class TestNSECalendar:
    def test_weekends_not_trading(self):
        cal = NSECalendar()
        assert not cal.is_trading_day(date(2026, 8, 22))
        assert not cal.is_trading_day(date(2026, 8, 23))

    def test_fixed_holidays(self):
        cal = NSECalendar()
        assert not cal.is_trading_day(date(2026, 1, 26))
        assert not cal.is_trading_day(date(2026, 8, 15))
        assert not cal.is_trading_day(date(2026, 10, 2))
        assert not cal.is_trading_day(date(2026, 12, 25))

    def test_observed_2026_float_holidays(self):
        cal = NSECalendar()
        for d in (date(2026, 4, 3), date(2026, 4, 14), date(2026, 5, 1), date(2026, 5, 28), date(2026, 6, 26)):
            assert not cal.is_trading_day(d), d

    def test_regular_weekday_trades(self):
        cal = NSECalendar()
        assert cal.is_trading_day(date(2026, 8, 18))

    def test_extra_holidays(self):
        cal = NSECalendar(extra_holidays={date(2026, 8, 19)})
        assert not cal.is_trading_day(date(2026, 8, 19))
        assert NSECalendar().is_trading_day(date(2026, 8, 19))

    def test_trading_days_between_excludes_gap_holidays(self):
        cal = NSECalendar()
        days = cal.trading_days_between(date(2026, 4, 2), date(2026, 4, 6))
        assert days == [date(2026, 4, 2), date(2026, 4, 6)]

    def test_yearly_seed_covers_projected_window(self):
        cal = NSECalendar()
        for year in (2024, 2025, 2026, 2027):
            assert len(cal.holidays(year)) >= 7
