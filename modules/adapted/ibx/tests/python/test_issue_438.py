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


"""ibx#438: a continuous futures row has secType CONTFUT, and a bond row is
a bond contract details message, as the reference sends them."""

from ibx import EClient, EWrapper


class Recorder(EWrapper):
    def __init__(self):
        super().__init__()
        self.events = []

    def contract_details(self, req_id, contract_details):
        self.events.append(("contract_details", req_id, contract_details.contract.sec_type))

    def bond_contract_details(self, req_id, contract_details):
        self.events.append(("bond_contract_details", req_id, contract_details.contract.sec_type))

    def contract_details_end(self, req_id):
        self.events.append(("contract_details_end", req_id))


def connected():
    w = Recorder()
    c = EClient(w)
    c._test_connect("TEST123")
    return c, w


def test_continuous_future_row_is_contfut():
    c, w = connected()
    c._test_push_contract_row(9480, 515416632, "FUT", True)
    c._test_dispatch_once()
    assert w.events == [("contract_details", 9480, "CONTFUT"), ("contract_details_end", 9480)]


def test_bond_row_is_bond_contract_details():
    c, w = connected()
    c._test_push_contract_row(9488, 29105555, "BOND")
    c._test_dispatch_once()
    assert w.events == [("bond_contract_details", 9488, "BOND"), ("contract_details_end", 9488)]
