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

_List = list[object]
_Dict = dict[str, object]


class ImplicitAPI:
    public_get_getvalidprimarycurrencycodes = publicGetGetValidPrimaryCurrencyCodes = Entry[_List](
        "GetValidPrimaryCurrencyCodes", "public", "GET", {"cost": 1}
    )
    public_get_getvalidsecondarycurrencycodes = publicGetGetValidSecondaryCurrencyCodes = Entry[_List](
        "GetValidSecondaryCurrencyCodes", "public", "GET", {"cost": 1}
    )
    public_get_getvalidlimitordertypes = publicGetGetValidLimitOrderTypes = Entry[_List](
        "GetValidLimitOrderTypes", "public", "GET", {"cost": 1}
    )
    public_get_getvalidmarketordertypes = publicGetGetValidMarketOrderTypes = Entry[_List](
        "GetValidMarketOrderTypes", "public", "GET", {"cost": 1}
    )
    public_get_getvalidordertypes = publicGetGetValidOrderTypes = Entry[_List](
        "GetValidOrderTypes", "public", "GET", {"cost": 1}
    )
    public_get_getvalidtransactiontypes = publicGetGetValidTransactionTypes = Entry[_List](
        "GetValidTransactionTypes", "public", "GET", {"cost": 1}
    )
    public_get_getmarketsummary = publicGetGetMarketSummary = Entry[_Dict](
        "GetMarketSummary", "public", "GET", {"cost": 1}
    )
    public_get_getorderbook = publicGetGetOrderBook = Entry[_Dict]("GetOrderBook", "public", "GET", {"cost": 1})
    public_get_getallorders = publicGetGetAllOrders = Entry[_Dict]("GetAllOrders", "public", "GET", {"cost": 1})
    public_get_gettradehistorysummary = publicGetGetTradeHistorySummary = Entry[_Dict](
        "GetTradeHistorySummary", "public", "GET", {"cost": 1}
    )
    public_get_getrecenttrades = publicGetGetRecentTrades = Entry[_Dict](
        "GetRecentTrades", "public", "GET", {"cost": 1}
    )
    public_get_getfxrates = publicGetGetFxRates = Entry[_List]("GetFxRates", "public", "GET", {"cost": 1})
    public_get_getorderminimumvolumes = publicGetGetOrderMinimumVolumes = Entry[_Dict](
        "GetOrderMinimumVolumes", "public", "GET", {"cost": 1}
    )
    public_get_getcryptowithdrawalfees = publicGetGetCryptoWithdrawalFees = Entry[_Dict](
        "GetCryptoWithdrawalFees", "public", "GET", {"cost": 1}
    )
    public_get_getcryptowithdrawalfees2 = publicGetGetCryptoWithdrawalFees2 = Entry[_List](
        "GetCryptoWithdrawalFees2", "public", "GET", {"cost": 1}
    )
    public_get_getnetworks = publicGetGetNetworks = Entry[_List]("GetNetworks", "public", "GET", {"cost": 1})
    public_get_getprimarycurrencyconfig2 = publicGetGetPrimaryCurrencyConfig2 = Entry[_List](
        "GetPrimaryCurrencyConfig2", "public", "GET", {"cost": 1}
    )
    private_post_getopenorders = privatePostGetOpenOrders = Entry[_Dict](
        "GetOpenOrders", "private", "POST", {"cost": 1}
    )
    private_post_getclosedorders = privatePostGetClosedOrders = Entry[_Dict](
        "GetClosedOrders", "private", "POST", {"cost": 1}
    )
    private_post_getclosedfilledorders = privatePostGetClosedFilledOrders = Entry[_Dict](
        "GetClosedFilledOrders", "private", "POST", {"cost": 1}
    )
    private_post_getorderdetails = privatePostGetOrderDetails = Entry[_Dict](
        "GetOrderDetails", "private", "POST", {"cost": 1}
    )
    private_post_getaccounts = privatePostGetAccounts = Entry[_Dict]("GetAccounts", "private", "POST", {"cost": 1})
    private_post_gettransactions = privatePostGetTransactions = Entry[_Dict](
        "GetTransactions", "private", "POST", {"cost": 1}
    )
    private_post_getfiatbankaccounts = privatePostGetFiatBankAccounts = Entry[_List](
        "GetFiatBankAccounts", "private", "POST", {"cost": 1}
    )
    private_post_getdigitalcurrencydepositaddress = privatePostGetDigitalCurrencyDepositAddress = Entry[_Dict](
        "GetDigitalCurrencyDepositAddress", "private", "POST", {"cost": 1}
    )
    private_post_getdigitalcurrencydepositaddress2 = privatePostGetDigitalCurrencyDepositAddress2 = Entry[_List](
        "GetDigitalCurrencyDepositAddress2", "private", "POST", {"cost": 1}
    )
    private_post_getdigitalcurrencydepositaddresses = privatePostGetDigitalCurrencyDepositAddresses = Entry[_Dict](
        "GetDigitalCurrencyDepositAddresses", "private", "POST", {"cost": 1}
    )
    private_post_getdigitalcurrencydepositaddresses2 = privatePostGetDigitalCurrencyDepositAddresses2 = Entry[_Dict](
        "GetDigitalCurrencyDepositAddresses2", "private", "POST", {"cost": 1}
    )
    private_post_gettrades = privatePostGetTrades = Entry[_Dict]("GetTrades", "private", "POST", {"cost": 1})
    private_post_getbrokeragefees = privatePostGetBrokerageFees = Entry[_List](
        "GetBrokerageFees", "private", "POST", {"cost": 1}
    )
    private_post_getdigitalcurrencywithdrawal = privatePostGetDigitalCurrencyWithdrawal = Entry[_Dict](
        "GetDigitalCurrencyWithdrawal", "private", "POST", {"cost": 1}
    )
    private_post_placelimitorder = privatePostPlaceLimitOrder = Entry[_Dict](
        "PlaceLimitOrder", "private", "POST", {"cost": 1}
    )
    private_post_placemarketorder = privatePostPlaceMarketOrder = Entry[_Dict](
        "PlaceMarketOrder", "private", "POST", {"cost": 1}
    )
    private_post_cancelorder = privatePostCancelOrder = Entry[_Dict]("CancelOrder", "private", "POST", {"cost": 1})
    private_post_synchdigitalcurrencydepositaddresswithblockchain = (
        privatePostSynchDigitalCurrencyDepositAddressWithBlockchain
    ) = Entry[_Dict]("SynchDigitalCurrencyDepositAddressWithBlockchain", "private", "POST", {"cost": 1})
    private_post_requestfiatwithdrawal = privatePostRequestFiatWithdrawal = Entry[_Dict](
        "RequestFiatWithdrawal", "private", "POST", {"cost": 1}
    )
    private_post_withdrawfiatcurrency = privatePostWithdrawFiatCurrency = Entry[_Dict](
        "WithdrawFiatCurrency", "private", "POST", {"cost": 1}
    )
    private_post_withdrawdigitalcurrency = privatePostWithdrawDigitalCurrency = Entry[_Dict](
        "WithdrawDigitalCurrency", "private", "POST", {"cost": 1}
    )
    private_post_withdrawcrypto = privatePostWithdrawCrypto = Entry[_Dict](
        "WithdrawCrypto", "private", "POST", {"cost": 1}
    )
