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
    public_get_coins = publicGetCoins = Entry[_List]("coins", "public", "GET", {"cost": 1})
    public_get_coin_orderbook = publicGetCoinOrderbook = Entry[_Dict]("{coin}/orderbook/", "public", "GET", {"cost": 1})
    public_get_coin_ticker = publicGetCoinTicker = Entry[_Dict]("{coin}/ticker/", "public", "GET", {"cost": 1})
    public_get_coin_trades = publicGetCoinTrades = Entry[_List]("{coin}/trades/", "public", "GET", {"cost": 1})
    public_get_coin_trades_from = publicGetCoinTradesFrom = Entry[_List](
        "{coin}/trades/{from}/", "public", "GET", {"cost": 1}
    )
    public_get_coin_trades_from_to = publicGetCoinTradesFromTo = Entry[_List](
        "{coin}/trades/{from}/{to}", "public", "GET", {"cost": 1}
    )
    public_get_coin_day_summary_year_month_day = publicGetCoinDaySummaryYearMonthDay = Entry[_Dict](
        "{coin}/day-summary/{year}/{month}/{day}/", "public", "GET", {"cost": 1}
    )
    private_post_cancel_order = privatePostCancelOrder = Entry[_Dict]("cancel_order", "private", "POST", {"cost": 1})
    private_post_get_account_info = privatePostGetAccountInfo = Entry[_Dict](
        "get_account_info", "private", "POST", {"cost": 1}
    )
    private_post_get_order = privatePostGetOrder = Entry[_Dict]("get_order", "private", "POST", {"cost": 1})
    private_post_get_withdrawal = privatePostGetWithdrawal = Entry[_Dict](
        "get_withdrawal", "private", "POST", {"cost": 1}
    )
    private_post_list_system_messages = privatePostListSystemMessages = Entry[_Dict](
        "list_system_messages", "private", "POST", {"cost": 1}
    )
    private_post_list_orders = privatePostListOrders = Entry[_Dict]("list_orders", "private", "POST", {"cost": 1})
    private_post_list_orderbook = privatePostListOrderbook = Entry[_Dict](
        "list_orderbook", "private", "POST", {"cost": 1}
    )
    private_post_place_buy_order = privatePostPlaceBuyOrder = Entry[_Dict](
        "place_buy_order", "private", "POST", {"cost": 1}
    )
    private_post_place_sell_order = privatePostPlaceSellOrder = Entry[_Dict](
        "place_sell_order", "private", "POST", {"cost": 1}
    )
    private_post_place_market_buy_order = privatePostPlaceMarketBuyOrder = Entry[_Dict](
        "place_market_buy_order", "private", "POST", {"cost": 1}
    )
    private_post_place_market_sell_order = privatePostPlaceMarketSellOrder = Entry[_Dict](
        "place_market_sell_order", "private", "POST", {"cost": 1}
    )
    private_post_withdraw_coin = privatePostWithdrawCoin = Entry[_Dict]("withdraw_coin", "private", "POST", {"cost": 1})
    v4public_get_coin_candle = v4PublicGetCoinCandle = Entry[_Dict]("{coin}/candle/", "v4Public", "GET", {"cost": 1})
    v4publicnet_get_candles = v4PublicNetGetCandles = Entry[_Dict]("candles", "v4PublicNet", "GET", {"cost": 1})
