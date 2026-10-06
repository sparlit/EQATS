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


"""Issue #270: KeyboardInterrupt and SystemExit raised in a callback stop
the dispatch and reach the caller; any other exception is logged and the
dispatch goes on.
"""
import pytest
from ibx import EClient, EWrapper

LOST = "Connectivity between client and server has been lost."
RESTORED = "Connectivity between client and server has been restored - data maintained."


class RaisingWrapper(EWrapper):
    def __init__(self, exc):
        super().__init__()
        self.exc = exc
        self.codes = []

    def error(self, req_id, error_code, error_string, advanced_order_reject_json=""):
        self.codes.append(error_code)
        if error_code in (1100, 504):
            raise self.exc


def connected(exc):
    w = RaisingWrapper(exc)
    c = EClient(w)
    c._test_connect("TEST123")
    return w, c


def test_ordinary_exception_is_dropped_and_dispatch_goes_on():
    w, c = connected(ValueError("bad handler"))
    c._test_push_connection_notice(1100, LOST)
    c._test_push_connection_notice(1102, RESTORED)
    c._test_dispatch_once()
    assert w.codes == [1100, 1102]


@pytest.mark.parametrize("exc", [KeyboardInterrupt, SystemExit])
def test_base_exception_stops_dispatch(exc):
    w, c = connected(exc)
    c._test_push_connection_notice(1100, LOST)
    c._test_push_connection_notice(1102, RESTORED)
    with pytest.raises(exc):
        c._test_dispatch_once()
    assert w.codes == [1100]


def test_system_exit_from_callback_ends_run():
    w, c = connected(SystemExit(3))
    c._test_push_connection_notice(1100, LOST)
    with pytest.raises(SystemExit) as info:
        c.run()
    assert info.value.code == 3


@pytest.mark.parametrize("exc", [KeyboardInterrupt, SystemExit])
def test_base_exception_from_not_connected_error_is_raised(exc):
    w = RaisingWrapper(exc)
    c = EClient(w)
    with pytest.raises(exc):
        c.cancel_order(1)
    assert w.codes == [504]


def test_ordinary_exception_from_not_connected_error_is_dropped():
    w = RaisingWrapper(ValueError("bad handler"))
    c = EClient(w)
    c.cancel_order(1)
    assert w.codes == [504]
