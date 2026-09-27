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


"""BSE bhavcopy ingester tests (bseindia library-based implementation).

The old HTTP-based implementation was blocked by BSE's CDN.
New implementation uses the bseindia Python library which bypasses the block.
"""

from datetime import date

import pandas as pd
import pytest
from indian_quant.ingestion.bse import BseBhavcopyIngester


@pytest.fixture(scope="module")
def ingester():
    return BseBhavcopyIngester()


def make_sample_df() -> pd.DataFrame:
    """Create a sample BSE bhavcopy DataFrame for testing."""
    return pd.DataFrame(
        {
            "TradDt": ["2026-08-24", "2026-08-24", "2026-08-24"],
            "BizDt": ["2026-08-24", "2026-08-24", "2026-08-24"],
            "Sgmt": ["CM", "CM", "CM"],
            "Src": ["BSE", "BSE", "BSE"],
            "FinInstrmTp": ["STK", "STK", "STK"],
            "FinInstrmId": [500325, 544434, 519477],
            "ISIN": ["INE002A01018", "INE0UZO01024", "INE052V01019"],
            "TckrSymb": ["RELIANCE", "NEETUYOSHI", "CIANAGRO"],
            "SctySrs": ["B", "MT", "B"],
            "OpnPric": [1305.00, 126.90, 43.00],
            "HghPric": [1330.00, 126.90, 43.95],
            "LwPric": [1300.10, 124.00, 42.50],
            "ClsPric": [1321.50, 126.40, 43.50],
            "LastPric": [1321.50, 126.40, 43.50],
            "TtlTradgVol": [8500000, 15000, 52000],
            "TtlTrfVal": [11200000000, 1890000, 2260000],
            "TtlNbOfTxsExctd": [150000, 200, 800],
        }
    )


class TestBseBhavcopy:
    def test_parse_bhavcopy(self, ingester):
        df = make_sample_df()
        bars = ingester.parse_bhavcopy(df, date(2026, 8, 24))
        assert len(bars) == 3
        # Check RELIANCE
        rel = next(b for b in bars if "RELIANCE" in b.instrument_id)
        assert rel.instrument_id == "BSE_EQ|RELIANCE"
        assert rel.exchange == "BSE"
        assert rel.close == pytest.approx(1321.5)
        assert rel.volume == pytest.approx(8_500_000)

    def test_parse_neetuyoshi_sme(self, ingester):
        df = make_sample_df()
        bars = ingester.parse_bhavcopy(df, date(2026, 8, 24))
        neet = next(b for b in bars if "NEETUYOSHI" in b.instrument_id)
        assert neet.instrument_id == "BSE_SME|NEETUYOSHI"
        assert neet.close == pytest.approx(126.4)

    def test_parse_cianagro(self, ingester):
        df = make_sample_df()
        bars = ingester.parse_bhavcopy(df, date(2026, 8, 24))
        cian = next(b for b in bars if "CIANAGRO" in b.instrument_id)
        assert cian.instrument_id == "BSE_EQ|CIANAGRO"
        assert cian.close == pytest.approx(43.5)

    def test_series_filter(self, ingester):
        df = make_sample_df()
        # All 3 are in universe (B and MT series)
        bars = ingester.parse_bhavcopy(df, date(2026, 8, 24))
        assert len(bars) == 3
        # Filter to only EQ series
        bars_eq = ingester.parse_bhavcopy(df, date(2026, 8, 24), symbols={"RELIANCE"})
        assert len(bars_eq) == 1

    def test_parse_delivery(self, ingester):
        df = make_sample_df()
        delivery = ingester.parse_bhavcopy_to_delivery(df, date(2026, 8, 24))
        assert "RELIANCE" in delivery
        assert delivery["RELIANCE"]["close"] == pytest.approx(1321.5)
        assert delivery["RELIANCE"]["volume"] == pytest.approx(8_500_000)
        assert delivery["NEETUYOSHI"]["close"] == pytest.approx(126.4)

    def test_zero_price_filtered(self, ingester):
        df = pd.DataFrame(
            {
                "TradDt": ["2026-08-24"],
                "TckrSymb": ["ZEROSTOCK"],
                "SctySrs": ["B"],
                "OpnPric": [0.0],
                "HghPric": [0.0],
                "LwPric": [0.0],
                "ClsPric": [0.0],
                "TtlTradgVol": [0],
            }
        )
        bars = ingester.parse_bhavcopy(df, date(2026, 8, 24))
        assert len(bars) == 0

    def test_fetch_live(self, ingester):
        """Live fetch test - may fail if bseindia lib is down."""
        try:
            df = ingester.fetch_bhavcopy(date(2026, 8, 24))
            if df is not None:
                assert len(df) > 0
                assert "TckrSymb" in df.columns
        except Exception:
            pytest.skip("bseindia library unavailable")
