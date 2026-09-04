"""
Comprehensive Unit & Integration Test Suite for SEBI Broker Adapters and Indian Stock Market Support.
Verifies Zerodha Kite Connect, DhanHQ, UniversalBrokerGateway order routes, Indian product tags (MIS, CNC, NRML),
data ingestion, database schema persistence, and ensures zero breakage for Forex/Crypto execution routes.
"""

import os
import sqlite3
import time

# codespell:ignore MIS,IST
from typing import Any

import pytest

import database
from connector import SimulatorConnector, UniversalConnector
from institutional_integrations.extended_market_connectors import ExtendedDataConnectors
from institutional_integrations.openalgo_engine import OpenAlgoIndianExchangeRouter
from institutional_integrations.sebi_broker_adapter import (
    VALID_INDIAN_EXCHANGES,
    VALID_INDIAN_PRODUCT_TAGS,
    DhanHQAdapter,
    KiteConnectAdapter,
    SEBIBrokerAdapter,
    SEBIOrderRequest,
    SEBIOrderResponse,
    validate_indian_product_tag,
)
from institutional_integrations.universal_broker_adapter import UniversalBrokerGateway


def test_product_tag_validation() -> None:
    assert validate_indian_product_tag("MIS") == "MIS"
    assert validate_indian_product_tag("cnc") == "CNC"
    assert validate_indian_product_tag("nrml") == "NRML"
    assert validate_indian_product_tag(None) == "CNC"
    assert validate_indian_product_tag("INVALID_TAG") == "CNC"


def test_kite_connect_adapter_lifecycle() -> None:
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
    req_mis = SEBIOrderRequest(symbol="RELIANCE", order_type="BUY", quantity=10, product="MIS", exchange="NSE")
    res_mis = adapter.execute_order(req_mis)
    assert res_mis.success is True
    assert res_mis.product == "MIS"
    assert res_mis.ticket.startswith("KITE_")
    req_cnc = SEBIOrderRequest(symbol="INFY", order_type="BUY", quantity=5, product="CNC", exchange="NSE")
    res_cnc = adapter.execute_order(req_cnc)
    assert res_cnc.success is True
    assert res_cnc.product == "CNC"
    req_nrml = SEBIOrderRequest(symbol="NIFTY24MARFUT", order_type="BUY", quantity=50, product="NRML", exchange="NFO")
    res_nrml = adapter.execute_order(req_nrml)
    assert res_nrml.success is True
    assert res_nrml.product == "NRML"
    open_orders = adapter.get_open_orders()
    assert len(open_orders) == 3
    close_res = adapter.close_order(res_mis.ticket, "RELIANCE", "NSE", product="MIS")
    assert close_res.success is True
    assert close_res.status == "CLOSED"
    assert adapter.disconnect() is True


def test_dhan_hq_adapter_lifecycle() -> None:
    adapter = DhanHQAdapter(api_key="dhan_key", client_id="dhan_client", access_token="token", is_sandbox=True)
    assert adapter.connect() is True
    assert adapter.is_connected() is True
    account = adapter.get_account_info()
    assert account["currency"] == "INR"
    quote = adapter.get_current_price("TCS", "NSE")
    assert quote["last"] > 0
    req = SEBIOrderRequest(symbol="TCS", order_type="BUY", quantity=15, product="MIS", exchange="NSE")
    res = adapter.execute_order(req)
    assert res.success is True
    assert res.product == "MIS"
    assert res.ticket.startswith("DHAN_")
    assert adapter.disconnect() is True


def test_universal_broker_gateway_sebi_protocols() -> None:
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


def test_forex_crypto_order_routes_unaffected() -> None:
    gw_sim = UniversalBrokerGateway(protocol="SIMULATOR")
    assert gw_sim.connect() is True
    res_forex = gw_sim.execute_order("EURUSD", "BUY", 0.1, 1.08, 1.1)
    assert res_forex["success"] is True
    res_crypto = gw_sim.execute_order("BTCUSD", "BUY", 0.05, 60000.0, 65000.0)
    assert res_crypto["success"] is True
    conn = UniversalConnector(protocol="SIMULATOR")
    assert conn.connect() is True
    exec_res = conn.execute_order("GBPUSD", "SELL", 0.2, 1.27, 1.25)
    assert exec_res["success"] is True


