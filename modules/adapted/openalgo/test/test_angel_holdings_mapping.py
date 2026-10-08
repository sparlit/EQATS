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


"""Angel One holdings mapping.

Covers the two shapes that used to break: a holding whose average price and LTP
were silently dropped, and an empty demat account, which Angel reports as
``holdings: null`` rather than an empty list.
"""

import pytest
from broker.angel.mapping.order_data import (
    calculate_portfolio_statistics,
    map_portfolio_data,
    transform_holdings_data,
)


@pytest.fixture(autouse=True)
def _no_symbol_lookup(monkeypatch):
    """map_portfolio_data resolves broker symbols against the token DB."""
    monkeypatch.setattr(
        "broker.angel.mapping.order_data.get_oa_symbol",
        lambda symbol, exchange: symbol.replace("-EQ", ""),
    )


def _response(holdings, totalholding):
    return {
        "status": True,
        "message": "SUCCESS",
        "errorcode": "",
        "data": {"holdings": holdings, "totalholding": totalholding},
    }


def test_transform_holdings_carries_average_price_and_ltp():
    data = map_portfolio_data(
        _response(
            [
                {
                    "tradingsymbol": "TATASTEEL-EQ",
                    "exchange": "NSE",
                    "quantity": "2",
                    "product": "DELIVERY",
                    "averageprice": 111.87,
                    "ltp": 130.15,
                    "profitandloss": 37,
                    "pnlpercentage": 16.34,
                }
            ],
            {
                "totalholdingvalue": 5294,
                "totalinvvalue": 5116,
                "totalprofitandloss": 178.14,
                "totalpnlpercentage": 3.48,
            },
        )
    )

    assert transform_holdings_data(data) == [
        {
            "symbol": "TATASTEEL",
            "exchange": "NSE",
            "quantity": 2,
            "product": "CNC",
            "average_price": 111.87,
            "ltp": 130.15,
            "pnl": 37.0,
            "pnlpercent": 16.34,
        }
    ]


def test_statistics_coerce_string_numerics():
    stats = calculate_portfolio_statistics(
        {
            "holdings": [],
            "totalholding": {
                "totalholdingvalue": "5294",
                "totalinvvalue": "5116",
                "totalprofitandloss": "178.14",
                "totalpnlpercentage": "3.48",
            },
        }
    )

    assert stats == {
        "totalholdingvalue": 5294.0,
        "totalinvvalue": 5116.0,
        "totalprofitandloss": 178.14,
        "totalpnlpercentage": 3.48,
    }


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(_response(None, None), id="null-holdings"),
        pytest.param(_response([], None), id="empty-holdings"),
        pytest.param({"status": True, "data": None}, id="null-data"),
        pytest.param({"status": True, "data": {}}, id="data-without-holdings"),
    ],
)
def test_empty_portfolio_does_not_raise(payload):
    """Every one of these used to surface as a 500 from the holdings API."""
    data = map_portfolio_data(payload)

    assert transform_holdings_data(data) == []
    assert calculate_portfolio_statistics(data) == {
        "totalholdingvalue": 0,
        "totalinvvalue": 0,
        "totalprofitandloss": 0,
        "totalpnlpercentage": 0,
    }
