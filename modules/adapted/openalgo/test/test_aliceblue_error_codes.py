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


"""AliceBlue EC* error codes are expanded into readable text.

AliceBlue answers failures with a bare code and no prose, so a rejected order
surfaced to the user as the literal string "EC912". 15-error-code.md publishes
133 of them.
"""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ec = pytest.importorskip("broker.aliceblue.api.error_codes")
order_api = pytest.importorskip("broker.aliceblue.api.order_api")


def test_the_published_table_is_loaded():
    assert len(ec.ERROR_CODES) == 133
    assert ec.ERROR_CODES["EC912"] == "Failed to place the order."


@pytest.mark.parametrize(
    "code,fragment",
    [
        ("EC912", "Failed to place the order"),
        ("EC904", "positive number"),
        ("EC922", "No holdings found"),
        ("EC930", "LIMIT"),
    ],
)
def test_a_bare_code_is_expanded(code, fragment):
    out = ec.describe(code)
    assert out.startswith(f"{code}: ")
    assert fragment in out


def test_a_code_embedded_in_a_sentence_is_expanded_in_place():
    assert "positive number" in ec.describe("Order rejected: EC904")
    assert "Order rejected:" in ec.describe("Order rejected: EC904")


def test_an_unknown_code_passes_through_untouched():
    """Inventing a description would be worse than showing the raw code."""
    assert ec.describe("EC100") == "EC100"


def test_a_message_with_no_code_is_unchanged():
    assert ec.describe("Session expired") == "Session expired"


@pytest.mark.parametrize("value", ["", None])
def test_empty_input_is_returned_as_is(value):
    assert ec.describe(value) == value


def test_the_api_error_path_expands_codes():
    """_extract_result is the funnel every read error passes through."""
    with patch.object(order_api, "logger") as log:
        result = order_api._extract_result({"status": "Not_Ok", "message": "EC922"})

    assert result is None
    logged = " ".join(str(c) for c in log.error.call_args_list)
    assert "No holdings found" in logged, f"code was not expanded in the log: {logged}"
