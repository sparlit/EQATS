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


"""Plan M3.1: the broker contract's error taxonomy and capability records."""

from decimal import Decimal

import pytest
from src.brokers.base import (
    AuthError,
    BrokerCapabilities,
    BrokerError,
    BrokerUnavailableError,
    InvalidRequestError,
    MarginQuote,
    OrderRejectedError,
    RateLimitedError,
    RejectReason,
    TransportError,
)
from src.domain.types import OrderType, Product, Validity


@pytest.mark.parametrize(
    ("error", "outcome", "retryable"),
    [
        (AuthError("expired"), "NOT_PLACED", False),
        (RateLimitedError("slow down", retry_after=2.0), "NOT_PLACED", True),
        (
            OrderRejectedError("no cash", reason=RejectReason.INSUFFICIENT_FUNDS),
            "NOT_PLACED",
            False,
        ),
        (InvalidRequestError("qty 0"), "NOT_PLACED", False),
        (TransportError("timeout"), "UNKNOWN", True),
        (BrokerUnavailableError("503"), "UNKNOWN", True),
    ],
)
def test_error_outcomes_drive_the_oms(error, outcome, retryable):
    assert isinstance(error, BrokerError)
    assert error.outcome == outcome and error.retryable is retryable


def test_error_details_are_kept():
    err = OrderRejectedError(
        "band", reason=RejectReason.PRICE_BAND, broker_code="RMS:7", raw={"x": 1}
    )
    assert err.reason is RejectReason.PRICE_BAND and err.broker_code == "RMS:7"
    assert dict(err.raw) == {"x": 1}
    assert RateLimitedError("x", retry_after=1.5).retry_after == 1.5


def test_capabilities_supports():
    caps = BrokerCapabilities(
        order_types=frozenset({OrderType.MARKET, OrderType.SL_M}),
        products=frozenset({Product.CNC}),
    )
    assert caps.supports(OrderType.MARKET, Product.CNC, Validity.DAY)
    assert not caps.supports(OrderType.LIMIT, Product.CNC, Validity.DAY)
    assert not caps.supports(OrderType.MARKET, Product.MIS, Validity.DAY)
    assert not caps.supports(OrderType.MARKET, Product.CNC, Validity.IOC)


def test_margin_quote():
    assert MarginQuote(required=Decimal(100), available=Decimal(100)).sufficient
    assert not MarginQuote(required=Decimal("100.01"), available=Decimal(100)).sufficient
