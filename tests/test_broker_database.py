"""Unit tests for broker database ingestion and XLS broker parsing."""

import os
import sqlite3
import unittest
from unittest.mock import MagicMock, patch

import broker_database
import database
from institutional_integrations.web_api import TradingOSHTTPServer


class TestBrokerDatabase(unittest.TestCase):
    """Test suite for registered broker database queries and web API endpoints."""
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


class TestParseXlsBrokers(unittest.TestCase):
    """Test suite for parse_xls_brokers spreadsheet parser."""

    def test_parse_xls_brokers_nonexistent_file(self) -> None:
        """Verifies parse_xls_brokers returns empty list when file path does not exist."""
        records = broker_database.parse_xls_brokers("non_existent_file_xyz_123.xls")
        self.assertEqual(records, [])

    def test_parse_xls_brokers_real_file(self) -> None:
        """Verifies parse_xls_brokers accurately parses an actual XLS broker spreadsheet."""
        real_xls = os.path.join(
            "Brokers",
            "Registered Stock Brokers in Equity Derivative Segment as on Jul 11 2026.xls",
        )
        if os.path.exists(real_xls):
            records = broker_database.parse_xls_brokers(real_xls)
            self.assertGreater(len(records), 0)
            first = records[0]
            self.assertIn("name", first)
            self.assertIn("registration_no", first)
            self.assertIn("Equity Derivative", first["segments"])
            self.assertIn(os.path.basename(real_xls), first["sources"])

    @patch("os.path.exists", return_value=True)
    @patch("xlrd.open_workbook")
    def test_parse_xls_brokers_mocked_success(
        self, mock_open_wb: MagicMock, mock_exists: MagicMock
    ) -> None:
        """Verifies mock XLS parsing for field mapping, trade name fallback, and segment regex."""
        mock_wb = MagicMock()
        mock_sheet = MagicMock()
        mock_wb.sheet_by_index.return_value = mock_sheet
        mock_open_wb.return_value = mock_wb

        # Row indices:
        # Row 0, 1, 2: header / unused
        # Row 3: valid full broker record
        # Row 4: empty primary name, but valid trade_name
        mock_sheet.nrows = 5
        mock_sheet.ncols = 22

        def cell_val(row_idx: int, col_idx: int) -> str:
            if row_idx == 3:
                data = {
                    0: "ALPHA CAPITAL LTD",
                    1: "INZ000111222",
                    2: "John Doe",
                    3: "123 Main St",
                    4: "john@alpha.com",
                    5: "9876543210",
                    6: "022-1234567",
                    7: "Mumbai",
                    8: "Maharashtra",
                    9: "400001",
                    17: "2020-01-01",
                    18: "2030-01-01",
                    20: "NSE",
                    21: "ALPHA TRADING",
                }
                return data.get(col_idx, "")
            if row_idx == 4:
                data = {
                    0: "",  # Name empty
                    1: "INZ000333444",
                    21: "BETA SECURITIES TRADING",  # Trade name present
                }
                return data.get(col_idx, "")
            return ""

        mock_sheet.cell_value.side_effect = cell_val

        fpath = "Brokers in Commodity Derivative Segment as on Jul 11 2026.xls"
        records = broker_database.parse_xls_brokers(fpath)

        self.assertTrue(mock_exists.called)
        self.assertTrue(mock_open_wb.called)
        self.assertEqual(len(records), 2)

        # Record 0 checks
        r0 = records[0]
        self.assertEqual(r0["name"], "ALPHA CAPITAL LTD")
        self.assertEqual(r0["registration_no"], "INZ000111222")
        self.assertEqual(r0["trade_name"], "ALPHA TRADING")
        self.assertEqual(r0["contact_person"], "John Doe")
        self.assertEqual(r0["email"], "john@alpha.com")
        self.assertEqual(r0["phone"], "9876543210")
        self.assertEqual(r0["fax"], "022-1234567")
        self.assertEqual(r0["address"], "123 Main St")
        self.assertEqual(r0["city"], "Mumbai")
        self.assertEqual(r0["state"], "Maharashtra")
        self.assertEqual(r0["pincode"], "400001")
        self.assertEqual(r0["valid_from"], "2020-01-01")
        self.assertEqual(r0["valid_to"], "2030-01-01")
        self.assertEqual(r0["exchange"], "NSE")
        self.assertEqual(r0["segments"], ["Commodity Derivative"])
        self.assertEqual(r0["sources"], [fpath])

        # Record 1 checks (trade_name fallback when name is empty)
        r1 = records[1]
        self.assertEqual(r1["name"], "BETA SECURITIES TRADING")
        self.assertEqual(r1["trade_name"], "BETA SECURITIES TRADING")
        self.assertEqual(r1["registration_no"], "INZ000333444")

    @patch("os.path.exists", return_value=True)
    @patch("xlrd.open_workbook")
    def test_parse_xls_brokers_empty_row_and_short_row(
        self, mock_open_wb: MagicMock, mock_exists: MagicMock
    ) -> None:
        """Verifies parse_xls_brokers skips empty rows and handles short row lengths safely."""
        mock_wb = MagicMock()
        mock_sheet = MagicMock()
        mock_wb.sheet_by_index.return_value = mock_sheet
        mock_open_wb.return_value = mock_wb

        # Row 3: empty row (skipped)
        # Row 4: short row (ncols = 2, only name & reg_no)
        mock_sheet.nrows = 5
        mock_sheet.ncols = 2

        def cell_val(row_idx: int, col_idx: int) -> str:
            if row_idx == 4:
                if col_idx == 0:
                    return "GAMMA TRADERS"
                if col_idx == 1:
                    return "INZ000555666"
            return ""

        mock_sheet.cell_value.side_effect = cell_val

        # Test filename without segment match pattern -> default segment "General"
        fpath = "random_brokers_file.xls"
        records = broker_database.parse_xls_brokers(fpath)

        self.assertTrue(mock_exists.called)
        self.assertTrue(mock_open_wb.called)
        self.assertEqual(len(records), 1)
        r = records[0]
        self.assertEqual(r["name"], "GAMMA TRADERS")
        self.assertEqual(r["registration_no"], "INZ000555666")
        self.assertEqual(r["segments"], ["General"])
        self.assertEqual(r["sources"], ["random_brokers_file.xls"])

    @patch("os.path.exists", return_value=True)
    @patch("xlrd.open_workbook", side_effect=Exception("XLS file corrupted or invalid"))
    def test_parse_xls_brokers_exception_handling(
        self, mock_open_wb: MagicMock, mock_exists: MagicMock
    ) -> None:
        """Verifies parse_xls_brokers catches xlrd errors gracefully and returns empty list."""
        records = broker_database.parse_xls_brokers("corrupted.xls")
        self.assertTrue(mock_exists.called)
        self.assertTrue(mock_open_wb.called)
        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
