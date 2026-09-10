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
    public_get_orderbook = publicGetOrderbook = Entry[_Dict]("orderbook", "public", "GET", {"cost": 1})
    public_get_ticker = publicGetTicker = Entry[_Dict]("ticker", "public", "GET", {"cost": 0.1})
    public_get_trades = publicGetTrades = Entry[_Dict]("trades", "public", "GET", {"cost": 1})
    public_get_ohlc = publicGetOhlc = Entry[_Dict]("ohlc", "public", "GET", {"cost": 1})
    public_get_server_exchangeinfo = publicGetServerExchangeinfo = Entry[_Dict](
        "server/exchangeinfo", "public", "GET", {"cost": 1}
    )
    private_get_users_balances = privateGetUsersBalances = Entry[_Dict]("users/balances", "private", "GET", {"cost": 1})
    private_get_openorders = privateGetOpenOrders = Entry[_Dict]("openOrders", "private", "GET", {"cost": 1})
    private_get_allorders = privateGetAllOrders = Entry[_Dict]("allOrders", "private", "GET", {"cost": 1})
    private_get_users_transactions_trade = privateGetUsersTransactionsTrade = Entry[_Dict](
        "users/transactions/trade", "private", "GET", {"cost": 1}
    )
    private_post_users_transactions_crypto = privatePostUsersTransactionsCrypto = Entry[_Dict](
        "users/transactions/crypto", "private", "POST", {"cost": 1}
    )
    private_post_users_transactions_fiat = privatePostUsersTransactionsFiat = Entry[_Dict](
        "users/transactions/fiat", "private", "POST", {"cost": 1}
    )
    private_post_order = privatePostOrder = Entry[_Dict]("order", "private", "POST", {"cost": 1})
    private_post_cancelorder = privatePostCancelOrder = Entry[_Dict]("cancelOrder", "private", "POST", {"cost": 1})
    private_delete_order = privateDeleteOrder = Entry[_Dict]("order", "private", "DELETE", {"cost": 1})
    graph_get_ohlcs = graphGetOhlcs = Entry[_List]("ohlcs", "graph", "GET", {"cost": 1})
    graph_get_klines_history = graphGetKlinesHistory = Entry[_Dict]("klines/history", "graph", "GET", {"cost": 1})
