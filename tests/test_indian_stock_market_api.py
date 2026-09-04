# codespell:ignore MIS,IST
"""
Unit Test Suite for 0xramm/Indian-Stock-Market-API Adaptation Module.
Verifies IndianStockMarketAPIClient lifecycle, market depth, option chain generation,
0.05 INR tick rounding, and microkernel plugin registry lookup.
"""

from typing import Any

from institutional_integrations.indian_stock_market_api import (
    MAGIC_NUMBER_INDIAN_API,
    IndianStockMarketAPIClient,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
    UnifiedIndianBrokerClientAdapter,
)


def test_indian_stock_market_api_client_lifecycle() -> None:
    client = IndianStockMarketAPIClient(api_key="test_key", is_sandbox=True)
    assert client.connect() is True
    assert client.is_connected() is True

    account = client.get_account_info()
    assert account["currency"] == "INR"
    assert account["magic_number"] == MAGIC_NUMBER_INDIAN_API

    price = client.get_current_price("RELIANCE", "NSE")
    assert price["last"] > 0
    assert round(price["last"] * 20) == price["last"] * 20  # 0.05 INR tick multiple

    depth = client.fetch_market_depth("INFY", "NSE")
    assert len(depth["bids"]) == 5
    assert len(depth["asks"]) == 5

    chain = client.fetch_option_chain("NIFTY")
    assert len(chain) == 11
    assert "call_price" in chain[0]

    req = SEBIOrderRequest(
        symbol="SBIN",
        order_type="BUY",
        quantity=10,
        price=520.12,
        product="MIS",
        exchange="NSE",
    )
    res = client.execute_order(req)
    assert res.success is True
    assert res.price == 520.10
    assert res.ticket.startswith("INAPI_")

    assert client.disconnect() is True


def test_indian_stock_market_api_microkernel_registry() -> None:
    cls = IndianBrokerPluginRegistry.get_adapter_class("INDIAN_STOCK_MARKET_API")
    assert cls is IndianStockMarketAPIClient

    adapter = UnifiedIndianBrokerClientAdapter(broker_name="INDIAN_STOCK_MARKET_API", api_key="key", is_sandbox=True)
    assert adapter.login() is True
    res = adapter.place_order(symbol="TCS", side="BUY", quantity=5, price=3800.18, product="CNC")
    assert res["success"] is True
    assert res["price"] == 3800.20
