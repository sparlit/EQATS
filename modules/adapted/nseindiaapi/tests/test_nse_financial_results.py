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


import json
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from context import NSE

DIR = Path(__file__).parent
SAMPLES = DIR.parent / "src" / "samples"


class TestNseFinancialResults(unittest.TestCase):
    """Unit tests for financial_results and results_comparison (mocked _req)."""

    @classmethod
    def setUpClass(cls):
        cls.nse = NSE(download_folder=DIR, server=False)

    @classmethod
    def tearDownClass(cls):
        cls.nse.exit()

    def _mock_req_json(self, payload):
        mock = MagicMock()
        mock.return_value.json.return_value = payload
        self.nse._transport.request = mock
        return mock

    def test_financial_results_params(self):
        sample = json.loads((SAMPLES / "financial_results.json").read_text())
        mock = self._mock_req_json(sample)

        from_dt = datetime(2025, 1, 1)
        to_dt = datetime(2025, 3, 31)

        result = self.nse.financial_results(
            segment="equities",
            period="quarterly",
            symbol="reliance",
            from_date=from_dt,
            to_date=to_dt,
        )

        assert result == sample
        mock.assert_called_once()
        _, kwargs = mock.call_args
        assert kwargs["params"] == {
            "index": "equities",
            "period": "quarterly",
            "symbol": "RELIANCE",
            "from_date": "01-01-2025",
            "to_date": "31-03-2025",
        }

    def test_financial_results_date_validation(self):
        with pytest.raises(ValueError):
            self.nse.financial_results(
                from_date=datetime(2025, 3, 1),
                to_date=datetime(2025, 1, 1),
            )

    def test_results_comparison(self):
        sample = json.loads((SAMPLES / "results_comparison.json").read_text())
        mock = self._mock_req_json(sample)

        result = self.nse.results_comparison("reliance")

        assert result == sample
        assert "resCmpData" in result
        mock.assert_called_once()
        args, kwargs = mock.call_args
        assert args[0].endswith("/results-comparision")
        assert kwargs["params"] == {"symbol": "RELIANCE"}


if __name__ == "__main__":
    unittest.main()
