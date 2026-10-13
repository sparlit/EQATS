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


import pytest
from marshmallow import ValidationError
from restx_api.data_schemas import validate_date_or_timestamp, validate_option_offset


class TestValidateDateOrTimestamp:
    """Tests for validate_date_or_timestamp validation function."""

    @pytest.mark.parametrize(
        "valid_input",
        [
            "2026-08-22",
            "1999-01-01",
            "2030-12-31",
            "1724300000",  # 10-digit epoch timestamp
            "1724300000000",  # 13-digit millisecond timestamp
        ],
    )
    def test_valid_date_or_timestamp(self, valid_input: str):
        # Should execute without raising ValidationError
        result = validate_date_or_timestamp(valid_input)
        assert result is None

    @pytest.mark.parametrize(
        "invalid_input",
        [
            "2026/08/22",
            "22-08-2026",
            "2026-8-2",
            "invalid_string",
            "",
            "12345",  # Too short for timestamp
            "123456789012345",  # Too long for timestamp
            None,
            1724300000,  # Integer type instead of string
        ],
    )
    def test_invalid_date_or_timestamp(self, invalid_input):
        with pytest.raises(ValidationError):
            validate_date_or_timestamp(invalid_input)


class TestValidateOptionOffset:
    """Tests for validate_option_offset validation function."""

    @pytest.mark.parametrize(
        "valid_offset",
        [
            "ATM",
            "atm",
            "ITM1",
            "itm1",
            "ITM25",
            "itm25",
            "ITM50",
            "itm50",
            "OTM1",
            "otm1",
            "OTM25",
            "otm25",
            "OTM50",
            "otm50",
        ],
    )
    def test_valid_option_offset(self, valid_offset: str):
        assert validate_option_offset(valid_offset) is True

    @pytest.mark.parametrize(
        "invalid_offset",
        [
            "ITM0",
            "ITM51",
            "ITM100",
            "OTM0",
            "OTM51",
            "OTM100",
            "ATM1",
            "INVALID",
            "",
        ],
    )
    def test_invalid_option_offset(self, invalid_offset: str):
        with pytest.raises(ValidationError):
            validate_option_offset(invalid_offset)
