"""
Unit tests for Multi-Broker Registration and Symbol Auto-Fetching.
"""

import unittest
import os
import database
import config
from connector import SimulatorConnector

class TestBrokerAndSymbolFetch(unittest.TestCase):

    def setUp(self):
        os.environ["ENCRYPTION_KEY"] = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        self.test_db = "test_broker_fetch.db"
        self.old_db = getattr(config, "DB_PATH", "forex_scalper.db")
        config.DB_PATH = self.test_db
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        database.init_db()

    def tearDown(self):
        config.DB_PATH = self.old_db
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    def test_multi_broker_registration_crud(self):
        # 1. Add broker profile
        database.add_broker_account(
            broker_name="OANDA Global",
            server="OANDA-Demo-1",
            account_id="101-001-123456",
            password="secret_password",
            leverage="1:50",
            environment="Demo",
            is_active=1
        )

        brokers = database.get_all_brokers()
        self.assertEqual(len(brokers), 1)
        self.assertEqual(brokers[0]["broker_name"], "OANDA Global")
        self.assertEqual(brokers[0]["password"], "secret_password")

        # 2. Add second broker profile and set active
        database.add_broker_account(
            broker_name="IC Markets Raw",
            server="ICMarkets-Live",
            account_id="88991122",
            password="raw_password",
            leverage="1:500",
            environment="ECN",
            is_active=1
        )

        brokers_after = database.get_all_brokers()
        self.assertEqual(len(brokers_after), 2)

    def test_connector_symbol_auto_fetch(self):
        conn = SimulatorConnector(initial_balance=10000.0)
        symbols = conn.fetch_all_symbols()
        self.assertTrue(len(symbols) > 0)
        self.assertIn("EURUSD", symbols)

        count = conn.fetch_and_register_broker_symbols()
        self.assertTrue(count >= 6)

        mappings = database.get_all_symbol_mappings("SIMULATOR_BROKER")
        self.assertTrue(len(mappings) >= 6)

    def test_rest_broker_connector(self):
        from connector import RESTBrokerConnector
        rest_conn = RESTBrokerConnector(api_url="https://api.oanda.com", account_id="OANDA_TEST")
        self.assertTrue(rest_conn.connect())
        self.assertTrue(rest_conn.is_connected())

        info = rest_conn.get_account_info()
        self.assertEqual(info["balance"], 10000.0)

        price = rest_conn.get_current_price("EURUSD")
        self.assertIn("bid", price)
        self.assertIn("ask", price)

        history = rest_conn.get_history("EURUSD", 10)
        self.assertEqual(len(history), 10)

        order_res = rest_conn.execute_order("EURUSD", "BUY", 0.1, 1.0800, 1.1000)
        self.assertTrue(order_res["success"])
        ticket = order_res["ticket"]

        orders = rest_conn.get_open_orders()
        self.assertEqual(len(orders), 1)

        self.assertTrue(rest_conn.modify_order(ticket, 1.0850, 1.1050))

        close_res = rest_conn.close_order(ticket)
        self.assertTrue(close_res["success"])
        self.assertEqual(len(rest_conn.get_open_orders()), 0)

        rest_conn.disconnect()
        self.assertFalse(rest_conn.is_connected())

    def test_ccxt_connector(self):
        from connector import CCXTConnector
        ccxt_conn = CCXTConnector(exchange_id="binance")
        self.assertTrue(ccxt_conn.connect())
        self.assertTrue(ccxt_conn.is_connected())

        info = ccxt_conn.get_account_info()
        self.assertEqual(info["currency"], "USDT")

        price = ccxt_conn.get_current_price("BTCUSD")
        self.assertIn("bid", price)

        history = ccxt_conn.get_history("BTCUSD", 5)
        self.assertEqual(len(history), 5)

        order_res = ccxt_conn.execute_order("BTCUSD", "BUY", 0.01)
        self.assertTrue(order_res["success"])
        ticket = order_res["ticket"]

        close_res = ccxt_conn.close_order(ticket)
        self.assertTrue(close_res["success"])

        ccxt_conn.disconnect()

    def test_fix_connector(self):
        from connector import FIXConnector
        fix_conn = FIXConnector(sender_comp_id="EQATS_TEST", target_comp_id="LP_TEST")
        self.assertTrue(fix_conn.connect())
        self.assertTrue(fix_conn.is_connected())

        info = fix_conn.get_account_info()
        self.assertEqual(info["balance"], 100000.0)

        order_res = fix_conn.execute_order("XAUUSD", "BUY", 1.0)
        self.assertTrue(order_res["success"])

        symbols = fix_conn.fetch_all_symbols()
        self.assertIn("XAUUSD", symbols)

        fix_conn.disconnect()

    def test_mt4_gateway_connector(self):
        from connector import MT4GatewayConnector
        gw_conn = MT4GatewayConnector(gateway_url="http://localhost:8080")
        self.assertTrue(gw_conn.connect())
        self.assertTrue(gw_conn.is_connected())

        info = gw_conn.get_account_info()
        self.assertEqual(info["balance"], 10000.0)

        order_res = gw_conn.execute_order("GBPUSD", "SELL", 0.05)
        self.assertTrue(order_res["success"])

        gw_conn.disconnect()

    def test_connector_factory(self):
        from connector import ConnectorFactory, SimulatorConnector, RESTBrokerConnector, CCXTConnector, FIXConnector, MT4GatewayConnector, MT5Connector

        c_sim = ConnectorFactory.get_connector("SIMULATOR")
        self.assertIsInstance(c_sim, SimulatorConnector)

        c_rest = ConnectorFactory.get_connector("REST")
        self.assertIsInstance(c_rest, RESTBrokerConnector)

        c_ccxt = ConnectorFactory.get_connector("CCXT")
        self.assertIsInstance(c_ccxt, CCXTConnector)

        c_fix = ConnectorFactory.get_connector("FIX")
        self.assertIsInstance(c_fix, FIXConnector)

        c_gw = ConnectorFactory.get_connector("MT4_GATEWAY")
        self.assertIsInstance(c_gw, MT4GatewayConnector)

        c_mt5 = ConnectorFactory.get_connector("MT5")
        # On Linux, MT5Connector falls back to MT4GatewayConnector gracefully
        self.assertTrue(isinstance(c_mt5, (MT5Connector, MT4GatewayConnector)))

if __name__ == "__main__":
    unittest.main()
