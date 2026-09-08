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
    public_get_api_server_time = publicGetApiServerTime = Entry[_Dict]("api/server_time", "public", "GET", {"cost": 5})
    public_get_api_pairs = publicGetApiPairs = Entry[_List]("api/pairs", "public", "GET", {"cost": 5})
    public_get_api_price_increments = publicGetApiPriceIncrements = Entry[_Dict](
        "api/price_increments", "public", "GET", {"cost": 5}
    )
    public_get_api_summaries = publicGetApiSummaries = Entry[_Dict]("api/summaries", "public", "GET", {"cost": 5})
    public_get_api_ticker_pair = publicGetApiTickerPair = Entry[_Dict](
        "api/ticker/{pair}", "public", "GET", {"cost": 5}
    )
    public_get_api_ticker_all = publicGetApiTickerAll = Entry[_Dict]("api/ticker_all", "public", "GET", {"cost": 5})
    public_get_api_trades_pair = publicGetApiTradesPair = Entry[_List](
        "api/trades/{pair}", "public", "GET", {"cost": 5}
    )
    public_get_api_depth_pair = publicGetApiDepthPair = Entry[_Dict]("api/depth/{pair}", "public", "GET", {"cost": 5})
    public_get_tradingview_history_v2 = publicGetTradingviewHistoryV2 = Entry[_List](
        "tradingview/history_v2", "public", "GET", {"cost": 5}
    )
    private_post_getinfo = privatePostGetInfo = Entry[_Dict]("getInfo", "private", "POST", {"cost": 4})
    private_post_transhistory = privatePostTransHistory = Entry[_Dict]("transHistory", "private", "POST", {"cost": 4})
    private_post_trade = privatePostTrade = Entry[_Dict]("trade", "private", "POST", {"cost": 1})
    private_post_tradehistory = privatePostTradeHistory = Entry[_Dict]("tradeHistory", "private", "POST", {"cost": 4})
    private_post_openorders = privatePostOpenOrders = Entry[_Dict]("openOrders", "private", "POST", {"cost": 4})
    private_post_orderhistory = privatePostOrderHistory = Entry[_Dict]("orderHistory", "private", "POST", {"cost": 4})
    private_post_getorder = privatePostGetOrder = Entry[_Dict]("getOrder", "private", "POST", {"cost": 4})
    private_post_cancelorder = privatePostCancelOrder = Entry[_Dict]("cancelOrder", "private", "POST", {"cost": 4})
    private_post_withdrawfee = privatePostWithdrawFee = Entry[_Dict]("withdrawFee", "private", "POST", {"cost": 4})
    private_post_withdrawcoin = privatePostWithdrawCoin = Entry[_Dict]("withdrawCoin", "private", "POST", {"cost": 4})
    private_post_listdownline = privatePostListDownline = Entry[_Dict]("listDownline", "private", "POST", {"cost": 4})
    private_post_checkdownline = privatePostCheckDownline = Entry[_Dict](
        "checkDownline", "private", "POST", {"cost": 4}
    )
    private_post_createvoucher = privatePostCreateVoucher = Entry[_Dict](
        "createVoucher", "private", "POST", {"cost": 4}
    )
