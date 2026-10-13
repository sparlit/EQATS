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


"""AliceBlue get_holdings and _invalidate_position_cache (issue #1773).

A merge split get_holdings() in two: the function ended right after
``result = _extract_result(response)`` and returned None, while its remaining
body - the None check, the empty check and the normalize_holding return - landed
inside _invalidate_position_cache(), referencing ``result`` and ``response``
that do not exist in that scope.

Two failures, and the second is the expensive one:

* get_holdings() returned None, so holdings_service raised
  ``TypeError: argument of type 'NoneType' is not iterable`` -> 500.
* _invalidate_position_cache() raised NameError. It runs immediately after a
  smart order is placed, so the order reached AliceBlue but the API answered 500
  with no orderid. A client that retries on failure places the position twice.
"""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

order_api = pytest.importorskip("broker.aliceblue.api.order_api")


HOLDING = {
    "tradingsymbol": "RELIANCE",
    "exchange": "NSE",
    "quantity": 10,
    "averageprice": 1300.0,
}


def test_invalidate_position_cache_only_clears_the_cache():
    """The guard on the double-order path: this must never raise.

    It runs right after a smart order is placed. A NameError here means the
    order exists at the broker but the caller sees a 500 with no orderid, and a
    retry doubles the position.
    """
    auth = "token-abc"
    order_api._position_cache[auth] = {"data": [{"x": 1}], "timestamp": 0.0}

    order_api._invalidate_position_cache(auth)  # must not raise

    assert auth not in order_api._position_cache


def test_invalidate_position_cache_tolerates_an_absent_entry():
    order_api._invalidate_position_cache("never-cached")  # must not raise


def test_get_holdings_returns_normalized_holdings():
    """It must return the list, not None."""
    with patch.object(
        order_api, "get_api_response", return_value={"status": "Ok", "result": [HOLDING]}
    ):
        result = order_api.get_holdings("token-abc")

    assert result is not None, "get_holdings returned None - the body is detached again"
    assert isinstance(result, list) and len(result) == 1


def test_get_holdings_returns_empty_list_when_there_are_no_holdings():
    """holdings_service does `if "status" in holdings`, so None raises TypeError."""
    response = {"status": "Not_Ok", "message": "No holding available"}
    with patch.object(order_api, "get_api_response", return_value=response):
        result = order_api.get_holdings("token-abc")

    assert result == []
    assert "status" in result or result == []  # the membership test must not raise


def test_get_holdings_surfaces_a_real_error():
    response = {"status": "Not_Ok", "message": "Session expired"}
    with patch.object(order_api, "get_api_response", return_value=response):
        result = order_api.get_holdings("token-abc")

    assert isinstance(result, dict)
    assert result.get("stat") == "Not_Ok"
    assert "Session expired" in result.get("emsg", "")


def test_get_holdings_returns_empty_list_for_an_empty_result():
    with patch.object(order_api, "get_api_response", return_value={"status": "Ok", "result": []}):
        assert order_api.get_holdings("token-abc") == []
