# codespell:ignore MIS,IST
"""
Unit Test Suite for aeron7/nsepython Adaptation Module.
Verifies NSEPythonClient equity quotes, index constituents, option chain parsing,
Bhavcopy parser, 0.05 INR tick rounding, and microkernel plugin registry lookup.
"""

from typing import Any

from institutional_integrations.nsepython_client import (
    MAGIC_NUMBER_NSEPYTHON,
    NSEPythonClient,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
    UnifiedIndianBrokerClientAdapter,
)


def test_nsepython_client_equity_quote_and_constituents() -> None:
    client = NSEPythonClient(api_key="key", is_sandbox=True)
    assert client.connect() is True
    assert client.is_connected() is True

    quote = client.fetch_equity_quote("RELIANCE")
    assert quote["symbol"] == "RELIANCE"
    assert quote["last_price"] > 0
    assert round(quote["last_price"] * 20) == quote["last_price"] * 20  # 0.05 INR tick

    constituents = client.fetch_index_constituents("NIFTY 50")
    assert len(constituents) == 5
    assert constituents[0]["symbol"] == "RELIANCE"

    chain = client.fetch_option_chain_data("NIFTY")
    assert len(chain["records"]) == 11
    assert "CE" in chain["records"][0]

    bhav = client.fetch_eod_bhavcopy()
    assert len(bhav) == 2
    assert bhav[0]["symbol"] == "RELIANCE"


def test_nsepython_client_microkernel_registry() -> None:
    cls = IndianBrokerPluginRegistry.get_adapter_class("NSEPYTHON")
    assert cls is NSEPythonClient

    adapter = UnifiedIndianBrokerClientAdapter(broker_name="NSEPYTHON", api_key="key", is_sandbox=True)
    assert adapter.login() is True
    res = adapter.place_order(symbol="INFY", side="BUY", quantity=10, price=1820.14, product="CNC")
    assert res["success"] is True
    assert res["price"] == 1820.15
    assert res["ticket"].startswith("NSEPY_")
