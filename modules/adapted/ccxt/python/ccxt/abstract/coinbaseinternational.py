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
    v1_public_get_assets = v1PublicGetAssets = Entry[_List]("assets", ["v1", "public"], "GET", {"cost": 1})
    v1_public_get_assets_assets = v1PublicGetAssetsAssets = Entry[_Dict](
        "assets/{assets}", ["v1", "public"], "GET", {"cost": 1}
    )
    v1_public_get_assets_asset_networks = v1PublicGetAssetsAssetNetworks = Entry[_List](
        "assets/{asset}/networks", ["v1", "public"], "GET", {"cost": 1}
    )
    v1_public_get_instruments = v1PublicGetInstruments = Entry[_List](
        "instruments", ["v1", "public"], "GET", {"cost": 1}
    )
    v1_public_get_instruments_instrument = v1PublicGetInstrumentsInstrument = Entry[_Dict](
        "instruments/{instrument}", ["v1", "public"], "GET", {"cost": 1}
    )
    v1_public_get_instruments_instrument_quote = v1PublicGetInstrumentsInstrumentQuote = Entry[_Dict](
        "instruments/{instrument}/quote", ["v1", "public"], "GET", {"cost": 1}
    )
    v1_public_get_instruments_instrument_funding = v1PublicGetInstrumentsInstrumentFunding = Entry[_Dict](
        "instruments/{instrument}/funding", ["v1", "public"], "GET", {"cost": 1}
    )
    v1_public_get_instruments_instrument_candles = v1PublicGetInstrumentsInstrumentCandles = Entry[_Dict](
        "instruments/{instrument}/candles", ["v1", "public"], "GET", {"cost": 1}
    )
    v1_private_get_orders = v1PrivateGetOrders = Entry[_Dict]("orders", ["v1", "private"], "GET", {"cost": 1})
    v1_private_get_orders_id = v1PrivateGetOrdersId = Entry[_Dict]("orders/{id}", ["v1", "private"], "GET", {"cost": 1})
    v1_private_get_portfolios = v1PrivateGetPortfolios = Entry[_List](
        "portfolios", ["v1", "private"], "GET", {"cost": 1}
    )
    v1_private_get_portfolios_portfolio = v1PrivateGetPortfoliosPortfolio = Entry[_Dict](
        "portfolios/{portfolio}", ["v1", "private"], "GET", {"cost": 1}
    )
    v1_private_get_portfolios_portfolio_detail = v1PrivateGetPortfoliosPortfolioDetail = Entry[_Dict](
        "portfolios/{portfolio}/detail", ["v1", "private"], "GET", {"cost": 1}
    )
    v1_private_get_portfolios_portfolio_summary = v1PrivateGetPortfoliosPortfolioSummary = Entry[_Dict](
        "portfolios/{portfolio}/summary", ["v1", "private"], "GET", {"cost": 1}
    )
    v1_private_get_portfolios_portfolio_balances = v1PrivateGetPortfoliosPortfolioBalances = Entry[_List](
        "portfolios/{portfolio}/balances", ["v1", "private"], "GET", {"cost": 1}
    )
    v1_private_get_portfolios_portfolio_balances_asset = v1PrivateGetPortfoliosPortfolioBalancesAsset = Entry[_Dict](
        "portfolios/{portfolio}/balances/{asset}", ["v1", "private"], "GET", {"cost": 1}
    )
    v1_private_get_portfolios_portfolio_positions = v1PrivateGetPortfoliosPortfolioPositions = Entry[_List](
        "portfolios/{portfolio}/positions", ["v1", "private"], "GET", {"cost": 1}
    )
    v1_private_get_portfolios_portfolio_positions_instrument = v1PrivateGetPortfoliosPortfolioPositionsInstrument = (
        Entry[_Dict]("portfolios/{portfolio}/positions/{instrument}", ["v1", "private"], "GET", {"cost": 1})
    )
    v1_private_get_portfolios_fills = v1PrivateGetPortfoliosFills = Entry[_Dict](
        "portfolios/fills", ["v1", "private"], "GET", {"cost": 1}
    )
    v1_private_get_portfolios_portfolio_fills = v1PrivateGetPortfoliosPortfolioFills = Entry[_Dict](
        "portfolios/{portfolio}/fills", ["v1", "private"], "GET", {"cost": 1}
    )
    v1_private_get_transfers = v1PrivateGetTransfers = Entry[_Dict]("transfers", ["v1", "private"], "GET", {"cost": 1})
    v1_private_get_transfers_transfer_uuid = v1PrivateGetTransfersTransferUuid = Entry[_Dict](
        "transfers/{transfer_uuid}", ["v1", "private"], "GET", {"cost": 1}
    )
    v1_private_post_orders = v1PrivatePostOrders = Entry[_Dict]("orders", ["v1", "private"], "POST", {"cost": 1})
    v1_private_post_portfolios = v1PrivatePostPortfolios = Entry[_Dict](
        "portfolios", ["v1", "private"], "POST", {"cost": 1}
    )
    v1_private_post_portfolios_margin = v1PrivatePostPortfoliosMargin = Entry[_Dict](
        "portfolios/margin", ["v1", "private"], "POST", {"cost": 1}
    )
    v1_private_post_portfolios_transfer = v1PrivatePostPortfoliosTransfer = Entry[_Dict](
        "portfolios/transfer", ["v1", "private"], "POST", {"cost": 1}
    )
    v1_private_post_transfers_withdraw = v1PrivatePostTransfersWithdraw = Entry[_Dict](
        "transfers/withdraw", ["v1", "private"], "POST", {"cost": 1}
    )
    v1_private_post_transfers_address = v1PrivatePostTransfersAddress = Entry[_Dict](
        "transfers/address", ["v1", "private"], "POST", {"cost": 1}
    )
    v1_private_post_transfers_create_counterparty_id = v1PrivatePostTransfersCreateCounterpartyId = Entry[_Dict](
        "transfers/create-counterparty-id", ["v1", "private"], "POST", {"cost": 1}
    )
    v1_private_post_transfers_validate_counterparty_id = v1PrivatePostTransfersValidateCounterpartyId = Entry[_Dict](
        "transfers/validate-counterparty-id", ["v1", "private"], "POST", {"cost": 1}
    )
    v1_private_post_transfers_withdraw_counterparty = v1PrivatePostTransfersWithdrawCounterparty = Entry[_Dict](
        "transfers/withdraw/counterparty", ["v1", "private"], "POST", {"cost": 1}
    )
    v1_private_put_orders_id = v1PrivatePutOrdersId = Entry[_Dict]("orders/{id}", ["v1", "private"], "PUT", {"cost": 1})
    v1_private_put_portfolios_portfolio = v1PrivatePutPortfoliosPortfolio = Entry[_Dict](
        "portfolios/{portfolio}", ["v1", "private"], "PUT", {"cost": 1}
    )
    v1_private_delete_orders = v1PrivateDeleteOrders = Entry[_List]("orders", ["v1", "private"], "DELETE", {"cost": 1})
    v1_private_delete_orders_id = v1PrivateDeleteOrdersId = Entry[_Dict](
        "orders/{id}", ["v1", "private"], "DELETE", {"cost": 1}
    )
