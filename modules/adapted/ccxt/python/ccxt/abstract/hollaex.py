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
    public_get_health = publicGetHealth = Entry[_Dict]("health", "public", "GET", {"cost": 1})
    public_get_constants = publicGetConstants = Entry[_Dict]("constants", "public", "GET", {"cost": 1})
    public_get_kit = publicGetKit = Entry[_Dict]("kit", "public", "GET", {"cost": 1})
    public_get_tiers = publicGetTiers = Entry[_Dict]("tiers", "public", "GET", {"cost": 1})
    public_get_ticker = publicGetTicker = Entry[_Dict]("ticker", "public", "GET", {"cost": 1})
    public_get_tickers = publicGetTickers = Entry[_Dict]("tickers", "public", "GET", {"cost": 1})
    public_get_orderbook = publicGetOrderbook = Entry[_Dict]("orderbook", "public", "GET", {"cost": 1})
    public_get_orderbooks = publicGetOrderbooks = Entry[_Dict]("orderbooks", "public", "GET", {"cost": 1})
    public_get_trades = publicGetTrades = Entry[_Dict]("trades", "public", "GET", {"cost": 1})
    public_get_chart = publicGetChart = Entry[_List]("chart", "public", "GET", {"cost": 1})
    public_get_charts = publicGetCharts = Entry[_Dict]("charts", "public", "GET", {"cost": 1})
    public_get_minicharts = publicGetMinicharts = Entry[_Dict]("minicharts", "public", "GET", {"cost": 1})
    public_get_oracle_prices = publicGetOraclePrices = Entry[_Dict]("oracle/prices", "public", "GET", {"cost": 1})
    public_get_quick_trade = publicGetQuickTrade = Entry[_Dict]("quick-trade", "public", "GET", {"cost": 1})
    public_get_udf_config = publicGetUdfConfig = Entry[_Dict]("udf/config", "public", "GET", {"cost": 1})
    public_get_udf_history = publicGetUdfHistory = Entry[_Dict]("udf/history", "public", "GET", {"cost": 1})
    public_get_udf_symbols = publicGetUdfSymbols = Entry[_Dict]("udf/symbols", "public", "GET", {"cost": 1})
    private_get_user = privateGetUser = Entry[_Dict]("user", "private", "GET", {"cost": 1})
    private_get_user_balance = privateGetUserBalance = Entry[_Dict]("user/balance", "private", "GET", {"cost": 1})
    private_get_user_deposits = privateGetUserDeposits = Entry[_Dict]("user/deposits", "private", "GET", {"cost": 1})
    private_get_user_withdrawals = privateGetUserWithdrawals = Entry[_Dict](
        "user/withdrawals", "private", "GET", {"cost": 1}
    )
    private_get_user_withdrawal_fee = privateGetUserWithdrawalFee = Entry[_Dict](
        "user/withdrawal/fee", "private", "GET", {"cost": 1}
    )
    private_get_user_trades = privateGetUserTrades = Entry[_Dict]("user/trades", "private", "GET", {"cost": 1})
    private_get_orders = privateGetOrders = Entry[_Dict]("orders", "private", "GET", {"cost": 1})
    private_get_order = privateGetOrder = Entry[_Dict]("order", "private", "GET", {"cost": 1})
    private_post_user_withdrawal = privatePostUserWithdrawal = Entry[_Dict](
        "user/withdrawal", "private", "POST", {"cost": 1}
    )
    private_post_order = privatePostOrder = Entry[_Dict]("order", "private", "POST", {"cost": 1})
    private_delete_order_all = privateDeleteOrderAll = Entry[_List]("order/all", "private", "DELETE", {"cost": 1})
    private_delete_order = privateDeleteOrder = Entry[_Dict]("order", "private", "DELETE", {"cost": 1})