def test_database_trade_logging_with_product() -> None:
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


def test_extended_connectors_and_openalgo_router() -> None:
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
        symbol="TCS", action="BUY", quantity=25, price=3950.0, product="NRML", exchange="NSE"
    )
    assert payload["product"] == "NRML"
    assert payload["symbol"] == "TCS"
    assert payload["exchange"] == "NSE"


def test_indian_instrument_scheduler() -> None:
    from institutional_integrations.indian_instrument_scheduler import (
        IndianInstrumentScheduler,
        global_indian_scheduler,
    )

    scheduler = IndianInstrumentScheduler(data_dir="data_test_temp")
    token_sbin = scheduler.get_instrument_token("NSE:SBIN")
    assert token_sbin == 779521
    assert scheduler.get_symbol_from_token(token_sbin) == "NSE:SBIN"
    token_rel = scheduler.get_instrument_token("RELIANCE")
    assert token_rel == 738561
    sample_kite_csv = "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange\n123456,123,TESTSTOCK,Test Stock,100.0,,,0.05,1,EQ,NSE-EQ,NSE\n654321,456,TESTFUT,Test Future,500.0,2024-03-28,0,0.05,50,FUT,NFO-FUT,NFO\n"
    parsed_map = scheduler.parse_kite_instruments_csv(sample_kite_csv)
    assert parsed_map["NSE:TESTSTOCK"] == 123456
    assert parsed_map["NFO:TESTFUT"] == 654321
    sample_dhan_csv = "SEM_SMST_SECURITY_ID,SEM_EXCHANGE_ID,SEM_TRADING_SYMBOL\n998877,NSE,DHANSTOCK\n"
    parsed_dhan = scheduler.parse_dhan_instruments_csv(sample_dhan_csv)
    assert parsed_dhan["NSE:DHANSTOCK"] == 998877
    delay = scheduler.calculate_seconds_until_target_time_ist(8, 45)
    assert delay > 0 and delay <= 86400
    scheduler.start_daily_scheduler(target_time_ist="08:45")
    assert scheduler._running is True
    scheduler.stop_daily_scheduler()
    assert scheduler._running is False
    if os.path.exists("data_test_temp/indian_instruments.json"):
        os.remove("data_test_temp/indian_instruments.json")
    if os.path.exists("data_test_temp"):
        os.rmdir("data_test_temp")


def test_indian_market_state_machine_and_tick_size() -> None:
    from datetime import datetime

    from institutional_integrations.indian_market_state_machine import (
        IST_TIMEZONE,
        IndianMarketState,
        IndianMarketStateMachine,
        round_to_indian_tick_size,
    )

    assert round_to_indian_tick_size(2850.12) == 2850.1
    assert round_to_indian_tick_size(2850.13) == 2850.15
    assert round_to_indian_tick_size(2850.18) == 2850.2
    assert round_to_indian_tick_size(500.04) == 500.05
    dt_sunday = datetime(2026, 8, 30, 11, 0, tzinfo=IST_TIMEZONE)
    assert IndianMarketStateMachine.get_market_state(dt_sunday) == IndianMarketState.CLOSED
    dt_mon_pre = datetime(2026, 8, 31, 9, 5, tzinfo=IST_TIMEZONE)
    assert IndianMarketStateMachine.get_market_state(dt_mon_pre) == IndianMarketState.PRE_MARKET
    dt_mon_open = datetime(2026, 8, 31, 10, 30, tzinfo=IST_TIMEZONE)
    assert IndianMarketStateMachine.get_market_state(dt_mon_open) == IndianMarketState.OPEN
    assert IndianMarketStateMachine.is_mis_entry_allowed(dt_mon_open) is True
    dt_mon_cutoff = datetime(2026, 8, 31, 15, 15, tzinfo=IST_TIMEZONE)
    assert IndianMarketStateMachine.get_market_state(dt_mon_cutoff) == IndianMarketState.INTRADAY_CUTOFF
    assert IndianMarketStateMachine.is_mis_entry_allowed(dt_mon_cutoff) is False
    assert IndianMarketStateMachine.should_trigger_mis_squareoff(dt_mon_cutoff) is True
    allowed, reason, rounded_price = IndianMarketStateMachine.validate_order_execution(
        symbol="NSE:SBIN", order_type="BUY", product="MIS", price=520.13, dt_ist=dt_mon_cutoff
    )
    assert allowed is False
    assert "MIS Intraday orders blocked" in reason
    assert rounded_price == 520.15
    allowed_cnc, reason_cnc, price_cnc = IndianMarketStateMachine.validate_order_execution(
        symbol="NSE:SBIN", order_type="BUY", product="CNC", price=520.13, dt_ist=dt_mon_open
    )
    assert allowed_cnc is True
    assert price_cnc == 520.15


