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
    public_get_ping = publicGetPing = Entry[_Dict]("ping", "public", "GET", {"cost": 1})
    public_get_asset_pairs = publicGetAssetPairs = Entry[_Dict]("asset_pairs", "public", "GET", {"cost": 1})
    public_get_asset_pairs_asset_pair_name_depth = publicGetAssetPairsAssetPairNameDepth = Entry[_Dict](
        "asset_pairs/{asset_pair_name}/depth", "public", "GET", {"cost": 1}
    )
    public_get_asset_pairs_asset_pair_name_trades = publicGetAssetPairsAssetPairNameTrades = Entry[_Dict](
        "asset_pairs/{asset_pair_name}/trades", "public", "GET", {"cost": 1}
    )
    public_get_asset_pairs_asset_pair_name_ticker = publicGetAssetPairsAssetPairNameTicker = Entry[_Dict](
        "asset_pairs/{asset_pair_name}/ticker", "public", "GET", {"cost": 1}
    )
    public_get_asset_pairs_asset_pair_name_candles = publicGetAssetPairsAssetPairNameCandles = Entry[_Dict](
        "asset_pairs/{asset_pair_name}/candles", "public", "GET", {"cost": 1}
    )
    public_get_asset_pairs_tickers = publicGetAssetPairsTickers = Entry[_Dict](
        "asset_pairs/tickers", "public", "GET", {"cost": 1}
    )
    private_get_accounts = privateGetAccounts = Entry[_Dict]("accounts", "private", "GET", {"cost": 1})
    private_get_fund_accounts = privateGetFundAccounts = Entry[_Dict]("fund/accounts", "private", "GET", {"cost": 1})
    private_get_assets_asset_symbol_address = privateGetAssetsAssetSymbolAddress = Entry[_Dict](
        "assets/{asset_symbol}/address", "private", "GET", {"cost": 1}
    )
    private_get_orders = privateGetOrders = Entry[_Dict]("orders", "private", "GET", {"cost": 1})
    private_get_orders_id = privateGetOrdersId = Entry[_Dict]("orders/{id}", "private", "GET", {"cost": 1})
    private_get_orders_multi = privateGetOrdersMulti = Entry[_Dict]("orders/multi", "private", "GET", {"cost": 1})
    private_get_trades = privateGetTrades = Entry[_Dict]("trades", "private", "GET", {"cost": 1})
    private_get_withdrawals = privateGetWithdrawals = Entry[_Dict]("withdrawals", "private", "GET", {"cost": 1})
    private_get_deposits = privateGetDeposits = Entry[_Dict]("deposits", "private", "GET", {"cost": 1})
    private_post_orders = privatePostOrders = Entry[_Dict]("orders", "private", "POST", {"cost": 1})
    private_post_orders_id_cancel = privatePostOrdersIdCancel = Entry[_Dict](
        "orders/{id}/cancel", "private", "POST", {"cost": 1}
    )
    private_post_orders_cancel = privatePostOrdersCancel = Entry[_Dict]("orders/cancel", "private", "POST", {"cost": 1})
    private_post_withdrawals = privatePostWithdrawals = Entry[_Dict]("withdrawals", "private", "POST", {"cost": 1})
    private_post_transfer = privatePostTransfer = Entry[_Dict]("transfer", "private", "POST", {"cost": 1})
    contractpublic_get_symbols = contractPublicGetSymbols = Entry[_List](
        "symbols", "contractPublic", "GET", {"cost": 1}
    )
    contractpublic_get_instruments = contractPublicGetInstruments = Entry[_List](
        "instruments", "contractPublic", "GET", {"cost": 1}
    )
    contractpublic_get_depth_symbol_snapshot = contractPublicGetDepthSymbolSnapshot = Entry[_Dict](
        "depth@{symbol}/snapshot", "contractPublic", "GET", {"cost": 1}
    )
    contractpublic_get_instruments_difference = contractPublicGetInstrumentsDifference = Entry[_Dict](
        "instruments/difference", "contractPublic", "GET", {"cost": 1}
    )
    contractpublic_get_instruments_prices = contractPublicGetInstrumentsPrices = Entry[_Dict](
        "instruments/prices", "contractPublic", "GET", {"cost": 1}
    )
    contractprivate_get_accounts = contractPrivateGetAccounts = Entry[_List](
        "accounts", "contractPrivate", "GET", {"cost": 1}
    )
    contractprivate_get_orders_id = contractPrivateGetOrdersId = Entry[_Dict](
        "orders/{id}", "contractPrivate", "GET", {"cost": 1}
    )
    contractprivate_get_orders = contractPrivateGetOrders = Entry[_List](
        "orders", "contractPrivate", "GET", {"cost": 1}
    )
    contractprivate_get_orders_opening = contractPrivateGetOrdersOpening = Entry[_List](
        "orders/opening", "contractPrivate", "GET", {"cost": 1}
    )
    contractprivate_get_orders_count = contractPrivateGetOrdersCount = Entry[_Dict](
        "orders/count", "contractPrivate", "GET", {"cost": 1}
    )
    contractprivate_get_orders_opening_count = contractPrivateGetOrdersOpeningCount = Entry[_Dict](
        "orders/opening/count", "contractPrivate", "GET", {"cost": 1}
    )
    contractprivate_get_trades = contractPrivateGetTrades = Entry[_List](
        "trades", "contractPrivate", "GET", {"cost": 1}
    )
    contractprivate_get_trades_count = contractPrivateGetTradesCount = Entry[_Dict](
        "trades/count", "contractPrivate", "GET", {"cost": 1}
    )
    contractprivate_post_orders = contractPrivatePostOrders = Entry[_Dict](
        "orders", "contractPrivate", "POST", {"cost": 1}
    )
    contractprivate_post_orders_batch = contractPrivatePostOrdersBatch = Entry[_Dict](
        "orders/batch", "contractPrivate", "POST", {"cost": 1}
    )
    contractprivate_put_positions_symbol_margin = contractPrivatePutPositionsSymbolMargin = Entry[_Dict](
        "positions/{symbol}/margin", "contractPrivate", "PUT", {"cost": 1}
    )
    contractprivate_put_positions_symbol_risk_limit = contractPrivatePutPositionsSymbolRiskLimit = Entry[_Dict](
        "positions/{symbol}/risk-limit", "contractPrivate", "PUT", {"cost": 1}
    )
    contractprivate_delete_orders_id = contractPrivateDeleteOrdersId = Entry[_Dict](
        "orders/{id}", "contractPrivate", "DELETE", {"cost": 1}
    )
    contractprivate_delete_orders_batch = contractPrivateDeleteOrdersBatch = Entry[_Dict](
        "orders/batch", "contractPrivate", "DELETE", {"cost": 1}
    )
    webexchange_get_v3_assets = webExchangeGetV3Assets = Entry[_Dict]("v3/assets", "webExchange", "GET", {"cost": 1})
