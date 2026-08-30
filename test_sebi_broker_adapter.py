"""
Comprehensive Unit & Integration Test Suite for SEBI Broker Adapters and Indian Stock Market Support.
Verifies Zerodha Kite Connect, DhanHQ, UniversalBrokerGateway order routes, Indian product tags (MIS, CNC, NRML),
data ingestion, database schema persistence, and ensures zero breakage for Forex/Crypto execution routes.
"""

import os
import time
import pytest
import sqlite3

from institutional_integrations.sebi_broker_adapter import (
    SEBIBrokerAdapter,
    KiteConnectAdapter,
    DhanHQAdapter,
    SEBIOrderRequest,
    SEBIOrderResponse,
    validate_indian_product_tag,
    VALID_INDIAN_PRODUCT_TAGS,
    VALID_INDIAN_EXCHANGES,
)
from institutional_integrations.universal_broker_adapter import UniversalBrokerGateway
from connector import UniversalConnector, SimulatorConnector
from institutional_integrations.extended_market_connectors import ExtendedDataConnectors
from institutional_integrations.openalgo_engine import OpenAlgoIndianExchangeRouter
import database


def test_product_tag_validation():
    assert validate_indian_product_tag("MIS") == "MIS"
    assert validate_indian_product_tag("cnc") == "CNC"
    assert validate_indian_product_tag("nrml") == "NRML"
    assert validate_indian_product_tag(None) == "CNC"
    assert validate_indian_product_tag("INVALID_TAG") == "CNC"


def test_kite_connect_adapter_lifecycle():
    adapter = KiteConnectAdapter(api_key="test_key", access_token="test_token", is_sandbox=True)
    assert adapter.connect() is True
    assert adapter.is_connected() is True

    account = adapter.get_account_info()
    assert account["currency"] == "INR"
    assert account["balance"] > 0

    quote = adapter.get_current_price("RELIANCE", "NSE")
    assert quote["last"] > 0

    history = adapter.get_history("RELIANCE", exchange="NSE", count=10)
    assert len(history) == 10
    assert "close" in history[0]

    # Test MIS Order
    req_mis = SEBIOrderRequest(
        symbol="RELIANCE",
        order_type="BUY",
        quantity=10,
        product="MIS",
        exchange="NSE",
    )
    res_mis = adapter.execute_order(req_mis)
    assert res_mis.success is True
    assert res_mis.product == "MIS"
    assert res_mis.ticket.startswith("KITE_")

    # Test CNC Order
    req_cnc = SEBIOrderRequest(
        symbol="INFY",
        order_type="BUY",
        quantity=5,
        product="CNC",
        exchange="NSE",
    )
    res_cnc = adapter.execute_order(req_cnc)
    assert res_cnc.success is True
    assert res_cnc.product == "CNC"

    # Test NRML Order
    req_nrml = SEBIOrderRequest(
        symbol="NIFTY24MARFUT",
        order_type="BUY",
        quantity=50,
        product="NRML",
        exchange="NFO",
    )
    res_nrml = adapter.execute_order(req_nrml)
    assert res_nrml.success is True
    assert res_nrml.product == "NRML"

    open_orders = adapter.get_open_orders()
    assert len(open_orders) == 3

    close_res = adapter.close_order(res_mis.ticket, "RELIANCE", "NSE", product="MIS")
    assert close_res.success is True
    assert close_res.status == "CLOSED"

    assert adapter.disconnect() is True


def test_dhan_hq_adapter_lifecycle():
    adapter = DhanHQAdapter(api_key="dhan_key", client_id="dhan_client", access_token="token", is_sandbox=True)
    assert adapter.connect() is True
    assert adapter.is_connected() is True

    account = adapter.get_account_info()
    assert account["currency"] == "INR"

    quote = adapter.get_current_price("TCS", "NSE")
    assert quote["last"] > 0

    req = SEBIOrderRequest(
        symbol="TCS",
        order_type="BUY",
        quantity=15,
        product="MIS",
        exchange="NSE",
    )
    res = adapter.execute_order(req)
    assert res.success is True
    assert res.product == "MIS"
    assert res.ticket.startswith("DHAN_")

    assert adapter.disconnect() is True


def test_universal_broker_gateway_sebi_protocols():
    gw_kite = UniversalBrokerGateway(protocol="KITE", broker_config={"is_sandbox": True})
    assert gw_kite.connect() is True
    assert gw_kite.is_connected() is True

    res = gw_kite.execute_order("SBIN", "BUY", 10.0, 0.0, 0.0, product="MIS", exchange="NSE")
    assert res["success"] is True
    assert res["product"] == "MIS"
    assert res["protocol"] == "KITE"

    gw_dhan = UniversalBrokerGateway(protocol="DHAN", broker_config={"is_sandbox": True})
    assert gw_dhan.connect() is True

    res_dhan = gw_dhan.execute_order("HDFCBANK", "SELL", 5.0, 0.0, 0.0, product="CNC", exchange="NSE")
    assert res_dhan["success"] is True
    assert res_dhan["product"] == "CNC"
    assert res_dhan["protocol"] == "DHAN"


def test_forex_crypto_order_routes_unaffected():
    gw_sim = UniversalBrokerGateway(protocol="SIMULATOR")
    assert gw_sim.connect() is True

    # Standard Forex order
    res_forex = gw_sim.execute_order("EURUSD", "BUY", 0.1, 1.0800, 1.1000)
    assert res_forex["success"] is True

    # Standard Crypto order
    res_crypto = gw_sim.execute_order("BTCUSD", "BUY", 0.05, 60000.0, 65000.0)
    assert res_crypto["success"] is True

    # UniversalConnector with Simulator
    conn = UniversalConnector(protocol="SIMULATOR")
    assert conn.connect() is True
    exec_res = conn.execute_order("GBPUSD", "SELL", 0.2, 1.2700, 1.2500)
    assert exec_res["success"] is True


def test_database_trade_logging_with_product():
    database.init_db()
    ticket = f"TEST_SEBI_{int(time.time() * 1000)}"
    success = database.log_trade_open(
        ticket=ticket,
        symbol="NSE:RELIANCE",
        direction="BUY",
        open_price=2850.0,
        sl=2800.0,
        tp=2950.0,
        lot_size=10.0,
        strategy="IndianScalp",
        method="MIS_Intraday",
        product="MIS",
    )
    assert success is True

    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, product FROM trades WHERE ticket = ?", (ticket,))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "NSE:RELIANCE"
        assert row[1] == "MIS"


def test_extended_connectors_and_openalgo_router():
    quote = ExtendedDataConnectors.fetch_indian_equity_quote("NSE:RELIANCE")
    assert quote["symbol"] == "RELIANCE"
    assert quote["exchange"] == "NSE"
    assert quote["last"] > 0

    depth = ExtendedDataConnectors.fetch_indian_market_depth("NSE:SBIN")
    assert len(depth["bids"]) == 5
    assert len(depth["asks"]) == 5

    bars = ExtendedDataConnectors.fetch_indian_market_ohlcv("NSE:INFY", count=20)
    assert len(bars) == 20

    payload = OpenAlgoIndianExchangeRouter.format_order_payload(
        symbol="TCS",
        action="BUY",
        quantity=25,
        price=3950.0,
        product="NRML",
        exchange="NSE",
    )
    assert payload["product"] == "NRML"
    assert payload["symbol"] == "TCS"
    assert payload["exchange"] == "NSE"
