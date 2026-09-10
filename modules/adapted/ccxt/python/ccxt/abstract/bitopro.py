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
    public_get_order_book_pair = publicGetOrderBookPair = Entry[_Dict](
        "order-book/{pair}", "public", "GET", {"cost": 1}
    )
    public_get_tickers = publicGetTickers = Entry[_Dict]("tickers", "public", "GET", {"cost": 1})
    public_get_tickers_pair = publicGetTickersPair = Entry[_Dict]("tickers/{pair}", "public", "GET", {"cost": 1})
    public_get_trades_pair = publicGetTradesPair = Entry[_Dict]("trades/{pair}", "public", "GET", {"cost": 1})
    public_get_provisioning_currencies = publicGetProvisioningCurrencies = Entry[_Dict](
        "provisioning/currencies", "public", "GET", {"cost": 1}
    )
    public_get_provisioning_trading_pairs = publicGetProvisioningTradingPairs = Entry[_Dict](
        "provisioning/trading-pairs", "public", "GET", {"cost": 1}
    )
    public_get_provisioning_limitations_and_fees = publicGetProvisioningLimitationsAndFees = Entry[_Dict](
        "provisioning/limitations-and-fees", "public", "GET", {"cost": 1}
    )
    public_get_trading_history_pair = publicGetTradingHistoryPair = Entry[_Dict](
        "trading-history/{pair}", "public", "GET", {"cost": 1}
    )
    public_get_price_otc_currency = publicGetPriceOtcCurrency = Entry[_Dict](
        "price/otc/{currency}", "public", "GET", {"cost": 1}
    )
    private_get_accounts_balance = privateGetAccountsBalance = Entry[_Dict](
        "accounts/balance", "private", "GET", {"cost": 1}
    )
    private_get_orders_history = privateGetOrdersHistory = Entry[_Dict]("orders/history", "private", "GET", {"cost": 1})
    private_get_orders_all_pair = privateGetOrdersAllPair = Entry[_Dict](
        "orders/all/{pair}", "private", "GET", {"cost": 1}
    )
    private_get_orders_trades_pair = privateGetOrdersTradesPair = Entry[_Dict](
        "orders/trades/{pair}", "private", "GET", {"cost": 1}
    )
    private_get_orders_pair_orderid = privateGetOrdersPairOrderId = Entry[_Dict](
        "orders/{pair}/{orderId}", "private", "GET", {"cost": 1}
    )
    private_get_wallet_withdraw_currency_serial = privateGetWalletWithdrawCurrencySerial = Entry[_Dict](
        "wallet/withdraw/{currency}/{serial}", "private", "GET", {"cost": 1}
    )
    private_get_wallet_withdraw_currency_id_id = privateGetWalletWithdrawCurrencyIdId = Entry[_Dict](
        "wallet/withdraw/{currency}/id/{id}", "private", "GET", {"cost": 1}
    )
    private_get_wallet_deposithistory_currency = privateGetWalletDepositHistoryCurrency = Entry[_Dict](
        "wallet/depositHistory/{currency}", "private", "GET", {"cost": 1}
    )
    private_get_wallet_withdrawhistory_currency = privateGetWalletWithdrawHistoryCurrency = Entry[_Dict](
        "wallet/withdrawHistory/{currency}", "private", "GET", {"cost": 1}
    )
    private_get_orders_open = privateGetOrdersOpen = Entry[_Dict]("orders/open", "private", "GET", {"cost": 1})
    private_post_orders_pair = privatePostOrdersPair = Entry[_Dict]("orders/{pair}", "private", "POST", {"cost": 0.5})
    private_post_orders_batch = privatePostOrdersBatch = Entry[_Dict](
        "orders/batch", "private", "POST", {"cost": 6.666666666666667}
    )
    private_post_wallet_withdraw_currency = privatePostWalletWithdrawCurrency = Entry[_Dict](
        "wallet/withdraw/{currency}", "private", "POST", {"cost": 10}
    )
    private_put_orders = privatePutOrders = Entry[_Dict]("orders", "private", "PUT", {"cost": 5})
    private_delete_orders_pair_id = privateDeleteOrdersPairId = Entry[_Dict](
        "orders/{pair}/{id}", "private", "DELETE", {"cost": 0.6666666666666666}
    )
    private_delete_orders_all = privateDeleteOrdersAll = Entry[_Dict]("orders/all", "private", "DELETE", {"cost": 5})
    private_delete_orders_pair = privateDeleteOrdersPair = Entry[_Dict](
        "orders/{pair}", "private", "DELETE", {"cost": 5}
    )
