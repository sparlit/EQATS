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
    public_get_market_book = publicGetMarketBook = Entry[_Dict]("{market}/book", "public", "GET", {"cost": 1})
    public_get_report_market_book = publicGetReportMarketBook = Entry[_Dict](
        "report/{market}/book", "public", "GET", {"cost": 1}
    )
    public_get_market_trades = publicGetMarketTrades = Entry[_List]("{market}/trades", "public", "GET", {"cost": 5})
    public_get_report_market_trades = publicGetReportMarketTrades = Entry[_List](
        "report/{market}/trades", "public", "GET", {"cost": 5}
    )
    public_get_ticker_price = publicGetTickerPrice = Entry[_List]("ticker/price", "public", "GET", {"cost": 1})
    public_get_ticker_book = publicGetTickerBook = Entry[_List]("ticker/book", "public", "GET", {"cost": 1})
    public_get_market_candles = publicGetMarketCandles = Entry[_List]("{market}/candles", "public", "GET", {"cost": 1})
    public_get_ticker_24h = publicGetTicker24h = Entry[_Dict | _List](
        "ticker/24h", "public", "GET", {"cost": 1, "noMarket": 25}
    )
    public_get_time = publicGetTime = Entry[_Dict]("time", "public", "GET", {"cost": 1})
    public_get_markets = publicGetMarkets = Entry[_List]("markets", "public", "GET", {"cost": 1})
    public_get_assets = publicGetAssets = Entry[_List]("assets", "public", "GET", {"cost": 1})
    private_get_order = privateGetOrder = Entry[_Dict]("order", "private", "GET", {"cost": 1})
    private_get_ordersopen = privateGetOrdersOpen = Entry[_List](
        "ordersOpen", "private", "GET", {"cost": 5, "noMarket": 100}
    )
    private_get_trades = privateGetTrades = Entry[_List]("trades", "private", "GET", {"cost": 5})
    private_get_orders = privateGetOrders = Entry[_List]("orders", "private", "GET", {"cost": 5})
    private_get_deposit = privateGetDeposit = Entry[_Dict]("deposit", "private", "GET", {"cost": 1})
    private_get_deposithistory = privateGetDepositHistory = Entry[_List](
        "depositHistory", "private", "GET", {"cost": 5}
    )
    private_get_withdrawalhistory = privateGetWithdrawalHistory = Entry[_List](
        "withdrawalHistory", "private", "GET", {"cost": 5}
    )
    private_get_account = privateGetAccount = Entry[_List]("account", "private", "GET", {"cost": 1})
    private_get_balance = privateGetBalance = Entry[_List]("balance", "private", "GET", {"cost": 5})
    private_get_stakingbalance = privateGetStakingBalance = Entry[_List](
        "stakingBalance", "private", "GET", {"cost": 1}
    )
    private_get_account_fees = privateGetAccountFees = Entry[_Dict]("account/fees", "private", "GET", {"cost": 1})
    private_get_account_history = privateGetAccountHistory = Entry[_Dict](
        "account/history", "private", "GET", {"cost": 1}
    )
    private_get_subaccounts = privateGetSubaccounts = Entry[_Dict]("subaccounts", "private", "GET", {"cost": 5})
    private_get_subaccounts_transfers = privateGetSubaccountsTransfers = Entry[_Dict](
        "subaccounts/transfers", "private", "GET", {"cost": 5}
    )
    private_get_subaccounts_transfers_transferid = privateGetSubaccountsTransfersTransferId = Entry[_Dict](
        "subaccounts/transfers/{transferId}", "private", "GET", {"cost": 5}
    )
    private_get_institutional_subaccounts_balance = privateGetInstitutionalSubaccountsBalance = Entry[_Dict](
        "institutional/subaccounts/balance", "private", "GET", {"cost": 5}
    )
    private_get_institutional_subaccounts_history = privateGetInstitutionalSubaccountsHistory = Entry[_Dict](
        "institutional/subaccounts/history", "private", "GET", {"cost": 5}
    )
    private_get_institutional_subaccounts_orders_open = privateGetInstitutionalSubaccountsOrdersOpen = Entry[_List](
        "institutional/subaccounts/orders/open", "private", "GET", {"cost": 5, "noMarket": 100}
    )
    private_post_order = privatePostOrder = Entry[_Dict]("order", "private", "POST", {"cost": 1})
    private_post_cancelordersafter = privatePostCancelOrdersAfter = Entry[_Dict](
        "cancelOrdersAfter", "private", "POST", {"cost": 5}
    )
    private_post_withdrawal = privatePostWithdrawal = Entry[_Dict]("withdrawal", "private", "POST", {"cost": 1})
    private_post_crypto_withdrawal = privatePostCryptoWithdrawal = Entry[_Dict](
        "crypto/withdrawal", "private", "POST", {"cost": 25}
    )
    private_post_subaccounts = privatePostSubaccounts = Entry[_Dict]("subaccounts", "private", "POST", {"cost": 5})
    private_post_subaccounts_transfers = privatePostSubaccountsTransfers = Entry[_Dict](
        "subaccounts/transfers", "private", "POST", {"cost": 5}
    )
    private_put_order = privatePutOrder = Entry[_Dict]("order", "private", "PUT", {"cost": 1})
    private_delete_order = privateDeleteOrder = Entry[_Dict]("order", "private", "DELETE", {"cost": 1})
    private_delete_orders = privateDeleteOrders = Entry[_List](
        "orders", "private", "DELETE", {"cost": 25, "noMarket": 100}
    )
    private_delete_atomic_orders = privateDeleteAtomicOrders = Entry[_List](
        "atomic/orders", "private", "DELETE", {"cost": 100}
    )
    private_delete_institutional_subaccounts_order = privateDeleteInstitutionalSubaccountsOrder = Entry[_Dict](
        "institutional/subaccounts/order", "private", "DELETE", {"cost": 1}
    )
    private_delete_institutional_subaccounts_orders = privateDeleteInstitutionalSubaccountsOrders = Entry[_Dict](
        "institutional/subaccounts/orders", "private", "DELETE", {"cost": 25, "noMarket": 100}
    )
