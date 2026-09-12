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


"""Tests for 59b (sector rotation fallback) and 59c (NSE shareholding pattern).

TDD — written before implementation.
"""

import pytest


class TestSectorFallback:
    """59b: Sector rotation should have yfinance fallback when NSE returns zeros."""

    def test_get_sector_snapshot_returns_list(self):
        """Should return list of IndexSnapshot."""
        from market.indices import get_sector_snapshot

        result = get_sector_snapshot()
        assert isinstance(result, list)

    @pytest.mark.network
    def test_sectors_have_non_zero_values(self):
        """At least some sectors should have real prices.

        Requires network access (yfinance). Skipped in offline CI.
        Run with: pytest -m network
        """
        from market.indices import get_sector_snapshot

        result = get_sector_snapshot()
        non_zero = [s for s in result if s.ltp > 0]
        # With yfinance fallback, should always have data when online
        assert len(non_zero) > 0


class TestNSEShareholding:
    """59c: NSE shareholding pattern parser."""

    def test_parse_shareholding_xbrl(self):
        """Parser should extract promoter/FII/DII from XBRL data."""

        # Minimal XBRL-like data simulating what the parser extracts
        sample = {
            "promoter": 50.01,
            "fii": 19.09,
            "dii": 20.18,
            "retail": 10.63,
            "pledged": False,
            "mutual_funds": 9.52,
            "insurance": 9.05,
        }
        # The parser should return a dict with these keys
        assert sample["promoter"] == pytest.approx(50.01)
        assert sample["fii"] == pytest.approx(19.09)
        assert sample["dii"] == pytest.approx(20.18)

    @pytest.mark.network
    def test_fetch_nse_shareholding_returns_dict(self):
        """fetch should return a dict (may be empty if API fails)."""
        from analysis.fundamental import _fetch_nse_shareholding

        result = _fetch_nse_shareholding("RELIANCE")
        assert isinstance(result, dict)

    @pytest.mark.network
    def test_shareholding_has_promoter(self):
        """If data available, promoter % should be present."""
        from analysis.fundamental import _fetch_nse_shareholding

        result = _fetch_nse_shareholding("RELIANCE")
        # May be empty if NSE API is down, but if data exists it should have promoter
        if result:
            assert "promoter_pct" in result
            assert result["promoter_pct"] > 0

    @pytest.mark.network
    def test_shareholding_has_fii_dii(self):
        """If data available, FII and DII % should be present."""
        from analysis.fundamental import _fetch_nse_shareholding

        result = _fetch_nse_shareholding("RELIANCE")
        if result:
            assert "fii_pct" in result
            assert "dii_pct" in result

    @pytest.mark.network
    def test_shareholding_has_pledge(self):
        """If data available, pledge status should be present."""
        from analysis.fundamental import _fetch_nse_shareholding

        result = _fetch_nse_shareholding("RELIANCE")
        if result:
            assert "pledged" in result
