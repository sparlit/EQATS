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
    public_get_depth = publicGetDepth = Entry[_Dict]("depth", "public", "GET", {"cost": 1})
    public_get_orders = publicGetOrders = Entry[_List]("orders", "public", "GET", {"cost": 1})
    public_get_ticker = publicGetTicker = Entry[_Dict]("ticker", "public", "GET", {"cost": 1})
    public_get_tickers = publicGetTickers = Entry[_Dict]("tickers", "public", "GET", {"cost": 1})
    private_post_balance = privatePostBalance = Entry[_Dict]("balance", "private", "POST", {"cost": 1})
    private_post_trade_add = privatePostTradeAdd = Entry[_Dict]("trade_add", "private", "POST", {"cost": 1})
    private_post_trade_cancel = privatePostTradeCancel = Entry[_Dict]("trade_cancel", "private", "POST", {"cost": 1})
    private_post_trade_list = privatePostTradeList = Entry[_List]("trade_list", "private", "POST", {"cost": 1})
    private_post_trade_view = privatePostTradeView = Entry[_Dict]("trade_view", "private", "POST", {"cost": 1})
    private_post_wallet = privatePostWallet = Entry[_Dict]("wallet", "private", "POST", {"cost": 1})
    webapi_get_ajax_coin_coininfo = webApiGetAjaxCoinCoinInfo = Entry[_Dict](
        "ajax/coin/coinInfo", "webApi", "GET", {"cost": 1}
    )
