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


class ImplicitAPI:
    public_get_markets = publicGetMarkets = Entry[_Dict]("markets", "public", "GET", {"cost": 1})
    public_get_market = publicGetMarket = Entry[_Dict]("market", "public", "GET", {"cost": 1})
    public_get_tickers = publicGetTickers = Entry[_Dict]("tickers", "public", "GET", {"cost": 1})
    public_get_ticker = publicGetTicker = Entry[_Dict]("ticker", "public", "GET", {"cost": 1})
    public_get_book = publicGetBook = Entry[_Dict]("book", "public", "GET", {"cost": 1})
    public_get_history = publicGetHistory = Entry[_Dict]("history", "public", "GET", {"cost": 1})
    public_get_depth_result = publicGetDepthResult = Entry[_Dict]("depth/result", "public", "GET", {"cost": 1})
    public_get_market_kline = publicGetMarketKline = Entry[_Dict]("market/kline", "public", "GET", {"cost": 1})
    private_post_account_balances = privatePostAccountBalances = Entry[_Dict](
        "account/balances", "private", "POST", {"cost": 1}
    )
    private_post_account_balance = privatePostAccountBalance = Entry[_Dict](
        "account/balance", "private", "POST", {"cost": 1}
    )
    private_post_order_new = privatePostOrderNew = Entry[_Dict]("order/new", "private", "POST", {"cost": 1})
    private_post_order_cancel = privatePostOrderCancel = Entry[_Dict]("order/cancel", "private", "POST", {"cost": 1})
    private_post_orders = privatePostOrders = Entry[_Dict]("orders", "private", "POST", {"cost": 1})
    private_post_account_market_order_history = privatePostAccountMarketOrderHistory = Entry[_Dict](
        "account/market_order_history", "private", "POST", {"cost": 1}
    )
    private_post_account_market_deal_history = privatePostAccountMarketDealHistory = Entry[_Dict](
        "account/market_deal_history", "private", "POST", {"cost": 1}
    )
    private_post_account_order = privatePostAccountOrder = Entry[_Dict]("account/order", "private", "POST", {"cost": 1})
    private_post_account_order_history = privatePostAccountOrderHistory = Entry[_Dict](
        "account/order_history", "private", "POST", {"cost": 1}
    )
    private_post_account_executed_history = privatePostAccountExecutedHistory = Entry[_Dict](
        "account/executed_history", "private", "POST", {"cost": 1}
    )
