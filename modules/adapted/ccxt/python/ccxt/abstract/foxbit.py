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
    v3_public_get_currencies = v3PublicGetCurrencies = Entry[_Dict]("currencies", ["v3", "public"], "GET", {"cost": 5})
    v3_public_get_markets = v3PublicGetMarkets = Entry[_Dict]("markets", ["v3", "public"], "GET", {"cost": 5})
    v3_public_get_markets_ticker_24hr = v3PublicGetMarketsTicker24hr = Entry[_Dict](
        "markets/ticker/24hr", ["v3", "public"], "GET", {"cost": 60}
    )
    v3_public_get_markets_market_orderbook = v3PublicGetMarketsMarketOrderbook = Entry[_Dict](
        "markets/{market}/orderbook", ["v3", "public"], "GET", {"cost": 6}
    )
    v3_public_get_markets_market_candlesticks = v3PublicGetMarketsMarketCandlesticks = Entry[_List](
        "markets/{market}/candlesticks", ["v3", "public"], "GET", {"cost": 12}
    )
    v3_public_get_markets_market_trades_history = v3PublicGetMarketsMarketTradesHistory = Entry[_Dict](
        "markets/{market}/trades/history", ["v3", "public"], "GET", {"cost": 12}
    )
    v3_public_get_markets_market_ticker_24hr = v3PublicGetMarketsMarketTicker24hr = Entry[_Dict](
        "markets/{market}/ticker/24hr", ["v3", "public"], "GET", {"cost": 15}
    )
    v3_private_get_accounts = v3PrivateGetAccounts = Entry[_Dict]("accounts", ["v3", "private"], "GET", {"cost": 2})
    v3_private_get_accounts_symbol_transactions = v3PrivateGetAccountsSymbolTransactions = Entry[_Dict](
        "accounts/{symbol}/transactions", ["v3", "private"], "GET", {"cost": 60}
    )
    v3_private_get_orders = v3PrivateGetOrders = Entry[_Dict]("orders", ["v3", "private"], "GET", {"cost": 2})
    v3_private_get_orders_by_order_id_id = v3PrivateGetOrdersByOrderIdId = Entry[_Dict](
        "orders/by-order-id/{id}", ["v3", "private"], "GET", {"cost": 2}
    )
    v3_private_get_trades = v3PrivateGetTrades = Entry[_Dict]("trades", ["v3", "private"], "GET", {"cost": 6})
    v3_private_get_deposits_address = v3PrivateGetDepositsAddress = Entry[_Dict](
        "deposits/address", ["v3", "private"], "GET", {"cost": 10}
    )
    v3_private_get_deposits = v3PrivateGetDeposits = Entry[_Dict]("deposits", ["v3", "private"], "GET", {"cost": 10})
    v3_private_get_withdrawals = v3PrivateGetWithdrawals = Entry[_Dict](
        "withdrawals", ["v3", "private"], "GET", {"cost": 10}
    )
    v3_private_get_me_fees_trading = v3PrivateGetMeFeesTrading = Entry[_Dict](
        "me/fees/trading", ["v3", "private"], "GET", {"cost": 60}
    )
    v3_private_post_orders = v3PrivatePostOrders = Entry[_Dict]("orders", ["v3", "private"], "POST", {"cost": 2})
    v3_private_post_orders_batch = v3PrivatePostOrdersBatch = Entry[_Dict](
        "orders/batch", ["v3", "private"], "POST", {"cost": 7.5}
    )
    v3_private_post_orders_cancel_replace = v3PrivatePostOrdersCancelReplace = Entry[_Dict](
        "orders/cancel-replace", ["v3", "private"], "POST", {"cost": 3}
    )
    v3_private_post_withdrawals = v3PrivatePostWithdrawals = Entry[_Dict](
        "withdrawals", ["v3", "private"], "POST", {"cost": 10}
    )
    v3_private_put_orders_cancel = v3PrivatePutOrdersCancel = Entry[_Dict](
        "orders/cancel", ["v3", "private"], "PUT", {"cost": 2}
    )
    status_public_get_status = statusPublicGetStatus = Entry[_Dict]("status", ["status", "public"], "GET", {"cost": 30})
