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
    gateway_public_get_symbols = gatewayPublicGetSymbols = Entry[_List](
        "symbols", ["gateway", "public"], "GET", {"cost": 2}
    )
    gateway_public_get_query = gatewayPublicGetQuery = Entry[_Dict]("query", ["gateway", "public"], "GET", {"cost": 1})
    gateway_public_get_edge_query = gatewayPublicGetEdgeQuery = Entry[_Dict](
        "edge/query", ["gateway", "public"], "GET", {"cost": 1}
    )
    gateway_public_post_query = gatewayPublicPostQuery = Entry[_Dict](
        "query", ["gateway", "public"], "POST", {"cost": 1}
    )
    gateway_private_post_execute = gatewayPrivatePostExecute = Entry[_Dict](
        "execute", ["gateway", "private"], "POST", {"cost": 1}
    )
    gatewayv2_public_get_assets = gatewayV2PublicGetAssets = Entry[_List](
        "assets", ["gatewayV2", "public"], "GET", {"cost": 2}
    )
    gatewayv2_public_get_pairs = gatewayV2PublicGetPairs = Entry[_List](
        "pairs", ["gatewayV2", "public"], "GET", {"cost": 1}
    )
    gatewayv2_public_get_orderbook = gatewayV2PublicGetOrderbook = Entry[_Dict](
        "orderbook", ["gatewayV2", "public"], "GET", {"cost": 1}
    )
    archive_post = archivePost = Entry[_Dict]("", "archive", "POST", {"cost": 1})
    archivev2_public_get_tickers = archiveV2PublicGetTickers = Entry[_Dict](
        "tickers", ["archiveV2", "public"], "GET", {"cost": 1}
    )
    archivev2_public_get_contracts = archiveV2PublicGetContracts = Entry[_Dict](
        "contracts", ["archiveV2", "public"], "GET", {"cost": 1}
    )
    archivev2_public_get_trades = archiveV2PublicGetTrades = Entry[_List](
        "trades", ["archiveV2", "public"], "GET", {"cost": 1}
    )
    trigger_private_post_execute = triggerPrivatePostExecute = Entry[_Dict](
        "execute", ["trigger", "private"], "POST", {"cost": 1}
    )
    trigger_private_post_query = triggerPrivatePostQuery = Entry[_Dict](
        "query", ["trigger", "private"], "POST", {"cost": 1}
    )
