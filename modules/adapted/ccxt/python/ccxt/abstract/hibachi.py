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
    public_get_market_exchange_info = publicGetMarketExchangeInfo = Entry[_Dict](
        "market/exchange-info", "public", "GET", {"cost": 1}
    )
    public_get_market_inventory = publicGetMarketInventory = Entry[_Dict](
        "market/inventory", "public", "GET", {"cost": 1}
    )
    public_get_market_data_prices = publicGetMarketDataPrices = Entry[_Dict](
        "market/data/prices", "public", "GET", {"cost": 1}
    )
    public_get_market_data_stats = publicGetMarketDataStats = Entry[_Dict](
        "market/data/stats", "public", "GET", {"cost": 1}
    )
    public_get_market_data_trades = publicGetMarketDataTrades = Entry[_Dict](
        "market/data/trades", "public", "GET", {"cost": 1}
    )
    public_get_market_data_klines = publicGetMarketDataKlines = Entry[_Dict](
        "market/data/klines", "public", "GET", {"cost": 1}
    )
    public_get_market_data_open_interest = publicGetMarketDataOpenInterest = Entry[_Dict](
        "market/data/open-interest", "public", "GET", {"cost": 1}
    )
    public_get_market_data_orderbook = publicGetMarketDataOrderbook = Entry[_Dict](
        "market/data/orderbook", "public", "GET", {"cost": 1}
    )
    public_get_market_data_funding_rates = publicGetMarketDataFundingRates = Entry[_Dict](
        "market/data/funding-rates", "public", "GET", {"cost": 1}
    )
    public_get_exchange_utc_timestamp = publicGetExchangeUtcTimestamp = Entry[_Dict](
        "exchange/utc-timestamp", "public", "GET", {"cost": 1}
    )
    private_get_capital_balance = privateGetCapitalBalance = Entry[_Dict](
        "capital/balance", "private", "GET", {"cost": 1}
    )
    private_get_capital_history = privateGetCapitalHistory = Entry[_Dict](
        "capital/history", "private", "GET", {"cost": 1}
    )
    private_get_capital_deposit_info = privateGetCapitalDepositInfo = Entry[_Dict](
        "capital/deposit-info", "private", "GET", {"cost": 1}
    )
    private_get_trade_account_info = privateGetTradeAccountInfo = Entry[_Dict](
        "trade/account/info", "private", "GET", {"cost": 1}
    )
    private_get_trade_account_trades = privateGetTradeAccountTrades = Entry[_Dict](
        "trade/account/trades", "private", "GET", {"cost": 1}
    )
    private_get_trade_account_trading_history = privateGetTradeAccountTradingHistory = Entry[_Dict](
        "trade/account/trading_history", "private", "GET", {"cost": 1}
    )
    private_get_trade_account_settlements_history = privateGetTradeAccountSettlementsHistory = Entry[_Dict](
        "trade/account/settlements_history", "private", "GET", {"cost": 1}
    )
    private_get_trade_orders = privateGetTradeOrders = Entry[_List]("trade/orders", "private", "GET", {"cost": 1})
    private_get_trade_order = privateGetTradeOrder = Entry[_Dict]("trade/order", "private", "GET", {"cost": 1})
    private_get_trade_orders_history = privateGetTradeOrdersHistory = Entry[_Dict](
        "trade/orders/history", "private", "GET", {"cost": 1}
    )
    private_put_trade_order = privatePutTradeOrder = Entry[_Dict]("trade/order", "private", "PUT", {"cost": 1})
    private_delete_trade_order = privateDeleteTradeOrder = Entry[_Dict]("trade/order", "private", "DELETE", {"cost": 1})
    private_delete_trade_orders = privateDeleteTradeOrders = Entry[_Dict](
        "trade/orders", "private", "DELETE", {"cost": 1}
    )
    private_post_trade_order = privatePostTradeOrder = Entry[_Dict]("trade/order", "private", "POST", {"cost": 1})
    private_post_trade_orders = privatePostTradeOrders = Entry[_Dict]("trade/orders", "private", "POST", {"cost": 1})
    private_post_capital_withdraw = privatePostCapitalWithdraw = Entry[_Dict](
        "capital/withdraw", "private", "POST", {"cost": 1}
    )
    private_post_capital_transfer = privatePostCapitalTransfer = Entry[_Dict](
        "capital/transfer", "private", "POST", {"cost": 1}
    )
    private_post_trade_account_leverage = privatePostTradeAccountLeverage = Entry[_Dict](
        "trade/account/leverage", "private", "POST", {"cost": 1}
    )