def test_indian_broker_plugin_registry_and_microkernel() -> None:
    from institutional_integrations.sebi_broker_adapter import (
        IndianBrokerPluginRegistry,
        KiteConnectAdapter,
        OpenAlgoFenixAdapter,
    )

    registered = IndianBrokerPluginRegistry.list_registered_brokers()
    assert "ZERODHA" in registered
    assert "DHAN" in registered
    assert "FENIX" in registered
    assert IndianBrokerPluginRegistry.is_enabled("FENIX") is True
    assert IndianBrokerPluginRegistry.get_adapter_class("FENIX") is OpenAlgoFenixAdapter

    # Test dynamic disable and re-enable
    IndianBrokerPluginRegistry.disable("FENIX")
    assert IndianBrokerPluginRegistry.is_enabled("FENIX") is False
    assert IndianBrokerPluginRegistry.get_adapter_class("FENIX") is None
    IndianBrokerPluginRegistry.enable("FENIX")
    assert IndianBrokerPluginRegistry.is_enabled("FENIX") is True


def test_unified_indian_broker_client_adapter_all_brokers() -> None:
    from institutional_integrations.sebi_broker_adapter import UnifiedIndianBrokerClientAdapter

    brokers = [
        "ZERODHA",
        "DHAN",
        "ANGELONE",
        "KOTAK",
        "UPSTOX",
        "ICICI",
        "5PAISA",
        "IIFL",
        "MOTILAL",
        "FENIX",
        "OPENALGO",
    ]
    for broker in brokers:
        client = UnifiedIndianBrokerClientAdapter(
            broker_name=broker, api_key=f"test_key_{broker}", client_id=f"client_{broker}", is_sandbox=True
        )
        assert client.login() is True
        token = client.generate_session_token("REQ_TOKEN_123")
        assert token == "REQ_TOKEN_123"
        res = client.place_order(symbol="SBIN", side="BUY", quantity=10, price=520.12, product="MIS", exchange="NSE")
        assert res["success"] is True
        assert res["product"] == "MIS"
        assert res["price"] == 520.1
        assert res["ticket"] != ""
        ticket = res["ticket"]
        mod_res = client.modify_order(ticket=ticket, price=525.18, sl=515.0, tp=535.0)
        assert mod_res["success"] is True
        assert mod_res["price"] == 525.2
        cancel_res = client.cancel_order(ticket=ticket, symbol="SBIN", exchange="NSE")
        assert cancel_res["success"] is True
        assert cancel_res["status"] == "CANCELLED"


def test_universal_broker_gateway_all_indian_brokers() -> None:
    from institutional_integrations.universal_broker_adapter import UniversalBrokerGateway

    indian_protocols = ["ANGELONE", "KOTAK", "UPSTOX", "ICICI", "FIVEPAISA", "IIFL", "MOTILAL"]
    for proto in indian_protocols:
        gw = UniversalBrokerGateway(protocol=proto, broker_config={"is_sandbox": True})
        assert gw.connect() is True
        assert gw.is_connected() is True
        res = gw.execute_order("TCS", "BUY", 5.0, 0.0, 0.0, product="CNC", exchange="NSE")
        assert res["success"] is True
        assert res["protocol"] == proto
        assert res["product"] == "CNC"


