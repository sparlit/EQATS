import os
import sqlite3
import unittest

import broker_database
import database


class TestBrokerDatabase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Initialize test database using in-memory or temp path
        database.init_db()
        broker_database.build_and_seed_broker_database("Brokers", force_rebuild=True)

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


if __name__ == "__main__":
    unittest.main()
