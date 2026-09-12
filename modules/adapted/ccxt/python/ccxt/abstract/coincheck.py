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
    public_get_exchange_orders_rate = publicGetExchangeOrdersRate = Entry[_Dict](
        "exchange/orders/rate", "public", "GET", {"cost": 1}
    )
    public_get_exchange_status = publicGetExchangeStatus = Entry[_Dict]("exchange_status", "public", "GET", {"cost": 1})
    public_get_order_books = publicGetOrderBooks = Entry[_Dict]("order_books", "public", "GET", {"cost": 1})
    public_get_rate_pair = publicGetRatePair = Entry[_Dict]("rate/{pair}", "public", "GET", {"cost": 1})
    public_get_ticker = publicGetTicker = Entry[_Dict]("ticker", "public", "GET", {"cost": 1})
    public_get_trades = publicGetTrades = Entry[_Dict]("trades", "public", "GET", {"cost": 1})
    private_get_accounts = privateGetAccounts = Entry[_Dict]("accounts", "private", "GET", {"cost": 1})
    private_get_accounts_balance = privateGetAccountsBalance = Entry[_Dict](
        "accounts/balance", "private", "GET", {"cost": 1}
    )
    private_get_accounts_leverage_balance = privateGetAccountsLeverageBalance = Entry[_Dict](
        "accounts/leverage_balance", "private", "GET", {"cost": 1}
    )
    private_get_bank_accounts = privateGetBankAccounts = Entry[_Dict]("bank_accounts", "private", "GET", {"cost": 1})
    private_get_deposit_money = privateGetDepositMoney = Entry[_Dict]("deposit_money", "private", "GET", {"cost": 1})
    private_get_exchange_orders_id = privateGetExchangeOrdersId = Entry[_Dict](
        "exchange/orders/{id}", "private", "GET", {"cost": 1}
    )
    private_get_exchange_orders_opens = privateGetExchangeOrdersOpens = Entry[_Dict](
        "exchange/orders/opens", "private", "GET", {"cost": 1}
    )
    private_get_exchange_orders_cancel_status = privateGetExchangeOrdersCancelStatus = Entry[_Dict](
        "exchange/orders/cancel_status", "private", "GET", {"cost": 1}
    )
    private_get_exchange_orders_transactions = privateGetExchangeOrdersTransactions = Entry[_Dict](
        "exchange/orders/transactions", "private", "GET", {"cost": 1}
    )
    private_get_exchange_orders_transactions_pagination = privateGetExchangeOrdersTransactionsPagination = Entry[_Dict](
        "exchange/orders/transactions_pagination", "private", "GET", {"cost": 1}
    )
    private_get_exchange_leverage_positions = privateGetExchangeLeveragePositions = Entry[_Dict](
        "exchange/leverage/positions", "private", "GET", {"cost": 1}
    )
    private_get_lending_borrows_matches = privateGetLendingBorrowsMatches = Entry[_Dict](
        "lending/borrows/matches", "private", "GET", {"cost": 1}
    )
    private_get_send_money = privateGetSendMoney = Entry[_Dict]("send_money", "private", "GET", {"cost": 1})
    private_get_withdraws = privateGetWithdraws = Entry[_Dict]("withdraws", "private", "GET", {"cost": 1})
    private_post_bank_accounts = privatePostBankAccounts = Entry[_Dict]("bank_accounts", "private", "POST", {"cost": 1})
    private_post_deposit_money_id_fast = privatePostDepositMoneyIdFast = Entry[_Dict](
        "deposit_money/{id}/fast", "private", "POST", {"cost": 1}
    )
    private_post_exchange_orders = privatePostExchangeOrders = Entry[_Dict](
        "exchange/orders", "private", "POST", {"cost": 1}
    )
    private_post_exchange_transfers_to_leverage = privatePostExchangeTransfersToLeverage = Entry[_Dict](
        "exchange/transfers/to_leverage", "private", "POST", {"cost": 1}
    )
    private_post_exchange_transfers_from_leverage = privatePostExchangeTransfersFromLeverage = Entry[_Dict](
        "exchange/transfers/from_leverage", "private", "POST", {"cost": 1}
    )
    private_post_lending_borrows = privatePostLendingBorrows = Entry[_Dict](
        "lending/borrows", "private", "POST", {"cost": 1}
    )
    private_post_lending_borrows_id_repay = privatePostLendingBorrowsIdRepay = Entry[_Dict](
        "lending/borrows/{id}/repay", "private", "POST", {"cost": 1}
    )
    private_post_send_money = privatePostSendMoney = Entry[_Dict]("send_money", "private", "POST", {"cost": 1})
    private_post_withdraws = privatePostWithdraws = Entry[_Dict]("withdraws", "private", "POST", {"cost": 1})
    private_delete_bank_accounts_id = privateDeleteBankAccountsId = Entry[_Dict](
        "bank_accounts/{id}", "private", "DELETE", {"cost": 1}
    )
    private_delete_exchange_orders_id = privateDeleteExchangeOrdersId = Entry[_Dict](
        "exchange/orders/{id}", "private", "DELETE", {"cost": 1}
    )
    private_delete_withdraws_id = privateDeleteWithdrawsId = Entry[_Dict](
        "withdraws/{id}", "private", "DELETE", {"cost": 1}
    )
