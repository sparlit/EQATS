import os
import sqlite3
import unittest

import broker_database
import database
from institutional_integrations.web_api import TradingOSHTTPServer


class TestBrokerDatabase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Initialize test database using in-memory or temp path
        database.init_db()
        broker_database.build_and_seed_broker_database("Brokers", force_rebuild=True)

    def test_parse_txt_brokers_nonexistent(self) -> None:
        records = broker_database.parse_txt_brokers("Brokers/nonexistent_file_12345.txt")
        self.assertEqual(records, [])

    def test_parse_txt_brokers_valid_file(self) -> None:
        import tempfile

        content = (
            "TRADE NAME\n"
            "   \n"
            "MEMBER NAME\n"
            "   Zerodha Broking Limited   \n"
            "INDIAN STOCK MARKET REGISTERED BROKERS\n"
            "  Groww   Pay   \n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(content)
            temp_path = f.name

        try:
            records = broker_database.parse_txt_brokers(temp_path)
            fname = os.path.basename(temp_path)
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0], {"name": "Zerodha Broking Limited", "sources": [fname]})
            self.assertEqual(records[1], {"name": "Groww Pay", "sources": [fname]})
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_parse_txt_brokers_error_handling(self) -> None:
        import tempfile

        # Open a directory or invalid path to raise an exception in open()
        with tempfile.TemporaryDirectory() as temp_dir:
            records = broker_database.parse_txt_brokers(temp_dir)
            self.assertEqual(records, [])

    def test_clean_field(self) -> None:
        self.assertEqual(broker_database.clean_field("  AXIS   BANK  "), "AXIS BANK")
        self.assertEqual(broker_database.clean_field("12345.0"), "12345")
        self.assertEqual(broker_database.clean_field(None), "")

    def test_normalize_entity_key(self) -> None:
        key1 = broker_database.normalize_entity_key("1FC SECURITIES PRIVATE LIMITED")
        key2 = broker_database.normalize_entity_key("1FC SECURITIES")
        self.assertEqual(key1, key2)
        self.assertEqual(key1, "1FCSECURITIES")

        reg_key = broker_database.normalize_entity_key("Any Name", "INZ000173137")
        self.assertEqual(reg_key, "REG_INZ000173137")

    def test_database_direct_sqlite3_query(self) -> None:
        # Actively test direct sqlite3 connection to DB_PATH
        self.assertTrue(os.path.exists(database.config.DB_PATH))
        conn = sqlite3.connect(database.config.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM registered_brokers")
        cnt = cursor.fetchone()[0]
        conn.close()
        self.assertGreater(cnt, 1000)

    def test_database_record_count(self) -> None:
        stats = broker_database.get_registered_broker_stats()
        self.assertGreater(stats["total_unique_brokers"], 1000)
        self.assertIn("SEBI_VERIFIED", stats["verification_breakdown"])

    def test_broker_lookup_exact(self) -> None:
        # Test lookup by SEBI registration number
        broker = broker_database.get_registered_broker("INZ000173137")
        self.assertIsNotNone(broker)
        if broker:
            self.assertIn("ADROIT FINANCIAL", broker["name"].upper())
            self.assertIn("Debt", broker["segments"])

    def test_broker_lookup_by_name(self) -> None:
        # Test lookup by entity name
        broker = broker_database.get_registered_broker("5PAISA CAPITAL LIMITED")
        self.assertIsNotNone(broker)
        if broker:
            self.assertEqual(broker["registration_no"], "INZ000010231")

    def test_search_registered_brokers(self) -> None:
        results = broker_database.search_registered_brokers(keyword="ANGEL", limit=10)
        self.assertGreater(len(results), 0)
        found = any("ANGEL" in b["name"].upper() for b in results)
        self.assertTrue(found)

    def test_search_registered_brokers_by_segment(self) -> None:
        results = broker_database.search_registered_brokers(segment="Commodity", limit=10)
        self.assertGreater(len(results), 0)
        for b in results:
            self.assertTrue(any("Commodity" in s for s in b["segments"]))

    def test_web_api_registered_broker_endpoints(self) -> None:
        server = TradingOSHTTPServer(port=59999)
        # Test /api/brokers/search
        res_search = server._route_request("GET", "/api/brokers/search?q=5paisa")
        self.assertEqual(res_search["status"], "SUCCESS")
        self.assertGreater(res_search["count"], 0)

        # Test /api/brokers/lookup
        res_lookup = server._route_request("GET", "/api/brokers/lookup?q=INZ000173137")
        self.assertEqual(res_lookup["status"], "SUCCESS")
        self.assertIsNotNone(res_lookup["broker"])

        # Test /api/brokers/stats
        res_stats = server._route_request("GET", "/api/brokers/stats")
        self.assertEqual(res_stats["status"], "SUCCESS")
        self.assertIn("total_unique_brokers", res_stats["stats"])


if __name__ == "__main__":
    unittest.main()
