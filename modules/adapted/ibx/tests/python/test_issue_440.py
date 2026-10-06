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


"""ibx#440: option chain parameters as the reference: local refusals with
321, then one securityDefinitionOptionParameter per row (expirations and
strikes as sets) and one end."""

from ibx import EClient, EWrapper


class Recorder(EWrapper):
    def __init__(self):
        super().__init__()
        self.events = []

    def error(self, req_id, error_code, error_string, advanced_order_reject_json=""):
        self.events.append(("error", req_id, error_code, error_string))

    def security_definition_option_parameter(
        self, req_id, exchange, underlying_con_id, trading_class, multiplier, expirations, strikes
    ):
        self.events.append(
            (
                "param",
                req_id,
                exchange,
                underlying_con_id,
                trading_class,
                multiplier,
                expirations,
                strikes,
            )
        )

    def security_definition_option_parameter_end(self, req_id):
        self.events.append(("end", req_id))


def connected():
    w = Recorder()
    c = EClient(w)
    c._test_connect("TEST123")
    return c, w


def cause(text):
    return "Error validating request.-'cp' : cause - " + text


def test_local_refusals():
    c, w = connected()
    c.req_sec_def_opt_params(1, "AAPL", "", "OPT", 265598)
    c.req_sec_def_opt_params(2, "ES", "", "FUT", 495512563)
    c.req_sec_def_opt_params(3, "AAPL", "", "STK", 0)
    c._test_dispatch_once()
    assert w.events == [
        ("error", 1, 321, cause("Invalid security type - OPT")),
        ("error", 2, 321, cause("Missing exchange for security type FUT")),
        ("error", 3, 321, cause("Invalid contract id")),
    ]


def test_rows_then_end():
    c, w = connected()
    c._test_push_option_chain(
        7,
        [
            ("SMART", 265598, "AAPL", "100", ["20261016", "20261120"], [5.0, 297.5]),
            ("IBUSOPT", 265598, "AAPL", "100", ["20261016"], [5.0]),
        ],
    )
    c._test_dispatch_once()
    assert w.events == [
        ("param", 7, "SMART", 265598, "AAPL", "100", {"20261016", "20261120"}, {5.0, 297.5}),
        ("param", 7, "IBUSOPT", 265598, "AAPL", "100", {"20261016"}, {5.0}),
        ("end", 7),
    ]
    assert isinstance(w.events[0][6], set) and isinstance(w.events[0][7], set)


def test_empty_answer_gives_the_end_only():
    c, w = connected()
    c._test_push_option_chain(8, [])
    c._test_dispatch_once()
    assert w.events == [("end", 8)]
