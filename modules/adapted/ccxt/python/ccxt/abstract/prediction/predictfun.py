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
    predictfun_get_v1_auth_message = predictfunGetV1AuthMessage = Entry[_Dict](
        "v1/auth/message", "predictfun", "GET", {"cost": 1}
    )
    predictfun_get_v1_categories = predictfunGetV1Categories = Entry[_Dict](
        "v1/categories", "predictfun", "GET", {"cost": 1}
    )
    predictfun_get_v1_categories_slug = predictfunGetV1CategoriesSlug = Entry[_Dict](
        "v1/categories/{slug}", "predictfun", "GET", {"cost": 1}
    )
    predictfun_get_v1_tags = predictfunGetV1Tags = Entry[_Dict](
        "v1/tags", "predictfun", "GET", {"cost": 1}
    )
    predictfun_get_v1_markets = predictfunGetV1Markets = Entry[_Dict](
        "v1/markets", "predictfun", "GET", {"cost": 1}
    )
    predictfun_get_v1_markets_id = predictfunGetV1MarketsId = Entry[_Dict](
        "v1/markets/{id}", "predictfun", "GET", {"cost": 1}
    )
    predictfun_get_v1_markets_id_stats = predictfunGetV1MarketsIdStats = Entry[_Dict](
        "v1/markets/{id}/stats", "predictfun", "GET", {"cost": 1}
    )
    predictfun_get_v1_markets_id_last_sale = predictfunGetV1MarketsIdLastSale = Entry[_Dict](
        "v1/markets/{id}/last-sale", "predictfun", "GET", {"cost": 1}
    )
    predictfun_get_v1_markets_id_orderbook = predictfunGetV1MarketsIdOrderbook = Entry[_Dict](
        "v1/markets/{id}/orderbook", "predictfun", "GET", {"cost": 1}
    )
    predictfun_get_v1_markets_id_timeseries = predictfunGetV1MarketsIdTimeseries = Entry[_Dict](
        "v1/markets/{id}/timeseries", "predictfun", "GET", {"cost": 1}
    )
    predictfun_get_v1_markets_id_timeseries_latest = predictfunGetV1MarketsIdTimeseriesLatest = (
        Entry[_Dict]("v1/markets/{id}/timeseries/latest", "predictfun", "GET", {"cost": 1})
    )
    predictfun_get_v1_orders_hash = predictfunGetV1OrdersHash = Entry[_Dict](
        "v1/orders/{hash}", "predictfun", "GET", {"cost": 1}
    )
    predictfun_get_v1_orders = predictfunGetV1Orders = Entry[_Dict](
        "v1/orders", "predictfun", "GET", {"cost": 1}
    )
    predictfun_get_v1_orders_matches = predictfunGetV1OrdersMatches = Entry[_Dict](
        "v1/orders/matches", "predictfun", "GET", {"cost": 1}
    )
    predictfun_get_v1_account = predictfunGetV1Account = Entry[_Dict](
        "v1/account", "predictfun", "GET", {"cost": 1}
    )
    predictfun_get_v1_account_activity = predictfunGetV1AccountActivity = Entry[_Dict](
        "v1/account/activity", "predictfun", "GET", {"cost": 1}
    )
    predictfun_get_v1_positions = predictfunGetV1Positions = Entry[_Dict](
        "v1/positions", "predictfun", "GET", {"cost": 1}
    )
    predictfun_get_v1_positions_address = predictfunGetV1PositionsAddress = Entry[_Dict](
        "v1/positions/{address}", "predictfun", "GET", {"cost": 1}
    )
    predictfun_get_v1_search = predictfunGetV1Search = Entry[_Dict](
        "v1/search", "predictfun", "GET", {"cost": 1}
    )
    predictfun_post_v1_auth = predictfunPostV1Auth = Entry[_Dict](
        "v1/auth", "predictfun", "POST", {"cost": 1}
    )
    predictfun_post_v1_orders_remove = predictfunPostV1OrdersRemove = Entry[_Dict](
        "v1/orders/remove", "predictfun", "POST", {"cost": 1}
    )
    predictfun_post_v1_orders = predictfunPostV1Orders = Entry[_Dict](
        "v1/orders", "predictfun", "POST", {"cost": 1}
    )
    predictfun_post_v1_orders_remove_by_hash = predictfunPostV1OrdersRemoveByHash = Entry[_Dict](
        "v1/orders/remove-by-hash", "predictfun", "POST", {"cost": 1}
    )
    predictfun_post_v1_account_referral = predictfunPostV1AccountReferral = Entry[_Dict](
        "v1/account/referral", "predictfun", "POST", {"cost": 1}
    )
    predictfun_post_v1_oauth_finalize = predictfunPostV1OauthFinalize = Entry[_Dict](
        "v1/oauth/finalize", "predictfun", "POST", {"cost": 1}
    )
    predictfun_post_v1_oauth_orders = predictfunPostV1OauthOrders = Entry[_Dict](
        "v1/oauth/orders", "predictfun", "POST", {"cost": 1}
    )
    predictfun_post_v1_oauth_orders_create = predictfunPostV1OauthOrdersCreate = Entry[_Dict](
        "v1/oauth/orders/create", "predictfun", "POST", {"cost": 1}
    )
    predictfun_post_v1_oauth_orders_cancel = predictfunPostV1OauthOrdersCancel = Entry[_Dict](
        "v1/oauth/orders/cancel", "predictfun", "POST", {"cost": 1}
    )
    predictfun_post_v1_oauth_positions = predictfunPostV1OauthPositions = Entry[_Dict](
        "v1/oauth/positions", "predictfun", "POST", {"cost": 1}
    )