def test_database_instrument_token_caching_and_scheduler() -> None:
    import database
    from institutional_integrations.extended_market_connectors import ExtendedDataConnectors
    from institutional_integrations.indian_instrument_scheduler import global_indian_scheduler

    database.init_db()
    saved_count = database.save_instrument_tokens_to_db({"NSE:TATASTEEL": 895745, "NSE:WIPRO": 378753})
    assert saved_count == 2
    token_tatasteel = database.get_instrument_token_from_db("NSE:TATASTEEL")
    assert token_tatasteel == 895745
    token_wipro = database.get_instrument_token_from_db("WIPRO")
    assert token_wipro == 378753
    sym_tatasteel = database.get_symbol_from_db_token(895745)
    assert sym_tatasteel == "NSE:TATASTEEL"
    quote = ExtendedDataConnectors.fetch_indian_equity_quote("NSE:TATASTEEL")
    assert quote["instrument_token"] == 895745
    sched_token = global_indian_scheduler.get_instrument_token("NSE:WIPRO")
    assert sched_token == 378753


def test_intraday_mis_cutoff_and_auto_squareoff() -> Any:
    from datetime import datetime

    from institutional_integrations.indian_market_state_machine import IST_TIMEZONE, IndianMarketStateMachine

    dt_cutoff = datetime(2026, 8, 31, 15, 15, tzinfo=IST_TIMEZONE)
    dt_normal = datetime(2026, 8, 31, 10, 30, tzinfo=IST_TIMEZONE)
    open_orders = [
        {"ticket": "ORD_1", "symbol": "NSE:SBIN", "product": "MIS", "status": "OPEN", "exchange": "NSE"},
        {"ticket": "ORD_2", "symbol": "NSE:RELIANCE", "product": "MIS", "status": "PENDING", "exchange": "NSE"},
        {"ticket": "ORD_3", "symbol": "NSE:INFY", "product": "CNC", "status": "OPEN", "exchange": "NSE"},
    ]
    cancelled_list = []
    closed_list = []

    def mock_close(ticket: Any, symbol: Any, exchange: Any, product: Any) -> Any:
        closed_list.append(ticket)
        return {"success": True, "ticket": ticket, "status": "CLOSED"}

    def mock_cancel(ticket: Any) -> Any:
        cancelled_list.append(ticket)
        return True

    res_normal = IndianMarketStateMachine.enforce_intraday_mis_cutoff_and_squareoff(
        open_orders=open_orders, close_order_func=mock_close, cancel_order_func=mock_cancel, dt_ist=dt_normal
    )
    assert res_normal["squareoff_triggered"] is False
    assert res_normal["entries_frozen"] is False
    assert len(cancelled_list) == 0
    assert len(closed_list) == 0
    res_cutoff = IndianMarketStateMachine.enforce_intraday_mis_cutoff_and_squareoff(
        open_orders=open_orders, close_order_func=mock_close, cancel_order_func=mock_cancel, dt_ist=dt_cutoff
    )
    assert res_cutoff["squareoff_triggered"] is True
    assert res_cutoff["entries_frozen"] is True
    assert res_cutoff["cancelled_orders_count"] == 1
    assert res_cutoff["closed_positions_count"] == 1
    assert "ORD_2" in cancelled_list
    assert "ORD_1" in closed_list
    assert "ORD_3" not in closed_list


def test_tick_size_and_integer_lot_position_sizing() -> None:
    from institutional_integrations.indian_market_state_machine import round_to_indian_tick_size
    from institutional_integrations.sebi_broker_adapter import (
        UnifiedIndianBrokerClientAdapter,
        round_to_indian_quantity,
    )

    assert round_to_indian_quantity(10.75) == 11
    assert round_to_indian_quantity(0.4) == 1
    assert round_to_indian_quantity(100.0) == 100
    assert round_to_indian_quantity(0) == 1
    entry_price = round_to_indian_tick_size(2850.12)
    sl_price = round_to_indian_tick_size(2800.18)
    tp_price = round_to_indian_tick_size(2950.03)
    assert entry_price == 2850.1
    assert sl_price == 2800.2
    assert tp_price == 2950.05
    client = UnifiedIndianBrokerClientAdapter(broker_name="ZERODHA", is_sandbox=True)
    res = client.place_order(
        symbol="SBIN", side="BUY", quantity=25.8, price=520.14, sl=510.19, tp=530.01, product="MIS"
    )
    assert res["success"] is True
    assert res["price"] == 520.15
