import os
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import openpyxl

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

    def test_parse_xlsx_brokers_nonexistent_file(self) -> None:
        records = broker_database.parse_xlsx_brokers("non_existent_file_12345.xlsx")
        self.assertEqual(records, [])

    def test_parse_xlsx_brokers_actual_file(self) -> None:
        xlsx_path = os.path.join("Brokers", "indian_brokers.xlsx")
        if os.path.exists(xlsx_path):
            records = broker_database.parse_xlsx_brokers(xlsx_path)
            self.assertGreater(len(records), 0)
            for rec in records:
                self.assertIn("name", rec)
                self.assertIn("segments", rec)
                self.assertEqual(rec["sources"], ["indian_brokers.xlsx"])
                self.assertNotIn(rec["name"].upper(), ("TRADE NAME", "MEMBER NAME", "INDIAN STOCK MARKET REGISTERED BROKERS"))

    def test_parse_xlsx_brokers_mock_file(self) -> None:
        wb = openpyxl.Workbook()
        ws_equity = wb.active
        ws_equity.title = "NSE_Equity"
        ws_equity.append(["TRADE NAME"])
        ws_equity.append(["  ALPHA CAPITAL PRIVATE LIMITED  "])
        ws_equity.append(["BETA SECURITIES 100.0"])
        ws_equity.append([None])
        ws_equity.append([""])

        ws_deriv = wb.create_sheet(title="NSE_Derivatives")
        ws_deriv.append(["MEMBER NAME"])
        ws_deriv.append(["GAMMA BROKING LTD"])

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            wb.save(tmp_path)
            records = broker_database.parse_xlsx_brokers(tmp_path)
            fname = os.path.basename(tmp_path)

            self.assertEqual(len(records), 3)
            self.assertEqual(
                records[0],
                {"name": "ALPHA CAPITAL PRIVATE LIMITED", "segments": ["NSE_Equity"], "sources": [fname]},
            )
            self.assertEqual(
                records[1],
                {"name": "BETA SECURITIES 100", "segments": ["NSE_Equity"], "sources": [fname]},
            )
            self.assertEqual(
                records[2],
                {"name": "GAMMA BROKING LTD", "segments": ["NSE_Derivatives"], "sources": [fname]},
            )
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_parse_xlsx_brokers_corrupt_file_exception_handling(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(b"NOT A VALID XLSX CONTENT CORRUPT BYTES")
            tmp_path = tmp.name

        try:
            records = broker_database.parse_xlsx_brokers(tmp_path)
            self.assertEqual(records, [])
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_parse_txt_brokers(self) -> None:
        self.assertEqual(broker_database.parse_txt_brokers("non_existent.txt"), [])

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as tmp:
            tmp.write("TRADE NAME\n  DELTA TRADING CO  \n\nEPSILON BROKERAGE\n")
            tmp_path = tmp.name

        try:
            records = broker_database.parse_txt_brokers(tmp_path)
            fname = os.path.basename(tmp_path)
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0], {"name": "DELTA TRADING CO", "sources": [fname]})
            self.assertEqual(records[1], {"name": "EPSILON BROKERAGE", "sources": [fname]})
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_parse_xls_and_pdf_nonexistent(self) -> None:
        self.assertEqual(broker_database.parse_xls_brokers("non_existent.xls"), [])
        self.assertEqual(broker_database.parse_pdf_brokers("non_existent.pdf"), [])


