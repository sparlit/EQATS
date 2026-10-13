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
    sxbet_public_get_metadata_obv3 = sxbetPublicGetMetadataObv3 = Entry[_Dict](
        "metadata/obv3", ["sxbet", "public"], "GET", {"cost": 1}
    )
    sxbet_public_get_orderbook_v3_snapshot = sxbetPublicGetOrderbookV3Snapshot = Entry[_Dict](
        "orderbook-v3/snapshot", ["sxbet", "public"], "GET", {"cost": 1}
    )
    sxbet_public_get_trades_v3_public = sxbetPublicGetTradesV3Public = Entry[_Dict](
        "trades-v3/public", ["sxbet", "public"], "GET", {"cost": 1}
    )
    sxbet_public_get_markets_active = sxbetPublicGetMarketsActive = Entry[_Dict](
        "markets/active", ["sxbet", "public"], "GET", {"cost": 1}
    )
    sxbet_public_get_markets_find = sxbetPublicGetMarketsFind = Entry[_Dict | _List](
        "markets/find", ["sxbet", "public"], "GET", {"cost": 1}
    )
    sxbet_public_get_markets_popular = sxbetPublicGetMarketsPopular = Entry[_Dict | _List](
        "markets/popular", ["sxbet", "public"], "GET", {"cost": 1}
    )
    sxbet_public_get_trades_consolidated = sxbetPublicGetTradesConsolidated = Entry[_Dict | _List](
        "trades/consolidated", ["sxbet", "public"], "GET", {"cost": 1}
    )
    sxbet_public_get_trades_orders = sxbetPublicGetTradesOrders = Entry[_Dict | _List](
        "trades/orders", ["sxbet", "public"], "GET", {"cost": 1}
    )
    sxbet_public_get_trades_portfolio_refunds = sxbetPublicGetTradesPortfolioRefunds = Entry[
        _Dict | _List
    ]("trades/portfolio/refunds", ["sxbet", "public"], "GET", {"cost": 1})
    sxbet_public_get_fixture_active = sxbetPublicGetFixtureActive = Entry[_Dict | _List](
        "fixture/active", ["sxbet", "public"], "GET", {"cost": 1}
    )
    sxbet_public_get_fixture_status = sxbetPublicGetFixtureStatus = Entry[_Dict | _List](
        "fixture/status", ["sxbet", "public"], "GET", {"cost": 1}
    )
    sxbet_public_get_sports = sxbetPublicGetSports = Entry[_Dict | _List](
        "sports", ["sxbet", "public"], "GET", {"cost": 1}
    )
    sxbet_public_get_leagues = sxbetPublicGetLeagues = Entry[_Dict | _List](
        "leagues", ["sxbet", "public"], "GET", {"cost": 1}
    )
    sxbet_public_get_leagues_active = sxbetPublicGetLeaguesActive = Entry[_Dict | _List](
        "leagues/active", ["sxbet", "public"], "GET", {"cost": 1}
    )
    sxbet_public_get_teams = sxbetPublicGetTeams = Entry[_Dict | _List](
        "teams", ["sxbet", "public"], "GET", {"cost": 1}
    )
    sxbet_public_get_live_scores = sxbetPublicGetLiveScores = Entry[_Dict | _List](
        "live-scores", ["sxbet", "public"], "GET", {"cost": 1}
    )
    sxbet_private_get_user_realtime_token_v3_api_key = sxbetPrivateGetUserRealtimeTokenV3ApiKey = (
        Entry[_Dict]("user/realtime-token-v3/api-key", ["sxbet", "private"], "GET", {"cost": 1})
    )
    sxbet_private_get_user_proxy = sxbetPrivateGetUserProxy = Entry[_Dict](
        "user/proxy", ["sxbet", "private"], "GET", {"cost": 1}
    )
    sxbet_private_get_user_balance_v3 = sxbetPrivateGetUserBalanceV3 = Entry[_Dict](
        "user/balance-v3", ["sxbet", "private"], "GET", {"cost": 1}
    )
    sxbet_private_get_user_transfer_to_proxy_pending = sxbetPrivateGetUserTransferToProxyPending = (
        Entry[_Dict | _List](
            "user/transfer-to-proxy/pending", ["sxbet", "private"], "GET", {"cost": 1}
        )
    )
    sxbet_private_get_user_transfer_to_proxy_status = sxbetPrivateGetUserTransferToProxyStatus = (
        Entry[_Dict | _List](
            "user/transfer-to-proxy/status", ["sxbet", "private"], "GET", {"cost": 1}
        )
    )
    sxbet_private_get_orders_v3 = sxbetPrivateGetOrdersV3 = Entry[_Dict](
        "orders-v3", ["sxbet", "private"], "GET", {"cost": 1}
    )
    sxbet_private_get_orders_v3_orderid = sxbetPrivateGetOrdersV3OrderId = Entry[_Dict](
        "orders-v3/{orderId}", ["sxbet", "private"], "GET", {"cost": 1}
    )
    sxbet_private_get_orders_v3_odds_best = sxbetPrivateGetOrdersV3OddsBest = Entry[_Dict](
        "orders-v3/odds/best", ["sxbet", "private"], "GET", {"cost": 1}
    )
    sxbet_private_get_trades_v3 = sxbetPrivateGetTradesV3 = Entry[_Dict](
        "trades-v3", ["sxbet", "private"], "GET", {"cost": 1}
    )
    sxbet_private_get_fills_v3 = sxbetPrivateGetFillsV3 = Entry[_Dict](
        "fills-v3", ["sxbet", "private"], "GET", {"cost": 1}
    )
    sxbet_private_get_positions_v3 = sxbetPrivateGetPositionsV3 = Entry[_Dict](
        "positions-v3", ["sxbet", "private"], "GET", {"cost": 1}
    )
    sxbet_private_delete_orders_v3 = sxbetPrivateDeleteOrdersV3 = Entry[_Dict](
        "orders-v3", ["sxbet", "private"], "DELETE", {"cost": 1}
    )
    sxbet_private_delete_orders_v3_event = sxbetPrivateDeleteOrdersV3Event = Entry[_Dict](
        "orders-v3/event", ["sxbet", "private"], "DELETE", {"cost": 1}
    )
    sxbet_private_delete_orders_v3_all = sxbetPrivateDeleteOrdersV3All = Entry[_Dict](
        "orders-v3/all", ["sxbet", "private"], "DELETE", {"cost": 1}
    )
    sxbet_private_post_orders_v3 = sxbetPrivatePostOrdersV3 = Entry[_Dict](
        "orders-v3", ["sxbet", "private"], "POST", {"cost": 1}
    )
    sxbet_private_post_user_deploy_proxy = sxbetPrivatePostUserDeployProxy = Entry[_Dict | _List](
        "user/deploy-proxy", ["sxbet", "private"], "POST", {"cost": 1}
    )
    sxbet_private_post_user_transfer_to_proxy = sxbetPrivatePostUserTransferToProxy = Entry[_Dict](
        "user/transfer-to-proxy", ["sxbet", "private"], "POST", {"cost": 1}
    )
    sxbet_private_post_heartbeat_v3 = sxbetPrivatePostHeartbeatV3 = Entry[_Dict | _List](
        "heartbeat/v3", ["sxbet", "private"], "POST", {"cost": 1}
    )
