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
    public_get_available_books = publicGetAvailableBooks = Entry[_Dict]("available_books", "public", "GET", {"cost": 1})
    public_get_catalogues = publicGetCatalogues = Entry[_Dict]("catalogues", "public", "GET", {"cost": 1})
    public_get_ticker = publicGetTicker = Entry[_Dict]("ticker", "public", "GET", {"cost": 1})
    public_get_order_book = publicGetOrderBook = Entry[_Dict]("order_book", "public", "GET", {"cost": 1})
    public_get_trades = publicGetTrades = Entry[_Dict]("trades", "public", "GET", {"cost": 1})
    public_get_ohlc = publicGetOhlc = Entry[_Dict]("ohlc", "public", "GET", {"cost": 1})
    private_get_account_status = privateGetAccountStatus = Entry[_Dict]("account_status", "private", "GET", {"cost": 1})
    private_get_balance = privateGetBalance = Entry[_Dict]("balance", "private", "GET", {"cost": 1})
    private_get_fees = privateGetFees = Entry[_Dict]("fees", "private", "GET", {"cost": 1})
    private_get_fundings = privateGetFundings = Entry[_Dict]("fundings", "private", "GET", {"cost": 1})
    private_get_fundings_fid = privateGetFundingsFid = Entry[_Dict]("fundings/{fid}", "private", "GET", {"cost": 1})
    private_get_funding_destination = privateGetFundingDestination = Entry[_Dict](
        "funding_destination", "private", "GET", {"cost": 1}
    )
    private_get_kyc_documents = privateGetKycDocuments = Entry[_Dict]("kyc_documents", "private", "GET", {"cost": 1})
    private_get_ledger = privateGetLedger = Entry[_Dict]("ledger", "private", "GET", {"cost": 1})
    private_get_ledger_trades = privateGetLedgerTrades = Entry[_Dict]("ledger/trades", "private", "GET", {"cost": 1})
    private_get_ledger_fees = privateGetLedgerFees = Entry[_Dict]("ledger/fees", "private", "GET", {"cost": 1})
    private_get_ledger_fundings = privateGetLedgerFundings = Entry[_Dict](
        "ledger/fundings", "private", "GET", {"cost": 1}
    )
    private_get_ledger_withdrawals = privateGetLedgerWithdrawals = Entry[_Dict](
        "ledger/withdrawals", "private", "GET", {"cost": 1}
    )
    private_get_mx_bank_codes = privateGetMxBankCodes = Entry[_Dict]("mx_bank_codes", "private", "GET", {"cost": 1})
    private_get_open_orders = privateGetOpenOrders = Entry[_Dict]("open_orders", "private", "GET", {"cost": 1})
    private_get_order_trades_oid = privateGetOrderTradesOid = Entry[_Dict](
        "order_trades/{oid}", "private", "GET", {"cost": 1}
    )
    private_get_orders_oid = privateGetOrdersOid = Entry[_Dict]("orders/{oid}", "private", "GET", {"cost": 1})
    private_get_user_trades = privateGetUserTrades = Entry[_Dict]("user_trades", "private", "GET", {"cost": 1})
    private_get_user_trades_tid = privateGetUserTradesTid = Entry[_Dict](
        "user_trades/{tid}", "private", "GET", {"cost": 1}
    )
    private_get_withdrawals = privateGetWithdrawals = Entry[_Dict]("withdrawals/", "private", "GET", {"cost": 1})
    private_get_withdrawals_wid = privateGetWithdrawalsWid = Entry[_Dict](
        "withdrawals/{wid}", "private", "GET", {"cost": 1}
    )
    private_post_bitcoin_withdrawal = privatePostBitcoinWithdrawal = Entry[_Dict](
        "bitcoin_withdrawal", "private", "POST", {"cost": 1}
    )
    private_post_debit_card_withdrawal = privatePostDebitCardWithdrawal = Entry[_Dict](
        "debit_card_withdrawal", "private", "POST", {"cost": 1}
    )
    private_post_ether_withdrawal = privatePostEtherWithdrawal = Entry[_Dict](
        "ether_withdrawal", "private", "POST", {"cost": 1}
    )
    private_post_orders = privatePostOrders = Entry[_Dict]("orders", "private", "POST", {"cost": 1})
    private_post_phone_number = privatePostPhoneNumber = Entry[_Dict]("phone_number", "private", "POST", {"cost": 1})
    private_post_phone_verification = privatePostPhoneVerification = Entry[_Dict](
        "phone_verification", "private", "POST", {"cost": 1}
    )
    private_post_phone_withdrawal = privatePostPhoneWithdrawal = Entry[_Dict](
        "phone_withdrawal", "private", "POST", {"cost": 1}
    )
    private_post_spei_withdrawal = privatePostSpeiWithdrawal = Entry[_Dict](
        "spei_withdrawal", "private", "POST", {"cost": 1}
    )
    private_post_ripple_withdrawal = privatePostRippleWithdrawal = Entry[_Dict](
        "ripple_withdrawal", "private", "POST", {"cost": 1}
    )
    private_post_bcash_withdrawal = privatePostBcashWithdrawal = Entry[_Dict](
        "bcash_withdrawal", "private", "POST", {"cost": 1}
    )
    private_post_litecoin_withdrawal = privatePostLitecoinWithdrawal = Entry[_Dict](
        "litecoin_withdrawal", "private", "POST", {"cost": 1}
    )
    private_delete_orders = privateDeleteOrders = Entry[_Dict]("orders", "private", "DELETE", {"cost": 1})
    private_delete_orders_oid = privateDeleteOrdersOid = Entry[_Dict]("orders/{oid}", "private", "DELETE", {"cost": 1})
    private_delete_orders_all = privateDeleteOrdersAll = Entry[_Dict]("orders/all", "private", "DELETE", {"cost": 1})
