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
    exchange_get_markets = exchangeGetMarkets = Entry[_Dict]("markets", "exchange", "GET", {"cost": 1})
    exchangeprivate_get_candles = exchangePrivateGetCandles = Entry[_Dict](
        "candles", "exchangePrivate", "GET", {"cost": 1}
    )
    exchangeprivate_get_move = exchangePrivateGetMove = Entry[_Dict]("move", "exchangePrivate", "GET", {"cost": 1})
    exchangeprivate_get_move_list_moves = exchangePrivateGetMoveListMoves = Entry[_Dict](
        "move/list_moves", "exchangePrivate", "GET", {"cost": 1}
    )
    exchangeprivate_get_transfers = exchangePrivateGetTransfers = Entry[_Dict](
        "transfers", "exchangePrivate", "GET", {"cost": 1}
    )
    exchangeprivate_post_convert = exchangePrivatePostConvert = Entry[_Dict](
        "convert", "exchangePrivate", "POST", {"cost": 1}
    )
    exchangeprivate_post_move = exchangePrivatePostMove = Entry[_Dict]("move", "exchangePrivate", "POST", {"cost": 1})
    public_get_orderbook = publicGetOrderbook = Entry[_Dict]("orderbook", "public", "GET", {"cost": 1})
    public_get_orderbook_top = publicGetOrderbookTop = Entry[_Dict]("orderbook_top", "public", "GET", {"cost": 1})
    public_get_ticker = publicGetTicker = Entry[_Dict]("ticker", "public", "GET", {"cost": 1})
    public_get_tickers = publicGetTickers = Entry[_Dict]("tickers", "public", "GET", {"cost": 1})
    public_get_trades = publicGetTrades = Entry[_Dict]("trades", "public", "GET", {"cost": 1})
    private_get_accounts_id_pending = privateGetAccountsIdPending = Entry[_Dict](
        "accounts/{id}/pending", "private", "GET", {"cost": 1}
    )
    private_get_accounts_id_transactions = privateGetAccountsIdTransactions = Entry[_Dict](
        "accounts/{id}/transactions", "private", "GET", {"cost": 1}
    )
    private_get_balance = privateGetBalance = Entry[_Dict]("balance", "private", "GET", {"cost": 1})
    private_get_beneficiaries = privateGetBeneficiaries = Entry[_Dict]("beneficiaries", "private", "GET", {"cost": 1})
    private_get_send_networks = privateGetSendNetworks = Entry[_Dict]("send/networks", "private", "GET", {"cost": 1})
    private_get_fee_info = privateGetFeeInfo = Entry[_Dict]("fee_info", "private", "GET", {"cost": 1})
    private_get_funding_address = privateGetFundingAddress = Entry[_Dict](
        "funding_address", "private", "GET", {"cost": 1}
    )
    private_get_listorders = privateGetListorders = Entry[_Dict]("listorders", "private", "GET", {"cost": 1})
    private_get_listtrades = privateGetListtrades = Entry[_Dict]("listtrades", "private", "GET", {"cost": 1})
    private_get_send_fee = privateGetSendFee = Entry[_Dict]("send_fee", "private", "GET", {"cost": 1})
    private_get_orders_id = privateGetOrdersId = Entry[_Dict]("orders/{id}", "private", "GET", {"cost": 1})
    private_get_withdrawals = privateGetWithdrawals = Entry[_Dict]("withdrawals", "private", "GET", {"cost": 1})
    private_get_withdrawals_id = privateGetWithdrawalsId = Entry[_Dict](
        "withdrawals/{id}", "private", "GET", {"cost": 1}
    )
    private_get_transfers = privateGetTransfers = Entry[_Dict]("transfers", "private", "GET", {"cost": 1})
    private_get_users_linked = privateGetUsersLinked = Entry[_Dict]("users/linked", "private", "GET", {"cost": 1})
    private_post_accounts = privatePostAccounts = Entry[_Dict]("accounts", "private", "POST", {"cost": 1})
    private_post_address_validate = privatePostAddressValidate = Entry[_Dict](
        "address/validate", "private", "POST", {"cost": 1}
    )
    private_post_postorder = privatePostPostorder = Entry[_Dict]("postorder", "private", "POST", {"cost": 1})
    private_post_marketorder = privatePostMarketorder = Entry[_Dict]("marketorder", "private", "POST", {"cost": 1})
    private_post_stoporder = privatePostStoporder = Entry[_Dict]("stoporder", "private", "POST", {"cost": 1})
    private_post_funding_address = privatePostFundingAddress = Entry[_Dict](
        "funding_address", "private", "POST", {"cost": 1}
    )
    private_post_withdrawals = privatePostWithdrawals = Entry[_Dict]("withdrawals", "private", "POST", {"cost": 1})
    private_post_send = privatePostSend = Entry[_Dict]("send", "private", "POST", {"cost": 1})
    private_post_oauth2_grant = privatePostOauth2Grant = Entry[_Dict]("oauth2/grant", "private", "POST", {"cost": 1})
    private_post_beneficiaries = privatePostBeneficiaries = Entry[_Dict](
        "beneficiaries", "private", "POST", {"cost": 1}
    )
    private_put_accounts_id_name = privatePutAccountsIdName = Entry[_Dict](
        "accounts/{id}/name", "private", "PUT", {"cost": 1}
    )
    private_delete_withdrawals_id = privateDeleteWithdrawalsId = Entry[_Dict](
        "withdrawals/{id}", "private", "DELETE", {"cost": 1}
    )
    private_delete_beneficiaries_id = privateDeleteBeneficiariesId = Entry[_Dict](
        "beneficiaries/{id}", "private", "DELETE", {"cost": 1}
    )
