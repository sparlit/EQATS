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
    market_get_price_kline = marketGetPriceKline = Entry[_Dict]("price/kline", "market", "GET", {"cost": 1})
    market_get_price_mark_kline = marketGetPriceMarkKline = Entry[_Dict](
        "price/mark-kline", "market", "GET", {"cost": 1}
    )
    private_get_futures = privateGetFutures = Entry[_Dict]("futures", "private", "GET", {"cost": 1})
    private_get_futures_asset_id = privateGetFuturesAssetId = Entry[_Dict](
        "futures/{asset_id}", "private", "GET", {"cost": 1}
    )
    private_get_wallet_funds = privateGetWalletFunds = Entry[_Dict]("wallet/funds", "private", "GET", {"cost": 5})
    private_get_futures_funds = privateGetFuturesFunds = Entry[_Dict]("futures/funds", "private", "GET", {"cost": 5})
    private_get_futures_orders = privateGetFuturesOrders = Entry[_Dict]("futures/orders", "private", "GET", {"cost": 1})
    private_get_futures_orders_history = privateGetFuturesOrdersHistory = Entry[_Dict](
        "futures/orders/history", "private", "GET", {"cost": 1}
    )
    private_get_futures_orders_order_id = privateGetFuturesOrdersOrderId = Entry[_Dict](
        "futures/orders/{order_id}", "private", "GET", {"cost": 1}
    )
    private_get_futures_positions = privateGetFuturesPositions = Entry[_Dict](
        "futures/positions", "private", "GET", {"cost": 1}
    )
    private_get_futures_positions_history = privateGetFuturesPositionsHistory = Entry[_Dict](
        "futures/positions/history", "private", "GET", {"cost": 1}
    )
    private_get_futures_fee_history = privateGetFuturesFeeHistory = Entry[_Dict](
        "futures/fee/history", "private", "GET", {"cost": 1}
    )
    private_get_futures_asset_id_leverage = privateGetFuturesAssetIdLeverage = Entry[_Dict](
        "futures/{asset_id}/leverage", "private", "GET", {"cost": 2}
    )
    private_get_futures_positions_position_id_liq_price = privateGetFuturesPositionsPositionIdLiqPrice = Entry[_Dict](
        "futures/positions/{position_id}/liq-price", "private", "GET", {"cost": 1}
    )
    private_post_wallet_futures_transfer = privatePostWalletFuturesTransfer = Entry[_Dict](
        "wallet/futures/transfer", "private", "POST", {"cost": 5}
    )
    private_post_futures_transfers_inr = privatePostFuturesTransfersInr = Entry[_Dict](
        "futures/transfers/inr", "private", "POST", {"cost": 5}
    )
    private_post_futures_asset_id_order = privatePostFuturesAssetIdOrder = Entry[_Dict](
        "futures/{asset_id}/order", "private", "POST", {"cost": 2}
    )
    private_post_futures_positions_position_id_close = privatePostFuturesPositionsPositionIdClose = Entry[_Dict](
        "futures/positions/{position_id}/close", "private", "POST", {"cost": 2}
    )
    private_post_futures_positions_position_id_close_partial = privatePostFuturesPositionsPositionIdClosePartial = (
        Entry[_Dict]("futures/positions/{position_id}/close/partial", "private", "POST", {"cost": 2})
    )
    private_post_futures_positions_position_id_reverse = privatePostFuturesPositionsPositionIdReverse = Entry[_Dict](
        "futures/positions/{position_id}/reverse", "private", "POST", {"cost": 2}
    )
    private_post_futures_positions_position_id_add_margin = privatePostFuturesPositionsPositionIdAddMargin = Entry[
        _Dict
    ]("futures/positions/{position_id}/add-margin", "private", "POST", {"cost": 2})
    private_post_futures_positions_position_id_riskorder = privatePostFuturesPositionsPositionIdRiskorder = Entry[
        _Dict
    ]("futures/positions/{position_id}/riskorder", "private", "POST", {"cost": 2})
    private_post_futures_asset_id_leverage = privatePostFuturesAssetIdLeverage = Entry[_Dict](
        "futures/{asset_id}/leverage", "private", "POST", {"cost": 2}
    )
    private_patch_futures_orders_order_id = privatePatchFuturesOrdersOrderId = Entry[_Dict](
        "futures/orders/{order_id}", "private", "PATCH", {"cost": 1}
    )
    private_patch_futures_positions_position_id_riskorder = privatePatchFuturesPositionsPositionIdRiskorder = Entry[
        _Dict
    ]("futures/positions/{position_id}/riskorder", "private", "PATCH", {"cost": 2})
    private_delete_futures_orders_order_id = privateDeleteFuturesOrdersOrderId = Entry[_Dict](
        "futures/orders/{order_id}", "private", "DELETE", {"cost": 2}
    )
