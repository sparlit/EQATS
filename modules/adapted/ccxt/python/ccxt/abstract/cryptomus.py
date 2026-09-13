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
    public_get_v2_user_api_exchange_markets = publicGetV2UserApiExchangeMarkets = Entry[_Dict](
        "v2/user-api/exchange/markets", "public", "GET", {"cost": 1}
    )
    public_get_v2_user_api_exchange_market_price = publicGetV2UserApiExchangeMarketPrice = Entry[_Dict](
        "v2/user-api/exchange/market/price", "public", "GET", {"cost": 1}
    )
    public_get_v1_exchange_market_assets = publicGetV1ExchangeMarketAssets = Entry[_Dict](
        "v1/exchange/market/assets", "public", "GET", {"cost": 1}
    )
    public_get_v1_exchange_market_order_book_currencypair = publicGetV1ExchangeMarketOrderBookCurrencyPair = Entry[
        _Dict
    ]("v1/exchange/market/order-book/{currencyPair}", "public", "GET", {"cost": 1})
    public_get_v1_exchange_market_tickers = publicGetV1ExchangeMarketTickers = Entry[_Dict](
        "v1/exchange/market/tickers", "public", "GET", {"cost": 1}
    )
    public_get_v1_exchange_market_trades_currencypair = publicGetV1ExchangeMarketTradesCurrencyPair = Entry[_Dict](
        "v1/exchange/market/trades/{currencyPair}", "public", "GET", {"cost": 1}
    )
    private_get_v2_user_api_exchange_orders = privateGetV2UserApiExchangeOrders = Entry[_Dict](
        "v2/user-api/exchange/orders", "private", "GET", {"cost": 1}
    )
    private_get_v2_user_api_exchange_orders_history = privateGetV2UserApiExchangeOrdersHistory = Entry[_Dict](
        "v2/user-api/exchange/orders/history", "private", "GET", {"cost": 1}
    )
    private_get_v2_user_api_exchange_account_balance = privateGetV2UserApiExchangeAccountBalance = Entry[_Dict](
        "v2/user-api/exchange/account/balance", "private", "GET", {"cost": 1}
    )
    private_get_v2_user_api_exchange_account_tariffs = privateGetV2UserApiExchangeAccountTariffs = Entry[_Dict](
        "v2/user-api/exchange/account/tariffs", "private", "GET", {"cost": 1}
    )
    private_get_v2_user_api_payment_services = privateGetV2UserApiPaymentServices = Entry[_Dict](
        "v2/user-api/payment/services", "private", "GET", {"cost": 1}
    )
    private_get_v2_user_api_payout_services = privateGetV2UserApiPayoutServices = Entry[_Dict](
        "v2/user-api/payout/services", "private", "GET", {"cost": 1}
    )
    private_get_v2_user_api_transaction_list = privateGetV2UserApiTransactionList = Entry[_Dict](
        "v2/user-api/transaction/list", "private", "GET", {"cost": 1}
    )
    private_post_v2_user_api_exchange_orders = privatePostV2UserApiExchangeOrders = Entry[_Dict](
        "v2/user-api/exchange/orders", "private", "POST", {"cost": 1}
    )
    private_post_v2_user_api_exchange_orders_market = privatePostV2UserApiExchangeOrdersMarket = Entry[_Dict](
        "v2/user-api/exchange/orders/market", "private", "POST", {"cost": 1}
    )
    private_delete_v2_user_api_exchange_orders_orderid = privateDeleteV2UserApiExchangeOrdersOrderId = Entry[_Dict](
        "v2/user-api/exchange/orders/{orderId}", "private", "DELETE", {"cost": 1}
    )
