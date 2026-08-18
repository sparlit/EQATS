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
        raw_symbols = conn.fetch_all_symbols()
        self.assertTrue(len(raw_symbols) > 0)
        symbol_names = [s["symbol"] for s in raw_symbols]
        self.assertIn("EURUSD", symbol_names)

        count = conn.fetch_and_register_broker_symbols()
        self.assertTrue(count >= 6)

        mappings = database.get_all_symbol_mappings("SIMULATOR_BROKER")
        self.assertTrue(len(mappings) >= 6)

if __name__ == "__main__":
    unittest.main()
