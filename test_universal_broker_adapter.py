import pytest
import config
import database
import connector
from institutional_integrations.universal_broker_adapter import UniversalBrokerGateway, detect_platform_environment

def test_platform_detection():
    env = detect_platform_environment()
    assert "os" in env
    assert "is_windows" in env
    assert "is_linux" in env
    assert "is_mac" in env
    assert "python_version" in env

def test_universal_broker_gateway_protocols():
    protocols = ["MT5", "FIX", "REST_WEBSOCKET", "CTRADER", "IBKR", "CCXT", "SIMULATOR"]
    for proto in protocols:
        gw = UniversalBrokerGateway(
            protocol=proto,
            broker_name=f"Test_{proto}",
            account_id="123456",
            server="TestServer"
        )
        assert gw.connect() is True
        assert gw.is_connected() is True
        info = gw.get_account_info()
        assert info["protocol"] == proto
        assert info["account_id"] == "123456"

        symbols = gw.fetch_symbols()
        assert len(symbols) >= 3

        order_res = gw.place_order("EURUSD", "BUY", 0.01)
        assert order_res["status"] == "SUCCESS"
        assert order_res["protocol"] == proto

        close_res = gw.close_order(order_res["ticket"])
        assert close_res["status"] == "SUCCESS"

def test_universal_connector_interface():
    conn = connector.UniversalConnector(protocol="FIX")
    assert conn.connect() is True
    assert conn.is_connected() is True

    info = conn.get_account_info()
    assert info["protocol"] == "FIX"

    ticket = conn.execute_order("EUR_USD", "BUY", 0.01, sl=1.0500, tp=1.1000)
    assert ticket is not None

    assert conn.modify_order(ticket, sl=1.0550, tp=1.1050) is True
    assert conn.close_order(ticket) is not None

def test_database_migration_v7_schema(tmp_path):
    test_db = str(tmp_path / "test_v7.db")
    orig_db = config.DB_PATH
    config.DB_PATH = test_db
    try:
        database.init_db()
        database.save_broker_credentials(
            server="MultiServer",
            account_id="777777",
            password="secret_password",
            leverage="1:200",
            broker_name="Multi Broker Gateway",
            environment="Demo",
            protocol_type="CTRADER",
            api_key="ctrader_api_key_123",
            rest_url="https://openapi.ctrader.com"
        )

        creds = database.get_broker_credentials()
        assert creds["protocol_type"] == "CTRADER"
        assert creds["api_key"] == "ctrader_api_key_123"
        assert creds["rest_url"] == "https://openapi.ctrader.com"
    finally:
        config.DB_PATH = orig_db
