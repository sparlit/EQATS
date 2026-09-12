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
    sapi_private_get_category_list = sapiPrivateGetCategoryList = Entry[_Dict](
        "category/list", ["sapi", "private"], "GET", {"cost": 200}
    )
    sapi_private_get_market_list = sapiPrivateGetMarketList = Entry[_Dict](
        "market/list", ["sapi", "private"], "GET", {"cost": 200}
    )
    sapi_private_get_market_search = sapiPrivateGetMarketSearch = Entry[_List](
        "market/search", ["sapi", "private"], "GET", {"cost": 200}
    )
    sapi_private_get_market_detail = sapiPrivateGetMarketDetail = Entry[_Dict](
        "market/detail", ["sapi", "private"], "GET", {"cost": 200}
    )
    sapi_private_get_order_book = sapiPrivateGetOrderBook = Entry[_Dict](
        "order-book", ["sapi", "private"], "GET", {"cost": 200}
    )
    sapi_private_get_order_book_last_trade_price = sapiPrivateGetOrderBookLastTradePrice = Entry[_Dict](
        "order-book/last-trade-price", ["sapi", "private"], "GET", {"cost": 200}
    )
    sapi_private_get_wallet_list = sapiPrivateGetWalletList = Entry[_Dict](
        "wallet/list", ["sapi", "private"], "GET", {"cost": 200}
    )
    sapi_private_get_balance_payment_options = sapiPrivateGetBalancePaymentOptions = Entry[_Dict](
        "balance/payment-options", ["sapi", "private"], "GET", {"cost": 200}
    )
    sapi_private_get_quota_limit_status = sapiPrivateGetQuotaLimitStatus = Entry[_Dict](
        "quota/limit/status", ["sapi", "private"], "GET", {"cost": 200}
    )
    sapi_private_get_pnl_portfolio = sapiPrivateGetPnlPortfolio = Entry[_Dict](
        "pnl/portfolio", ["sapi", "private"], "GET", {"cost": 200}
    )
    sapi_private_get_pnl_query = sapiPrivateGetPnlQuery = Entry[_Dict](
        "pnl/query", ["sapi", "private"], "GET", {"cost": 200}
    )
    sapi_private_get_position_list = sapiPrivateGetPositionList = Entry[_Dict](
        "position/list", ["sapi", "private"], "GET", {"cost": 200}
    )
    sapi_private_get_position_filter = sapiPrivateGetPositionFilter = Entry[_Dict](
        "position/filter", ["sapi", "private"], "GET", {"cost": 200}
    )
    sapi_private_get_position_token = sapiPrivateGetPositionToken = Entry[_Dict](
        "position/token", ["sapi", "private"], "GET", {"cost": 200}
    )
    sapi_private_get_position_settled_history = sapiPrivateGetPositionSettledHistory = Entry[_Dict](
        "position/settled-history", ["sapi", "private"], "GET", {"cost": 200}
    )
    sapi_private_get_order_list = sapiPrivateGetOrderList = Entry[_Dict](
        "order/list", ["sapi", "private"], "GET", {"cost": 200}
    )
    sapi_private_get_order_history = sapiPrivateGetOrderHistory = Entry[_Dict](
        "order/history", ["sapi", "private"], "GET", {"cost": 200}
    )
    sapi_private_post_trade_get_quote = sapiPrivatePostTradeGetQuote = Entry[_Dict](
        "trade/get-quote", ["sapi", "private"], "POST", {"cost": 200}
    )
    sapi_private_post_trade_place_order_bundle = sapiPrivatePostTradePlaceOrderBundle = Entry[_Dict](
        "trade/place-order-bundle", ["sapi", "private"], "POST", {"cost": 200}
    )
    sapi_private_post_trade_batch_cancel = sapiPrivatePostTradeBatchCancel = Entry[_Dict](
        "trade/batch-cancel", ["sapi", "private"], "POST", {"cost": 200}
    )
