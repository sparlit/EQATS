"""
Unit Tests for Master Symbology, Symbol Mapping Database, and Translation Adapters.
"""

import unittest
import os
import database
import config
from symbol_mapper import SymbolMapper, get_symbol_mapper

class TestSymbolMapping(unittest.TestCase):

    def setUp(self):
        self.test_db = "test_symbology.db"
        self.old_db = getattr(config, "DB_PATH", "forex_scalper.db")
        config.DB_PATH = self.test_db
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        database.init_db()
        self.mapper = SymbolMapper(default_broker_id="IC_MARKETS")

    def tearDown(self):
        config.DB_PATH = self.old_db
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    def test_regex_infer_master_symbol(self):
        # 1. Standard Forex pairs with raw/pro suffixes
        master, pip, contract = self.mapper.infer_master_symbol("EURUSD.raw")
        self.assertEqual(master, "EUR_USD")
        self.assertEqual(pip, 0.0001)
        self.assertEqual(contract, 100000.0)

        # 2. JPY pairs
        master, pip, contract = self.mapper.infer_master_symbol("USDJPY.pro")
        self.assertEqual(master, "USD_JPY")
        self.assertEqual(pip, 0.01)

        # 3. Commodity aliases (GOLD -> XAU_USD)
        master, pip, contract = self.mapper.infer_master_symbol("GOLD")
        self.assertEqual(master, "XAU_USD")
        self.assertEqual(pip, 0.01)
        self.assertEqual(contract, 100.0)

        # 4. IG / Complex prefix symbols
        master, pip, contract = self.mapper.infer_master_symbol("CS.D.EURUSD.TODAY.IP")
        self.assertEqual(master, "EUR_USD")

        # 5. Micro contracts
        master, pip, contract = self.mapper.infer_master_symbol("EURUSD.micro")
        self.assertEqual(master, "EUR_USD")
        self.assertEqual(contract, 1000.0)

    def test_database_mapping_crud(self):
        # Add mapping
        success = database.add_symbol_mapping("EUR_USD", "IC_MARKETS", "EURUSD.raw", pip_size=0.0001, contract_size=100000.0)
        self.assertTrue(success)

        # Retrieve mapped broker symbol
        broker_sym = database.get_broker_symbol("EUR_USD", "IC_MARKETS")
        self.assertEqual(broker_sym, "EURUSD.raw")

        # Retrieve mapped internal symbol
        internal_sym = database.get_internal_symbol("EURUSD.raw", "IC_MARKETS")
        self.assertEqual(internal_sym, "EUR_USD")

        # Get full mapping dict
        mapping = database.get_symbol_mapping("EUR_USD", "IC_MARKETS")
        self.assertIsNotNone(mapping)
        self.assertEqual(mapping["broker_symbol"], "EURUSD.raw")
        self.assertEqual(mapping["contract_size"], 100000.0)

    def test_symbol_mapper_translation_adapter(self):
        # Explicit mapping
        database.add_symbol_mapping("XAU_USD", "FOREX_COM", "GOLD", pip_size=0.01, contract_size=100.0)

        # Outbound translation (Internal -> Broker)
        outbound = self.mapper.to_broker_symbol("XAU_USD", "FOREX_COM")
        self.assertEqual(outbound, "GOLD")

        # Inbound translation (Broker -> Internal)
        inbound = self.mapper.to_internal_symbol("GOLD", "FOREX_COM")
        self.assertEqual(inbound, "XAU_USD")

        # Fallback when unmapped
        fallback_out = self.mapper.to_broker_symbol("GBP_USD", "UNKNOWN_BROKER")
        self.assertEqual(fallback_out, "GBPUSD")

    def test_auto_discovery_and_batch_mapping(self):
        instruments = ["EURUSD.raw", "GBPUSD.pro", "USDJPY.micro", "GOLD", "BITCOIN"]
        count = self.mapper.auto_discover_and_map_instruments(instruments, broker_id="OANDA")
        self.assertEqual(count, 5)

        mapped_list = database.get_all_symbol_mappings("OANDA")
        self.assertEqual(len(mapped_list), 5)

if __name__ == "__main__":
    unittest.main()
