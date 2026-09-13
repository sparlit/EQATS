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


from ccxt.base.types import Entry

_List = list[object]
_Dict = dict[str, object]


class ImplicitAPI:
    public_get_currencies = publicGetCurrencies = Entry[_List]("currencies", "public", "GET", {"cost": 1})
    public_get_candlesticks_instrument_code = publicGetCandlesticksInstrumentCode = Entry[_Dict](
        "candlesticks/{instrument_code}", "public", "GET", {"cost": 1}
    )
    public_get_fees = publicGetFees = Entry[_List]("fees", "public", "GET", {"cost": 1})
    public_get_instruments = publicGetInstruments = Entry[_List]("instruments", "public", "GET", {"cost": 1})
    public_get_order_book_instrument_code = publicGetOrderBookInstrumentCode = Entry[_Dict](
        "order-book/{instrument_code}", "public", "GET", {"cost": 1}
    )
    public_get_market_ticker = publicGetMarketTicker = Entry[_List]("market-ticker", "public", "GET", {"cost": 1})
    public_get_market_ticker_instrument_code = publicGetMarketTickerInstrumentCode = Entry[_Dict](
        "market-ticker/{instrument_code}", "public", "GET", {"cost": 1}
    )
    public_get_time = publicGetTime = Entry[_Dict]("time", "public", "GET", {"cost": 1})
    private_get_account_balances = privateGetAccountBalances = Entry[_Dict](
        "account/balances", "private", "GET", {"cost": 1}
    )
    private_get_account_fees = privateGetAccountFees = Entry[_Dict]("account/fees", "private", "GET", {"cost": 1})
    private_get_account_orders = privateGetAccountOrders = Entry[_Dict]("account/orders", "private", "GET", {"cost": 1})
    private_get_account_orders_order_id = privateGetAccountOrdersOrderId = Entry[_Dict](
        "account/orders/{order_id}", "private", "GET", {"cost": 1}
    )
    private_get_account_orders_client_client_id = privateGetAccountOrdersClientClientId = Entry[_Dict](
        "account/orders/client/{client_id}", "private", "GET", {"cost": 1}
    )
    private_get_account_orders_order_id_trades = privateGetAccountOrdersOrderIdTrades = Entry[_Dict](
        "account/orders/{order_id}/trades", "private", "GET", {"cost": 1}
    )
    private_get_account_trades = privateGetAccountTrades = Entry[_Dict]("account/trades", "private", "GET", {"cost": 1})
    private_get_account_trade_trade_id = privateGetAccountTradeTradeId = Entry[_Dict](
        "account/trade/{trade_id}", "private", "GET", {"cost": 1}
    )
    private_post_account_orders = privatePostAccountOrders = Entry[_Dict](
        "account/orders", "private", "POST", {"cost": 1}
    )
    private_delete_account_orders = privateDeleteAccountOrders = Entry[_List](
        "account/orders", "private", "DELETE", {"cost": 1}
    )
    private_delete_account_orders_order_id = privateDeleteAccountOrdersOrderId = Entry[_Dict](
        "account/orders/{order_id}", "private", "DELETE", {"cost": 1}
    )
    private_delete_account_orders_client_client_id = privateDeleteAccountOrdersClientClientId = Entry[_Dict](
        "account/orders/client/{client_id}", "private", "DELETE", {"cost": 1}
    )
