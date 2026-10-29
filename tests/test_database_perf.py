import os
import sys
import unittest
import tempfile
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config
import database

class TestDatabasePerformanceAndPooling(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_file = os.path.join(self.temp_dir, "test_perf.db")
        config.DB_PATH = self.db_file
        database.clear_connection_pool()
        database.init_db()

    def tearDown(self):
        database.clear_connection_pool()
        if os.path.exists(self.db_file):
            try:
                os.remove(self.db_file)
            except Exception:
                pass
        salt_file = self.db_file + ".salt"
        if os.path.exists(salt_file):
            try:
                os.remove(salt_file)
            except Exception:
                pass

    def test_connection_pooling_reuses_same_connection(self):
        conn1 = database.get_connection()
        conn2 = database.get_connection()
        self.assertIs(conn1, conn2, "get_connection() should return the thread-local pooled connection instance")

    def test_get_daily_profit_calculation(self):
        # Initial empty daily profit
        self.assertEqual(database.get_daily_profit("2026-03-31"), 0.0)

        # Log closed trade
        database.log_trade_open("T101", "EURUSD", "BUY", 1.05, 1.04, 1.06, 0.1)
        # Force close_time to specific date
        conn = database.get_connection()
        conn.execute(
            "UPDATE trades SET status = 'CLOSED', profit = 125.50, close_time = '2026-03-31T14:30:00' WHERE ticket = 'T101'"
        )

        profit = database.get_daily_profit("2026-03-31")
        self.assertEqual(profit, 125.50)

if __name__ == "__main__":
    unittest.main()
