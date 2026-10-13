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


from broker.upstox.mapping.order_data import transform_holdings_data


def test_transform_holdings_uses_standard_ltp_contract():
    out = transform_holdings_data(
        [
            {
                "tradingsymbol": "INFY",
                "exchange": "NSE",
                "quantity": 2,
                "product": "D",
                "average_price": 100,
                "last_price": 120,
                "pnl": 40,
            }
        ]
    )

    assert out == [
        {
            "symbol": "INFY",
            "exchange": "NSE",
            "quantity": 2,
            "product": "D",
            "average_price": 100.0,
            "ltp": 120.0,
            "pnl": 40.0,
            "pnlpercent": 20.0,
        }
    ]


def test_transform_holdings_handles_zero_average_price():
    out = transform_holdings_data(
        [
            {
                "tradingsymbol": "BONUS",
                "exchange": "NSE",
                "quantity": 1,
                "product": "D",
                "average_price": None,
                "last_price": 50,
                "pnl": 5,
            }
        ]
    )

    assert out[0]["average_price"] == 0.0
    assert out[0]["ltp"] == 50.0
    assert out[0]["pnlpercent"] == 0.0
