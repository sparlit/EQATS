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
    opinion_public_get_market = opinionPublicGetMarket = Entry[_Dict | _List](
        "market", ["opinion", "public"], "GET", {"cost": 1}
    )
    opinion_public_get_market_marketid = opinionPublicGetMarketMarketId = Entry[_Dict | _List](
        "market/{marketId}", ["opinion", "public"], "GET", {"cost": 1}
    )
    opinion_public_get_market_categorical_marketid = opinionPublicGetMarketCategoricalMarketId = Entry[_Dict | _List](
        "market/categorical/{marketId}", ["opinion", "public"], "GET", {"cost": 1}
    )
    opinion_public_get_market_slug_slug = opinionPublicGetMarketSlugSlug = Entry[_Dict | _List](
        "market/slug/{slug}", ["opinion", "public"], "GET", {"cost": 1}
    )
    opinion_public_get_label = opinionPublicGetLabel = Entry[_Dict | _List](
        "label", ["opinion", "public"], "GET", {"cost": 1}
    )
    opinion_public_get_token_latest_price = opinionPublicGetTokenLatestPrice = Entry[_Dict | _List](
        "token/latest-price", ["opinion", "public"], "GET", {"cost": 1}
    )
    opinion_public_get_token_orderbook = opinionPublicGetTokenOrderbook = Entry[_Dict | _List](
        "token/orderbook", ["opinion", "public"], "GET", {"cost": 1}
    )
    opinion_public_get_token_price_history = opinionPublicGetTokenPriceHistory = Entry[_Dict | _List](
        "token/price-history", ["opinion", "public"], "GET", {"cost": 1}
    )
    opinion_public_get_quotetoken = opinionPublicGetQuoteToken = Entry[_Dict | _List](
        "quoteToken", ["opinion", "public"], "GET", {"cost": 1}
    )
    opinion_private_get_order = opinionPrivateGetOrder = Entry[_Dict | _List](
        "order", ["opinion", "private"], "GET", {"cost": 1}
    )
    opinion_private_get_order_orderid = opinionPrivateGetOrderOrderId = Entry[_Dict | _List](
        "order/{orderId}", ["opinion", "private"], "GET", {"cost": 1}
    )
    opinion_private_get_positions_user_walletaddress = opinionPrivateGetPositionsUserWalletAddress = Entry[
        _Dict | _List
    ]("positions/user/{walletAddress}", ["opinion", "private"], "GET", {"cost": 1})
    opinion_private_get_trade_user_walletaddress = opinionPrivateGetTradeUserWalletAddress = Entry[_Dict | _List](
        "trade/user/{walletAddress}", ["opinion", "private"], "GET", {"cost": 1}
    )
    opinion_private_get_auth_api_key = opinionPrivateGetAuthApiKey = Entry[_Dict | _List](
        "auth/api-key", ["opinion", "private"], "GET", {"cost": 1}
    )
    opinion_private_get_user_auth = opinionPrivateGetUserAuth = Entry[_Dict | _List](
        "user/auth", ["opinion", "private"], "GET", {"cost": 1}
    )
    opinion_private_get_user_balance = opinionPrivateGetUserBalance = Entry[_Dict | _List](
        "user/balance", ["opinion", "private"], "GET", {"cost": 1}
    )
    opinion_private_post_auth_api_key = opinionPrivatePostAuthApiKey = Entry[_Dict | _List](
        "auth/api-key", ["opinion", "private"], "POST", {"cost": 1}
    )
    opinion_private_post_order = opinionPrivatePostOrder = Entry[_Dict | _List](
        "order", ["opinion", "private"], "POST", {"cost": 1}
    )
    opinion_private_post_order_cancel = opinionPrivatePostOrderCancel = Entry[_Dict | _List](
        "order/cancel", ["opinion", "private"], "POST", {"cost": 1}
    )
    opinion_private_delete_auth_api_key = opinionPrivateDeleteAuthApiKey = Entry[_Dict | _List](
        "auth/api-key", ["opinion", "private"], "DELETE", {"cost": 1}
    )
