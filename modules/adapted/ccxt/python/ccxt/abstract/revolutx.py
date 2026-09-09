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

_Dict = dict[str, object]
_List = list[object]


class ImplicitAPI:
    public_get_2_0_public_order_book_symbol = publicGet20PublicOrderBookSymbol = Entry[_Dict | _List](
        "2.0/public/order-book/{symbol}", "public", "GET", {"cost": 1}
    )
    public_get_1_0_public_tickers = publicGet10PublicTickers = Entry[_Dict | _List](
        "1.0/public/tickers", "public", "GET", {"cost": 1}
    )
    public_get_1_0_public_candles_symbol = publicGet10PublicCandlesSymbol = Entry[_Dict | _List](
        "1.0/public/candles/{symbol}", "public", "GET", {"cost": 1}
    )
    public_get_1_0_public_trades_all = publicGet10PublicTradesAll = Entry[_Dict | _List](
        "1.0/public/trades/all", "public", "GET", {"cost": 1}
    )
    public_get_1_0_public_configuration_currencies = publicGet10PublicConfigurationCurrencies = Entry[_Dict | _List](
        "1.0/public/configuration/currencies", "public", "GET", {"cost": 1}
    )
    public_get_1_0_public_configuration_pairs = publicGet10PublicConfigurationPairs = Entry[_Dict | _List](
        "1.0/public/configuration/pairs", "public", "GET", {"cost": 1}
    )
    private_get_1_0_balances = privateGet10Balances = Entry[_Dict | _List](
        "1.0/balances", "private", "GET", {"cost": 1}
    )
    private_get_1_0_orders_active = privateGet10OrdersActive = Entry[_Dict | _List](
        "1.0/orders/active", "private", "GET", {"cost": 1}
    )
    private_get_1_0_orders_historical = privateGet10OrdersHistorical = Entry[_Dict | _List](
        "1.0/orders/historical", "private", "GET", {"cost": 1}
    )
    private_get_1_0_orders_venue_order_id = privateGet10OrdersVenueOrderId = Entry[_Dict | _List](
        "1.0/orders/{venue_order_id}", "private", "GET", {"cost": 1}
    )
    private_get_1_0_orders_fills_venue_order_id = privateGet10OrdersFillsVenueOrderId = Entry[_Dict | _List](
        "1.0/orders/fills/{venue_order_id}", "private", "GET", {"cost": 1}
    )
    private_get_1_0_trades_private_symbol = privateGet10TradesPrivateSymbol = Entry[_Dict | _List](
        "1.0/trades/private/{symbol}", "private", "GET", {"cost": 1}
    )
    private_post_1_0_orders = privatePost10Orders = Entry[_Dict | _List]("1.0/orders", "private", "POST", {"cost": 1})
    private_put_1_0_orders_venue_order_id = privatePut10OrdersVenueOrderId = Entry[_Dict | _List](
        "1.0/orders/{venue_order_id}", "private", "PUT", {"cost": 1}
    )
    private_delete_1_0_orders = privateDelete10Orders = Entry[_Dict | _List](
        "1.0/orders", "private", "DELETE", {"cost": 1}
    )
    private_delete_1_0_orders_venue_order_id = privateDelete10OrdersVenueOrderId = Entry[_Dict | _List](
        "1.0/orders/{venue_order_id}", "private", "DELETE", {"cost": 1}
    )
