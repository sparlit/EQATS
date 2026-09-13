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
    public_get_exchanges_pair_ticker = publicGetExchangesPairTicker = Entry[_Dict](
        "Exchanges/{pair}/Ticker", "public", "GET", {"cost": 1}
    )
    public_get_exchanges_pair_orderbook = publicGetExchangesPairOrderbook = Entry[_Dict](
        "Exchanges/{pair}/orderbook", "public", "GET", {"cost": 1}
    )
    public_get_exchanges_pair_trades = publicGetExchangesPairTrades = Entry[_List](
        "Exchanges/{pair}/trades", "public", "GET", {"cost": 1}
    )
    public_get_exchanges_pair_lasttrades = publicGetExchangesPairLasttrades = Entry[_List](
        "Exchanges/{pair}/lasttrades", "public", "GET", {"cost": 1}
    )
    private_post_merchant_createcheckout = privatePostMerchantCreateCheckout = Entry[_Dict](
        "Merchant/CreateCheckout", "private", "POST", {"cost": 1}
    )
    private_post_funds_addcoinfundsrequest = privatePostFundsAddCoinFundsRequest = Entry[_Dict](
        "Funds/AddCoinFundsRequest", "private", "POST", {"cost": 1}
    )
    private_post_order_addfund = privatePostOrderAddFund = Entry[_Dict]("Order/AddFund", "private", "POST", {"cost": 1})
    private_post_order_addorder = privatePostOrderAddOrder = Entry[_Dict](
        "Order/AddOrder", "private", "POST", {"cost": 1}
    )
    private_post_order_getbyid = privatePostOrderGetById = Entry[_Dict]("Order/GetById", "private", "POST", {"cost": 1})
    private_post_order_addordermarketpricebuy = privatePostOrderAddOrderMarketPriceBuy = Entry[_Dict](
        "Order/AddOrderMarketPriceBuy", "private", "POST", {"cost": 1}
    )
    private_post_order_addordermarketpricesell = privatePostOrderAddOrderMarketPriceSell = Entry[_Dict](
        "Order/AddOrderMarketPriceSell", "private", "POST", {"cost": 1}
    )
    private_post_order_cancelorder = privatePostOrderCancelOrder = Entry[_Dict](
        "Order/CancelOrder", "private", "POST", {"cost": 1}
    )
    private_post_order_addcoinfundsrequest = privatePostOrderAddCoinFundsRequest = Entry[_Dict](
        "Order/AddCoinFundsRequest", "private", "POST", {"cost": 1}
    )
    private_post_order_addstoporder = privatePostOrderAddStopOrder = Entry[_Dict](
        "Order/AddStopOrder", "private", "POST", {"cost": 1}
    )
    private_post_payment_getmyid = privatePostPaymentGetMyId = Entry[_Dict](
        "Payment/GetMyId", "private", "POST", {"cost": 1}
    )
    private_post_payment_send = privatePostPaymentSend = Entry[_Dict]("Payment/Send", "private", "POST", {"cost": 1})
    private_post_payment_pay = privatePostPaymentPay = Entry[str]("Payment/Pay", "private", "POST", {"cost": 1})
    private_get_account_balance = privateGetAccountBalance = Entry[_Dict](
        "Account/Balance", "private", "GET", {"cost": 1}
    )
    private_get_account_balance_v2 = privateGetAccountBalanceV2 = Entry[_Dict](
        "Account/Balance/v2", "private", "GET", {"cost": 1}
    )
    private_get_order_myorders = privateGetOrderMyOrders = Entry[_Dict]("Order/MyOrders", "private", "GET", {"cost": 1})
    private_get_order_getbyid = privateGetOrderGetById = Entry[_Dict]("Order/GetById", "private", "GET", {"cost": 1})
    private_get_order_accounthistory = privateGetOrderAccountHistory = Entry[_List](
        "Order/AccountHistory", "private", "GET", {"cost": 1}
    )
    private_get_order_orderhistory = privateGetOrderOrderHistory = Entry[_List](
        "Order/OrderHistory", "private", "GET", {"cost": 1}
    )
