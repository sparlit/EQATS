from __future__ import annotations

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


"""
The MIS leverage screen.

On 2026-08-31 NSE:SHIPROCKET-EQ passed all six gates, reached an order, and was
rejected by the broker:

    RED:RULE:{Allowed Basket} in Basket NSE.MIS.NSE_MIS_BASKET [FYERS_RISK_CUG]

Fyers does not publish an "MIS allowed" flag. The margin calculator is the only
signal, and it is unambiguous: measured live over that session's 22 candidates,
12 symbols sat at 4.0x/4.99x and 10 at exactly 1.0x, with nothing in between.
At 1.0x the required margin equals the share price — SHIPROCKET needed ₹138.93
on a ₹138.89 share.

A leverage gate existed before and was removed in cd178cc ("root cause of 0
trades"). These tests pin the three things that made the old one fail: the host,
the response shape, and what happens when the lookup cannot answer.
"""

import threading
import types

import pytest
from shortcircuit.broker.fyers_broker_interface import FyersBrokerInterface


def broker(response=None, status=200, raises=None):
    """A stub carrying only what get_symbol_leverage_sync touches."""
    return types.SimpleNamespace(
        client_id="XX-100",
        access_token="tok",
        _leverage_cache={},
        _leverage_cache_lock=threading.Lock(),
        _low_leverage_blacklist=set(),
        _resp=response,
        _status=status,
        _raises=raises,
        _calls=[],
    )


@pytest.fixture
def patched(monkeypatch):
    """Swap requests.post inside the broker module; records every call."""
    import shortcircuit.broker.fyers_broker_interface as mod

    def install(stub):
        def fake_post(url, headers=None, json=None, timeout=None):
            stub._calls.append({"url": url, "json": json, "timeout": timeout})
            if stub._raises:
                raise stub._raises
            return types.SimpleNamespace(
                status_code=stub._status,
                json=lambda: stub._resp,
            )

        monkeypatch.setattr(mod.requests, "post", fake_post)
        return FyersBrokerInterface.get_symbol_leverage_sync.__get__(stub, FyersBrokerInterface)

    return install


# The exact response shape the live API returns (verified 2026-08-31).
def ok(margin):
    return {
        "code": 200,
        "message": "",
        "s": "ok",
        "data": {
            "margin_avail": 593.53,
            "margin_total": margin,
            "margin_new_order": margin,
            "prevMargin": 0,
        },
    }


# the reading itself


def test_margin_equal_to_price_reads_as_one_times(patched):
    """
    The signature of a symbol with no intraday leverage. SHIPROCKET's real
    numbers: ₹138.93 margin on a ₹138.89 share.
    """
    b = broker(ok(138.93))
    assert patched(b)("NSE:SHIPROCKET-EQ", 138.89) == pytest.approx(1.0, abs=0.01)


def test_a_normal_symbol_reads_around_five(patched):
    b = broker(ok(106.34))
    assert patched(b)("NSE:KIRIINDUS-EQ", 530.90) == pytest.approx(4.99, abs=0.01)


def test_the_response_is_a_dict_not_a_list(patched):
    """
    Regression on the old parser. It read response['data'][0]['margin'] — a
    list — against an API that returns a dict keyed 'margin_new_order'. That
    mismatch meant every lookup fell through to the error path.
    """
    b = broker({"code": 200, "s": "ok", "data": [{"margin": 106.34}]})
    assert patched(b)("NSE:KIRIINDUS-EQ", 530.90) is None, "a list must not parse"


def test_the_request_goes_to_the_sdk_host(patched):
    """
    The old code hardcoded api.fyers.in, which answers 500 for every symbol.
    The SDK's base is api-t1.fyers.in. Building the URL from the SDK means a
    vendor move is picked up rather than silently breaking the screen.
    """
    b = broker(ok(106.34))
    patched(b)("NSE:KIRIINDUS-EQ", 530.90)
    url = b._calls[0]["url"]
    assert url.endswith("/multiorder/margin")
    assert "api.fyers.in/api/v3/multiorder" not in url, "hardcoded dead host is back"


def test_it_asks_about_the_side_the_bot_actually_trades(patched):
    b = broker(ok(106.34))
    patched(b)("NSE:KIRIINDUS-EQ", 530.90)
    order = b._calls[0]["json"]["data"][0]
    assert order["side"] == -1, "this bot is short-only"
    assert order["productType"] == "INTRADAY"


# unknown must never mean "blocked"


@pytest.mark.parametrize(
    "kw,why",
    [
        ({"status": 500, "response": {}}, "server error"),
        ({"status": 401, "response": {}}, "expired token"),
        ({"response": {"s": "error", "message": "nope"}}, "broker said error"),
        ({"response": {"code": 200, "s": "ok", "data": {}}}, "no margin field"),
        ({"response": {"code": 200, "s": "ok", "data": {"margin_new_order": 0}}}, "zero margin"),
        ({"raises": ConnectionError("down")}, "transport failure"),
    ],
)
def test_an_unanswerable_lookup_returns_none(patched, kw, why):
    """
    None, never a number. The previous version returned 5.0 on failure, so the
    guard silently passed everything; an earlier one blocked and produced a
    session with zero trades. Neither is acceptable — the caller decides, and
    it fails open.
    """
    assert patched(broker(**kw))("NSE:X-EQ", 100.0) is None, why


@pytest.mark.parametrize("symbol,price", [("", 100.0), ("NSE:X-EQ", 0), ("NSE:X-EQ", -5)])
def test_unusable_inputs_are_not_guessed_at(patched, symbol, price):
    assert patched(broker(ok(50.0)))(symbol, price) is None


def test_a_failed_lookup_is_not_cached(patched):
    """
    Caching a failure would make one bad minute poison the symbol for the whole
    session. Only confirmed readings are kept.
    """
    b = broker({}, status=500)
    patched(b)("NSE:X-EQ", 100.0)
    assert "NSE:X-EQ" not in b._leverage_cache


# cost control


def test_a_confirmed_reading_is_cached(patched):
    b = broker(ok(106.34))
    get = patched(b)
    get("NSE:KIRIINDUS-EQ", 530.90)
    get("NSE:KIRIINDUS-EQ", 530.90)
    assert len(b._calls) == 1, "leverage does not change intraday; ask once"


def test_a_low_reading_blacklists_the_symbol_for_the_session(patched):
    b = broker(ok(138.93))
    get = patched(b)
    assert get("NSE:SHIPROCKET-EQ", 138.89) == pytest.approx(1.0, abs=0.01)
    assert "NSE:SHIPROCKET-EQ" in b._low_leverage_blacklist
    assert get("NSE:SHIPROCKET-EQ", 138.89) == 1.0
    assert len(b._calls) == 1


def test_a_good_reading_is_not_blacklisted(patched):
    b = broker(ok(106.34))
    patched(b)("NSE:KIRIINDUS-EQ", 530.90)
    assert b._low_leverage_blacklist == set()


# the floor


def test_the_floor_sits_in_the_empty_gap():
    """
    Live distribution on 2026-08-31 was strictly bimodal: 1.0x or 4.0x+, with
    nothing between. The floor must land in that gap — above 1.0 so no-MIS
    names are dropped, at or below 4.0 so the 4x cohort survives. A threshold
    inside a populated range is what produced a zero-trade session before.
    """
    from shortcircuit import config

    floor = config.SCANNER_MIN_LEVERAGE
    assert 1.0 < floor <= 4.0