class TestParseXlsBrokers(unittest.TestCase):
    """Unit tests for parse_xls_brokers in broker_database."""

    def test_parse_xls_brokers_non_existent_file(self) -> None:
        records = broker_database.parse_xls_brokers("non_existent_brokers_file.xls")
        self.assertEqual(records, [])

    @patch("os.path.exists", return_value=True)
    @patch("xlrd.open_workbook")
    def test_parse_xls_brokers_valid_file(self, mock_open_wb: MagicMock, mock_exists: MagicMock) -> None:
        mock_sheet = MagicMock()
        mock_sheet.nrows = 4
        mock_sheet.ncols = 22

        data_row = [""] * 22
        data_row[0] = "  ALPHA CAPITAL LIMITED  "
        data_row[1] = "INZ000999999"
        data_row[2] = "John Doe"
        data_row[3] = "123 Financial Street"
        data_row[4] = "info@alphacapital.com"
        data_row[5] = "9876543210.0"
        data_row[6] = "0221234567"
        data_row[7] = "Mumbai"
        data_row[8] = "Maharashtra"
        data_row[9] = "400001"
        data_row[17] = "2020-01-01"
        data_row[18] = "2030-01-01"
        data_row[20] = "NSE"
        data_row[21] = "Alpha Trade"

        def cell_val(r: int, c: int) -> str:
            if r < 3:
                return "Header"
            return data_row[c]

        mock_sheet.cell_value.side_effect = cell_val
        mock_wb = MagicMock()
        mock_wb.sheet_by_index.return_value = mock_sheet
        mock_open_wb.return_value = mock_wb

        file_path = "Brokers in Equity Segment as on Jul 11 2026.xls"
        records = broker_database.parse_xls_brokers(file_path)

        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["name"], "ALPHA CAPITAL LIMITED")
        self.assertEqual(rec["registration_no"], "INZ000999999")
        self.assertEqual(rec["trade_name"], "Alpha Trade")
        self.assertEqual(rec["contact_person"], "John Doe")
        self.assertEqual(rec["email"], "info@alphacapital.com")
        self.assertEqual(rec["phone"], "9876543210")
        self.assertEqual(rec["fax"], "0221234567")
        self.assertEqual(rec["address"], "123 Financial Street")
        self.assertEqual(rec["city"], "Mumbai")
        self.assertEqual(rec["state"], "Maharashtra")
        self.assertEqual(rec["pincode"], "400001")
        self.assertEqual(rec["exchange"], "NSE")
        self.assertEqual(rec["valid_from"], "2020-01-01")
        self.assertEqual(rec["valid_to"], "2030-01-01")
        self.assertEqual(rec["segments"], ["Equity"])
        self.assertEqual(rec["sources"], ["Brokers in Equity Segment as on Jul 11 2026.xls"])

    @patch("os.path.exists", return_value=True)
    @patch("xlrd.open_workbook")
    def test_parse_xls_brokers_segment_regex_and_trade_name_fallback(
        self, mock_open_wb: MagicMock, mock_exists: MagicMock
    ) -> None:
        mock_sheet = MagicMock()
        mock_sheet.nrows = 4
        mock_sheet.ncols = 22

        data_row = [""] * 22
        data_row[21] = "Fallback Trade Name"
        data_row[1] = "INZ000888888"

        def cell_val(r: int, c: int) -> str:
            if r < 3:
                return "Header"
            return data_row[c]

        mock_sheet.cell_value.side_effect = cell_val
        mock_wb = MagicMock()
        mock_wb.sheet_by_index.return_value = mock_sheet
        mock_open_wb.return_value = mock_wb

        file_path = "generic_stock_brokers.xls"
        records = broker_database.parse_xls_brokers(file_path)

        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["name"], "Fallback Trade Name")
        self.assertEqual(rec["segments"], ["General"])
        self.assertEqual(rec["sources"], ["generic_stock_brokers.xls"])

    @patch("os.path.exists", return_value=True)
    @patch("xlrd.open_workbook")
    def test_parse_xls_brokers_short_rows_and_empty_rows(
        self, mock_open_wb: MagicMock, mock_exists: MagicMock
    ) -> None:
        mock_sheet = MagicMock()
        mock_sheet.nrows = 5
        mock_sheet.ncols = 3

        def cell_val(r: int, c: int) -> str:
            if r == 3:
                return ""
            if r == 4:
                cols = ["Short Broker Name", "INZ111222333", "Contact Person"]
                return cols[c] if c < len(cols) else ""
            return "Header"

        mock_sheet.cell_value.side_effect = cell_val
        mock_wb = MagicMock()
        mock_wb.sheet_by_index.return_value = mock_sheet
        mock_open_wb.return_value = mock_wb

        records = broker_database.parse_xls_brokers("sample_short.xls")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["name"], "Short Broker Name")
        self.assertEqual(records[0]["registration_no"], "INZ111222333")
        self.assertEqual(records[0]["contact_person"], "Contact Person")
        self.assertEqual(records[0]["email"], "")

    @patch("os.path.exists", return_value=True)
    @patch("xlrd.open_workbook", side_effect=Exception("Workbook corrupt"))
    def test_parse_xls_brokers_exception_handling(
        self, mock_open_wb: MagicMock, mock_exists: MagicMock
    ) -> None:
        records = broker_database.parse_xls_brokers("corrupt.xls")
        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
