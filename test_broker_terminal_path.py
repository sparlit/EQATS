import pytest
import os
import database
import connector
import config

def test_broker_terminal_path_db(tmp_path):
    test_db = str(tmp_path / "test_broker.db")
    orig_db = config.DB_PATH
    config.DB_PATH = test_db
    try:
        database.init_db()

        database.save_broker_credentials(
            server="TestServer",
            account_id="12345678",
            password="TestPassword",
            leverage="1:100",
            broker_name="Test Gateway",
            environment="Demo",
            terminal_path="C:\\Program Files\\MetaTrader 5\\terminal64.exe"
        )

        creds = database.get_broker_credentials()
        assert creds["server"] == "TestServer"
        assert creds["account_id"] == "12345678"
        assert creds["terminal_path"] == "C:\\Program Files\\MetaTrader 5\\terminal64.exe"

        brokers = database.get_all_brokers()
        assert len(brokers) == 1
        assert brokers[0]["terminal_path"] == "C:\\Program Files\\MetaTrader 5\\terminal64.exe"
    finally:
        config.DB_PATH = orig_db

def test_single_broker_enforcement(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_broker_single.db")
    orig_db = config.DB_PATH
    orig_single = config.SINGLE_BROKER_ONLY
    config.DB_PATH = test_db
    config.SINGLE_BROKER_ONLY = True

    try:
        database.init_db()
        database.save_broker_credentials(
            server="RealServer",
            account_id="888888",
            password="password",
            leverage="1:100",
            broker_name="Primary Broker",
            environment="Demo",
            terminal_path="/usr/bin/mt5"
        )

        # Test connector initialization
        mt5_conn = connector.MT5Connector()
        assert mt5_conn.terminal_path is None

        # Test explicitly provided terminal path
        mt5_custom = connector.MT5Connector(terminal_path="C:\\MT5\\terminal.exe")
        assert mt5_custom.terminal_path == "C:\\MT5\\terminal.exe"

    finally:
        config.DB_PATH = orig_db
        config.SINGLE_BROKER_ONLY = orig_single
