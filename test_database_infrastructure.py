"""
Unit tests for Permanent Database Infrastructure Engine.
"""

import unittest
import os
import config
import database
from database_infrastructure import DatabaseInfrastructure, get_database_infrastructure

class TestDatabaseInfrastructure(unittest.TestCase):

    def setUp(self):
        self.test_db = "test_permanent_db.db"
        self.old_db = getattr(config, "DB_PATH", "forex_scalper.db")
        config.DB_PATH = self.test_db
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        self.infra = DatabaseInfrastructure(db_path=self.test_db)

    def tearDown(self):
        config.DB_PATH = self.old_db
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    def test_wal_connection_and_pragmas(self):
        conn = self.infra.get_connection()
        cursor = conn.cursor()

        cursor.execute("PRAGMA journal_mode;")
        journal_mode = cursor.fetchone()[0]
        self.assertEqual(journal_mode.lower(), "wal")

        cursor.execute("PRAGMA busy_timeout;")
        busy_timeout = cursor.fetchone()[0]
        self.assertEqual(busy_timeout, 60000)

        conn.close()

    def test_schema_migrations_versioning(self):
        version = self.infra.get_schema_version()
        self.assertEqual(version, self.infra.CURRENT_SCHEMA_VERSION)

        conn = self.infra.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'")
        table = cursor.fetchone()
        self.assertIsNotNone(table)
        conn.close()

    def test_online_maintenance_execution(self):
        res = self.infra.run_online_maintenance()
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(res["foreign_key_errors"], 0)

    def test_automated_backup_trigger(self):
        res = self.infra.trigger_automated_backup()
        self.assertIsInstance(res, dict)
        self.assertIn("success", res)

if __name__ == "__main__":
    unittest.main()
