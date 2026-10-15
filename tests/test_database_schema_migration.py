import os
import sqlite3
import tempfile
import unittest

import config
import database


class TestDatabaseSchemaMigration(unittest.TestCase):
    """Tests schema initialization and column migration in database.py."""

    def setUp(self):
        # Create a temporary database file for testing
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.original_db_path = config.DB_PATH
        config.DB_PATH = self.db_path

    def tearDown(self):
        config.DB_PATH = self.original_db_path
        os.close(self.db_fd)
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_init_db_fresh_database(self):
        """Test init_db creates all required tables and columns on a fresh database."""
        database.init_db()

        conn = database.get_connection()
        cursor = conn.cursor()

        # Verify trades table columns
        cursor.execute("PRAGMA table_info(trades)")
        columns = {row[1] for row in cursor.fetchall()}

        expected_columns = {
            "id",
            "ticket",
            "symbol",
            "direction",
            "open_price",
            "open_time",
            "sl",
            "tp",
            "lot_size",
            "status",
            "close_price",
            "close_time",
            "profit",
            "close_reason",
            "strategy",
            "method",
            "product",
        }
        self.assertTrue(expected_columns.issubset(columns))
        conn.close()

    def test_init_db_idempotent(self):
        """Test init_db can be called multiple times without error."""
        database.init_db()
        # Second call should handle "column already present" gracefully
        database.init_db()

        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(trades)")
        columns = {row[1] for row in cursor.fetchall()}
        self.assertIn("strategy", columns)
        self.assertIn("method", columns)
        self.assertIn("product", columns)
        conn.close()

    def test_init_db_legacy_trades_table_migration(self):
        """Test init_db correctly migrates an existing trades table lacking strategy, method, product columns."""
        # Manually create legacy trades table without strategy/method/product
        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket TEXT UNIQUE,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            open_price REAL NOT NULL,
            open_time TEXT NOT NULL,
            sl REAL NOT NULL,
            tp REAL NOT NULL,
            lot_size REAL NOT NULL,
            status TEXT NOT NULL
        )
        """)
        conn.commit()
        conn.close()

        # Run init_db which should execute ALTER TABLE ADD COLUMN for missing columns
        database.init_db()

        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(trades)")
        columns = {row[1] for row in cursor.fetchall()}

        self.assertIn("strategy", columns)
        self.assertIn("method", columns)
        self.assertIn("product", columns)
        conn.close()


if __name__ == "__main__":
    unittest.main()
