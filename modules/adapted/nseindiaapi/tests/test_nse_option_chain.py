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


class TestNSEOptionChain(unittest.TestCase):
    def setUp(self):
        DIR = Path(__file__).parent
        self.nse = NSE(DIR, server=False)
        self.cache_file = DIR / "opt-expiry.json"

    def tearDown(self):
        self.nse.exit()
        self.cache_file.unlink(missing_ok=True)

    def _mock_req(self, responses) -> MagicMock:
        """Helper to mock _NSE__req returning different .json() values
        on sequential calls.
        """
        mock = MagicMock()
        mock.side_effect = [MagicMock(json=MagicMock(return_value=resp)) for resp in responses]
        self.nse._transport.request = mock
        return mock

    def test_uses_cached_expiry_when_valid(self):
        expiry = datetime(2099, 1, 1)
        cache = {"nifty": expiry.isoformat()}

        self.cache_file.write_text(json.dumps(cache))

        mock = self._mock_req([{"data": "OK"}])

        result = self.nse.optionChain("nifty")

        assert result == {"data": "OK"}
        mock.assert_called_once()

    def test_expired_cached_expiry_is_ignored(self):
        expiry = datetime(2000, 1, 1)
        cache = {"nifty": expiry.isoformat()}
        self.cache_file.write_text(json.dumps(cache))

        responses = [
            {"expiryDates": ["01-Jan-2099"]},
            {"data": "ok"},
        ]

        mock = self._mock_req(responses)

        result = self.nse.optionChain("nifty")

        assert result == {"data": "ok"}
        assert mock.call_count == 2

    def test_missing_expiry_dates_raises(self):
        self._mock_req([{}])

        with pytest.raises(ValueError) as ctx:
            self.nse.optionChain("nifty")

        assert "expiryDates" in str(ctx.value)

    def test_empty_expiry_dates_raises(self):
        self._mock_req([{"expiryDates": []}])

        with pytest.raises(ValueError) as ctx:
            self.nse.optionChain("nifty")

        assert "No expiry dates" in str(ctx.value)

    def test_writes_expiry_cache_file(self):
        self._mock_req(
            [
                {"expiryDates": ["01-Jan-2099"]},
                {},
            ]
        )

        self.nse.optionChain("nifty")

        assert self.cache_file.exists()

        data = json.loads(self.cache_file.read_text())
        assert "nifty" in data

    def test_equity_type_for_non_index_symbol(self):
        responses = [
            {"expiryDates": ["01-Jan-2099"]},
            {"data": "ok"},
        ]
        mock = self._mock_req(responses)

        self.nse.optionChain("reliance")

        _, kwargs = mock.call_args
        assert kwargs["params"]["type"] == "Equity"

    def test_indices_type_for_index_symbol(self):
        responses = [
            {"expiryDates": ["01-Jan-2099"]},
            {"data": "ok"},
        ]
        mock = self._mock_req(responses)

        self.nse.optionChain("nifty")

        _, kwargs = mock.call_args
        assert kwargs["params"]["type"] == "Indices"

    def test_explicit_expiry_date_skips_cache_and_contract_info(self):
        expiry = datetime(2099, 1, 1)
        mock = self._mock_req([{"data": "ok"}])

        result = self.nse.optionChain("nifty", expiry_date=expiry)

        assert result == {"data": "ok"}
        mock.assert_called_once()

    def test_corrupt_cache_file_is_ignored(self):
        self.cache_file.write_text("invalid json")

        responses = [
            {"expiryDates": ["01-Jan-2099"]},
            {"data": "ok"},
        ]
        mock = self._mock_req(responses)

        result = self.nse.optionChain("nifty")

        assert result == {"data": "ok"}
        assert mock.call_count == 2


if __name__ == "__main__":
    unittest.main()
