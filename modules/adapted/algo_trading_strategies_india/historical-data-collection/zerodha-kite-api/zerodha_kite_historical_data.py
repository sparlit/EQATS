import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


# zerodha_kite_historical_data_backward_pagination.py
import csv
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import psycopg2
import requests
from kiteconnect import KiteConnect
from psycopg2.extras import execute_values


class KiteHistoricalDataDownloader:
    """
    Enhanced class to handle historical stock data download from Zerodha Kite Connect API
    using backward pagination strategy for better API management
    """

    def __init__(self):
        """Initialize the downloader with credentials and database configuration"""
        self._setup_credentials()
        self._setup_database_config()
        self._setup_file_paths()
        self._setup_logging()
        self._setup_pagination_config()
        self.kite = None
        self.processing_stats = {
            "total_instruments": 0,
            "processed_instruments": 0,
            "successful_instruments": 0,
            "failed_instruments": 0,
            "total_records_downloaded": 0,
            "total_api_calls": 0,
            "total_pagination_batches": 0,
            "start_time": None,
            "failed_symbols": [],
        }

    def _setup_credentials(self):
        """Setup API credentials - UPDATE THESE WITH YOUR ACTUAL CREDENTIALS"""
        self.api_key = "your_kite_api_key_here"
        self.api_secret = "your_kite_api_secret_here"

    def _setup_database_config(self):
        """Setup database configuration - UPDATE THESE WITH YOUR DATABASE DETAILS"""
        self.DB_PARAMS = {
            "dbname": "your_database_name",
            "user": "your_username",
            "password": "your_password",
            "host": "your_host",
            "port": 5432,
        }

    def _setup_file_paths(self):
        """Setup file paths using Path for better cross-platform compatibility"""
        self.base_path = Path("./kite_connect_data")
        self.access_token_file = self.base_path / "key_files" / "access_token.txt"
        self.instruments_file = Path("instruments.csv")

        # Create directories if they don't exist
        self.access_token_file.parent.mkdir(parents=True, exist_ok=True)

    def _setup_pagination_config(self):
        """Setup pagination configuration for backward data collection"""
        self.PAGINATION_CONFIG = {
            "days_per_batch": 1800,  # Days per API call for better performance
            "max_years_back": 70,  # Maximum years to go back
            "api_delay_seconds": 0,  # Delay between API calls to avoid rate limiting
            "max_retries": 3,  # Maximum retries for failed API calls
            "retry_delay": 1.0,  # Delay between retries
        }

    def _setup_logging(self):
        """Setup console-only logging configuration with detailed formatting"""
        console_formatter = logging.Formatter("%(asctime)s - %(levelname)-8s - %(message)s", datefmt="%H:%M:%S")

        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)

        self.logger.info("=" * 80)
        self.logger.info("KITE HISTORICAL DATA DOWNLOADER - BACKWARD PAGINATION VERSION")
        self.logger.info("=" * 80)

    def _log_processing_stats(self):
        """Log current processing statistics"""
        stats = self.processing_stats
        if stats["start_time"]:
            elapsed = datetime.now() - stats["start_time"]
            elapsed_str = str(elapsed).split(".")[0]
        else:
            elapsed_str = "N/A"

        self.logger.info("=" * 60)
        self.logger.info("PROCESSING STATISTICS")
        self.logger.info("=" * 60)
        self.logger.info(f"Total Instruments: {stats['total_instruments']}")
        self.logger.info(f"Processed: {stats['processed_instruments']}")
        self.logger.info(f"Successful (with API calls): {stats['successful_instruments']}")
        self.logger.info(f"Failed (API calls): {stats['failed_instruments']}")
        self.logger.info(
            f"Skipped (empty names): {stats['processed_instruments'] - stats['successful_instruments'] - stats['failed_instruments']}"
        )
        self.logger.info(f"Total Records Downloaded: {stats['total_records_downloaded']:,}")
        self.logger.info(f"Total API Calls: {stats['total_api_calls']}")
        self.logger.info(f"Total Pagination Batches: {stats['total_pagination_batches']}")
        self.logger.info(f"Elapsed Time: {elapsed_str}")

        if stats["processed_instruments"] > 0:
            api_call_instruments = stats["successful_instruments"] + stats["failed_instruments"]
            if api_call_instruments > 0:
                api_success_rate = (stats["successful_instruments"] / api_call_instruments) * 100
                self.logger.info(f"API Success Rate: {api_success_rate:.1f}%")

            if stats["total_api_calls"] > 0:
                avg_records = stats["total_records_downloaded"] / stats["total_api_calls"]
                self.logger.info(f"Avg Records per API Call: {avg_records:.1f}")

        if stats["failed_symbols"]:
            self.logger.warning(
                f"Failed Symbols ({len(stats['failed_symbols'])}): {', '.join(stats['failed_symbols'][:10])}"
            )
            if len(stats["failed_symbols"]) > 10:
                self.logger.warning(f"... and {len(stats['failed_symbols']) - 10} more failed symbols")

        self.logger.info("=" * 60)

    def _read_access_token(self):
        """Read access token from file with proper error handling"""
        try:
            self.logger.info("Reading access token from file...")
            if not self.access_token_file.exists():
                self.logger.error(f"Access token file not found: {self.access_token_file}")
                self.logger.error("Please create the access token file with your Kite Connect access token")
                self.logger.error("Example: echo 'your_access_token_here' > key_files/access_token.txt")
                return None

            with open(self.access_token_file, encoding="utf-8") as file:
                token = file.read().strip()
                if not token:
                    self.logger.error("Access token file is empty")
                    return None
                self.logger.info("Access token read successfully")
                return token

        except Exception as e:
            self.logger.exception(f"Error reading access token file: {e}")
            return None

    def _test_kite_connection(self):
        """Test Kite API connection by fetching profile"""
        try:
            self.logger.info("Testing Kite API connection...")
            profile = self.kite.profile()
            user_name = profile.get("user_name", "Unknown")
            user_id = profile.get("user_id", "Unknown")
            broker = profile.get("broker", "Unknown")
            self.logger.info("✓ Authentication successful!")
            self.logger.info(f"  User: {user_name} (ID: {user_id})")
            self.logger.info(f"  Broker: {broker}")
            return True
        except Exception as e:
            self.logger.exception(f"✗ Access token validation failed: {e}")
            self.logger.exception("Please ensure your access token is valid and not expired")
            return False

    def authenticate_kite(self):
        """Authenticate with Kite Connect API using access token from file"""
        try:
            self.logger.info("Starting Kite Connect authentication...")

            access_token = self._read_access_token()
            if not access_token:
                self.logger.error("Please ensure the access token file exists and contains a valid token")
                return False

            self.logger.info("Initializing KiteConnect client...")
            self.kite = KiteConnect(api_key=self.api_key)
            self.kite.set_access_token(access_token)

            return self._test_kite_connection()

        except Exception as e:
            self.logger.exception(f"Authentication failed: {e}")
            return False

    def _filter_instruments(self, instruments):
        """Filter instruments for BSE and NSE exchanges, lot_size = 1, and non-empty names only"""
        self.logger.info("Filtering instruments for BSE and NSE exchanges...")

        # STEP 1: First filter for exchanges
        exchange_filtered = [inst for inst in instruments if inst["exchange"] in ["BSE", "NSE"]]
        self.logger.info(
            f"After exchange filter: {len(exchange_filtered)} instruments from {len(instruments)} total instruments"
        )

        # STEP 2: Second filter for lot_size = 1 (applied to exchange_filtered)
        lot_size_filtered = [inst for inst in exchange_filtered if inst.get("lot_size") == 1]

        # Log filtering statistics for lot_size
        lot_size_filtered_count = len(exchange_filtered) - len(lot_size_filtered)
        self.logger.info(f"Filtered out {lot_size_filtered_count} instruments with lot_size != 1")
        self.logger.info(f"After lot_size filter: {len(lot_size_filtered)} instruments")

        # STEP 3: Third filter for non-empty names (FINAL FILTER)
        final_filtered = [inst for inst in lot_size_filtered if inst.get("name") and inst["name"].strip()]

        # Log filtering statistics for names
        empty_names_count = len(lot_size_filtered) - len(final_filtered)
        self.logger.info(f"Filtered out {empty_names_count} instruments with empty names")
        self.logger.info(f"FINAL FILTERED INSTRUMENTS: {len(final_filtered)} (only non-empty names)")

        # Log examples of filtered out instruments for debugging
        if empty_names_count > 0:
            empty_name_examples = [
                inst["tradingsymbol"] for inst in lot_size_filtered if not (inst.get("name") and inst["name"].strip())
            ][:5]
            self.logger.info(f"Examples of symbols with empty names (filtered out): {empty_name_examples}")

        if lot_size_filtered_count > 0:
            lot_size_examples = [
                f"{inst['tradingsymbol']}(lot_size:{inst.get('lot_size')})"
                for inst in exchange_filtered
                if inst.get("lot_size") != 1
            ][:5]
            self.logger.info(f"Examples of symbols with lot_size != 1: {lot_size_examples}")

        # Summary
        self.logger.info("=" * 50)
        self.logger.info("FILTERING SUMMARY:")
        self.logger.info(f"  Initial: {len(instruments):,}")
        self.logger.info(f"  After exchange: {len(exchange_filtered):,}")
        self.logger.info(f"  After lot_size: {len(lot_size_filtered):,}")
        self.logger.info(f"  After name filter: {len(final_filtered):,}")
        self.logger.info(f"  Total removed: {len(instruments) - len(final_filtered):,}")
        self.logger.info("=" * 50)

        return final_filtered

    def _save_instruments_to_csv(self, instruments):
        """Save filtered instruments to CSV file"""
        try:
            self.logger.info(f"Saving {len(instruments)} instruments to CSV file...")
            fieldnames = [
                "instrument_token",
                "exchange_token",
                "tradingsymbol",
                "name",
                "last_price",
                "expiry",
                "strike",
                "tick_size",
                "lot_size",
                "instrument_type",
                "segment",
                "exchange",
            ]

            with open(self.instruments_file, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(instruments)

            self.logger.info(f"✓ Successfully saved {len(instruments)} instruments to {self.instruments_file}")
            return True

        except Exception as e:
            self.logger.exception(f"✗ Failed to save instruments to CSV: {e}")
            return False

    def download_instruments(self):
        """Download instrument dump and filter for BSE and NSE"""
        try:
            self.logger.info("Downloading instruments dump from Kite API...")
            start_time = time.time()
            instruments = self.kite.instruments()
            download_time = time.time() - start_time

            self.logger.info(f"✓ Downloaded {len(instruments)} instruments in {download_time:.2f} seconds")

            filtered_instruments = self._filter_instruments(instruments)

            if self._save_instruments_to_csv(filtered_instruments):
                self.logger.info("✓ Instrument download completed successfully")
                return filtered_instruments
            return []

        except Exception as e:
            self.logger.exception(f"✗ Failed to download instruments: {e}")
            return []

    def _create_instruments_table(self, cursor):
        """Create instruments table"""
        self.logger.info("Creating instruments table...")
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS instruments
                       (
                           instrument_token BIGINT PRIMARY KEY,
                           exchange_token   BIGINT,
                           tradingsymbol    VARCHAR(100),
                           name             VARCHAR(200),
                           last_price       DECIMAL(10, 2),
                           expiry           DATE,
                           strike           DECIMAL(10, 2),
                           tick_size        DECIMAL(10, 4),
                           lot_size         INTEGER,
                           instrument_type  VARCHAR(20),
                           segment          VARCHAR(20),
                           exchange         VARCHAR(10)
                       )
                       """)

    def _create_historical_data_table(self, cursor):
        """Create z_kite_api_historical_data table"""
        self.logger.info("Creating z_kite_api_historical_data table...")
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS z_kite_api_historical_data
                       (
                           id            SERIAL PRIMARY KEY,
                           tradingsymbol VARCHAR(100),
                           exchange      VARCHAR(10),
                           timestamp     TIMESTAMP,
                           open_price    DECIMAL(15, 4),
                           high_price    DECIMAL(15, 4),
                           low_price     DECIMAL(15, 4),
                           close_price   DECIMAL(15, 4),
                           volume        BIGINT,
                           UNIQUE (tradingsymbol, exchange, timestamp)
                       )
                       """)

    def _create_database_indexes(self, cursor):
        """Create database indexes for better performance"""
        self.logger.info("Creating database indexes...")
        cursor.execute("""
                       CREATE INDEX IF NOT EXISTS idx_kite_historical_symbol_timestamp
                           ON z_kite_api_historical_data (tradingsymbol, exchange, timestamp)
                       """)

        cursor.execute("""
                       CREATE INDEX IF NOT EXISTS idx_kite_historical_timestamp
                           ON z_kite_api_historical_data (timestamp)
                       """)

        cursor.execute("""
                       CREATE INDEX IF NOT EXISTS idx_kite_historical_symbol
                           ON z_kite_api_historical_data (tradingsymbol, exchange)
                       """)

    def _truncate_instruments_table(self, cursor):
        """Truncate instruments table to ensure fresh data"""
        self.logger.info("Truncating instruments table...")
        cursor.execute("TRUNCATE TABLE instruments")

    def create_database_tables(self):
        """Create necessary database tables"""
        try:
            self.logger.info("Setting up database tables and indexes...")
            conn = psycopg2.connect(**self.DB_PARAMS)
            cursor = conn.cursor()

            self._create_instruments_table(cursor)
            self._create_historical_data_table(cursor)
            self._create_database_indexes(cursor)

            conn.commit()
            cursor.close()
            conn.close()

            self.logger.info("✓ Database tables and indexes created successfully")
            return True

        except Exception as e:
            self.logger.exception(f"✗ Failed to create database tables: {e}")
            self.logger.exception("Please check your database connection details in DB_PARAMS")
            return False

    def _prepare_instrument_data(self, instruments):
        """Prepare instruments data for database insertion"""
        self.logger.info("Preparing instrument data for database insertion...")
        instrument_data = []
        for inst in instruments:
            expiry = None
            if inst["expiry"] and inst["expiry"] != "":
                try:
                    expiry = datetime.strptime(inst["expiry"], "%Y-%m-%d").date()
                except:
                    expiry = None

            instrument_data.append(
                (
                    inst["instrument_token"],
                    inst["exchange_token"],
                    inst["tradingsymbol"],
                    inst["name"],
                    inst["last_price"] or 0,
                    expiry,
                    inst["strike"] or 0,
                    inst["tick_size"],
                    inst["lot_size"],
                    inst["instrument_type"],
                    inst["segment"],
                    inst["exchange"],
                )
            )

        self.logger.info(f"Prepared {len(instrument_data)} instrument records for insertion")
        return instrument_data

    def _execute_instrument_insert(self, cursor, instrument_data):
        """Execute instrument data insertion with conflict handling"""
        self.logger.info("Executing bulk instrument insertion...")
        insert_query = """
                       INSERT INTO instruments (instrument_token, exchange_token, tradingsymbol, name,
                                                last_price, expiry, strike, tick_size, lot_size,
                                                instrument_type, segment, exchange)
                       VALUES \
                       %s
                       ON CONFLICT (instrument_token)
                       DO UPDATE SET
                       tradingsymbol = EXCLUDED.tradingsymbol,
                       name = EXCLUDED.name,
                       last_price = EXCLUDED.last_price,
                       expiry = EXCLUDED.expiry,
                       strike = EXCLUDED.strike,
                       tick_size = EXCLUDED.tick_size,
                       lot_size = EXCLUDED.lot_size,
                       instrument_type = EXCLUDED.instrument_type,
                       segment = EXCLUDED.segment,
                       exchange = EXCLUDED.exchange
                       """
        execute_values(cursor, insert_query, instrument_data)

    def save_instruments_to_db(self, instruments):
        """Save instruments data to database"""
        try:
            self.logger.info(f"Saving {len(instruments)} filtered instruments to database...")
            conn = psycopg2.connect(**self.DB_PARAMS)
            cursor = conn.cursor()

            self._truncate_instruments_table(cursor)

            instrument_data = self._prepare_instrument_data(instruments)

            self.logger.info(f"Prepared {len(instrument_data)} instrument records for database insertion")

            self._execute_instrument_insert(cursor, instrument_data)

            conn.commit()

            # Verify the insertion
            cursor.execute("SELECT COUNT(*) FROM instruments")
            db_count = cursor.fetchone()[0]
            self.logger.info(f"✓ Verified: {db_count} instruments saved to database")

            cursor.close()
            conn.close()

            self.logger.info(f"✓ Successfully saved {len(instrument_data)} instruments to database")
            return True

        except Exception as e:
            self.logger.exception(f"✗ Failed to save instruments to database: {e}")
            return False

    def _generate_backward_date_ranges(self, start_date, earliest_date=None):
        """Generate date ranges for backward pagination"""
        if earliest_date is None:
            earliest_date = datetime.now() - timedelta(days=365 * self.PAGINATION_CONFIG["max_years_back"])

        date_ranges = []
        current_end = start_date

        while current_end > earliest_date:
            current_start = max(current_end - timedelta(days=self.PAGINATION_CONFIG["days_per_batch"]), earliest_date)
            date_ranges.append((current_start, current_end))
            current_end = current_start - timedelta(days=1)

            if current_start <= earliest_date:
                break

        return date_ranges

    def _fetch_historical_data_with_retry(self, instrument_token, from_date, to_date, interval, tradingsymbol):
        """Fetch historical data with retry mechanism"""
        for attempt in range(self.PAGINATION_CONFIG["max_retries"]):
            try:
                from_str = from_date.strftime("%Y-%m-%d %H:%M:%S")
                to_str = to_date.strftime("%Y-%m-%d %H:%M:%S")

                self.logger.info(
                    f"  API Call (Attempt {attempt + 1}): {tradingsymbol} - {from_date.strftime('%Y-%m-%d')} to {to_date.strftime('%Y-%m-%d')}"
                )

                start_time = time.time()

                response = self.kite.historical_data(
                    instrument_token=instrument_token, from_date=from_str, to_date=to_str, interval=interval
                )

                api_time = time.time() - start_time
                self.processing_stats["total_api_calls"] += 1

                # Extract the candles from the response
                if isinstance(response, dict) and "data" in response and "candles" in response["data"]:
                    historical_data = response["data"]["candles"]
                elif isinstance(response, list):
                    historical_data = response
                else:
                    self.logger.warning(f"  ⚠ Unexpected response format for {tradingsymbol}")
                    return []

                self.logger.info(f"  ✓ Retrieved {len(historical_data)} records in {api_time:.2f}s")

                # Add delay to avoid rate limiting
                if self.PAGINATION_CONFIG["api_delay_seconds"] > 0:
                    time.sleep(self.PAGINATION_CONFIG["api_delay_seconds"])

                return historical_data

            except Exception as e:
                self.logger.warning(f"  ⚠ API Error (Attempt {attempt + 1}): {e}")
                if attempt < self.PAGINATION_CONFIG["max_retries"] - 1:
                    time.sleep(self.PAGINATION_CONFIG["retry_delay"] * (attempt + 1))
                else:
                    self.logger.exception(f"  ✗ API call failed after {self.PAGINATION_CONFIG['max_retries']} attempts")
                    return []

        return []

    def download_historical_data_backward(self, instrument_token, tradingsymbol, exchange, interval="day"):
        """Download historical data using backward pagination strategy"""
        try:
            self.logger.info(f"Starting backward pagination for {tradingsymbol}")

            # Start from today and go backward
            start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            earliest_date = datetime.now() - timedelta(days=365 * self.PAGINATION_CONFIG["max_years_back"])

            # Generate backward date ranges
            date_ranges = self._generate_backward_date_ranges(start_date, earliest_date)

            if not date_ranges:
                self.logger.info(f"  ℹ No date ranges to collect for {tradingsymbol}")
                return 0

            self.logger.info(f"  📅 Collecting data in {len(date_ranges)} backward batches")
            self.logger.info(
                f"  📊 Date range: {date_ranges[-1][0].strftime('%Y-%m-%d')} to {date_ranges[0][1].strftime('%Y-%m-%d')}"
            )

            total_records = 0
            successful_batches = 0

            for i, (from_date, to_date) in enumerate(date_ranges, 1):
                batch_info = f"Batch {i}/{len(date_ranges)}"

                historical_data = self._fetch_historical_data_with_retry(
                    instrument_token, from_date, to_date, interval, tradingsymbol
                )

                if historical_data:
                    records_saved = self.save_historical_data(tradingsymbol, exchange, historical_data)
                    total_records += records_saved
                    successful_batches += 1

                    self.logger.info(f"  ✓ Saved {records_saved} records - {batch_info}")
                else:
                    self.logger.warning(f"  ⚠ No data returned - {batch_info}")

                self.processing_stats["total_pagination_batches"] += 1

            self.processing_stats["total_records_downloaded"] += total_records

            self.logger.info(
                f"✓ Completed {tradingsymbol}: {total_records:,} total records from {successful_batches}/{len(date_ranges)} successful batches"
            )
            return total_records

        except Exception as e:
            self.logger.exception(f"✗ Failed backward pagination for {tradingsymbol}: {e}")
            return 0

    def _prepare_historical_data(self, tradingsymbol, exchange, historical_data):
        """Prepare historical data for database insertion with proper format handling"""
        data_to_insert = []
        for record in historical_data:
            try:
                # Handle both dictionary format and array format
                if isinstance(record, dict):
                    # Dictionary format: {'date': datetime, 'open': float, 'high': float, ...}
                    timestamp = record.get("date")
                    open_price = float(record.get("open", 0)) if record.get("open") is not None else 0.0
                    high_price = float(record.get("high", 0)) if record.get("high") is not None else 0.0
                    low_price = float(record.get("low", 0)) if record.get("low") is not None else 0.0
                    close_price = float(record.get("close", 0)) if record.get("close") is not None else 0.0
                    volume = int(record.get("volume", 0)) if record.get("volume") is not None else 0

                elif isinstance(record, (list, tuple)) and len(record) >= 6:
                    # Array format: [timestamp, open, high, low, close, volume] or [timestamp, open, high, low, close, volume, oi]
                    timestamp = record[0]
                    open_price = float(record[1]) if record[1] is not None else 0.0
                    high_price = float(record[2]) if record[2] is not None else 0.0
                    low_price = float(record[3]) if record[3] is not None else 0.0
                    close_price = float(record[4]) if record[4] is not None else 0.0
                    volume = int(record[5]) if record[5] is not None else 0
                else:
                    self.logger.warning(f"Invalid record format: {record}")
                    continue

                # Handle timestamp conversion
                if isinstance(timestamp, str):
                    # Handle ISO format timestamps
                    if "+" in timestamp:
                        timestamp = timestamp.split("+")[0]
                    timestamp = datetime.fromisoformat(timestamp.replace("T", " "))
                elif hasattr(timestamp, "replace"):  # datetime object
                    # If it's already a datetime object, ensure it's timezone-naive for PostgreSQL
                    if timestamp.tzinfo is not None:
                        timestamp = timestamp.replace(tzinfo=None)

                data_to_insert.append(
                    (tradingsymbol, exchange, timestamp, open_price, high_price, low_price, close_price, volume)
                )

            except Exception as e:
                self.logger.warning(f"Error processing record {record}: {e}")
                continue

        return data_to_insert

    def _execute_historical_data_insert(self, cursor, data_to_insert):
        """Execute historical data insertion with conflict handling"""
        insert_query = """
                       INSERT INTO z_kite_api_historical_data (tradingsymbol, exchange, timestamp, open_price, high_price,
                                                               low_price, close_price, volume)
                       VALUES \
                       %s
                       ON CONFLICT (tradingsymbol, exchange, timestamp)
                       DO NOTHING
                       """
        execute_values(cursor, insert_query, data_to_insert)

    def save_historical_data(self, tradingsymbol, exchange, historical_data):
        """Save historical data to database with improved error handling"""
        conn = None
        cursor = None
        try:
            conn = psycopg2.connect(**self.DB_PARAMS)
            cursor = conn.cursor()

            data_to_insert = self._prepare_historical_data(tradingsymbol, exchange, historical_data)

            if data_to_insert:
                self._execute_historical_data_insert(cursor, data_to_insert)
                conn.commit()
                self.logger.debug(f"Successfully inserted {len(data_to_insert)} records to database")
                return len(data_to_insert)
            self.logger.warning("No valid data to insert")
            return 0

        except Exception as e:
            self.logger.exception(f"Failed to save historical data to database: {e}")
            if conn:
                conn.rollback()
            return 0
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def _load_instruments_from_csv(self):
        """Load instruments from CSV file"""
        try:
            self.logger.info("Loading instruments from CSV file...")
            df = pd.read_csv(self.instruments_file)
            self.logger.info(f"✓ Loaded {len(df)} instruments from CSV")
            return df
        except Exception as e:
            self.logger.exception(f"✗ Failed to load instruments from CSV: {e}")
            return None

    def _filter_test_symbols(self, instruments_df, test_symbols):
        """Filter dataframe for specific test symbols"""
        if not test_symbols:
            return instruments_df

        self.logger.info(f"Filtering for test symbols: {test_symbols}")

        test_symbols_upper = [symbol.upper() for symbol in test_symbols]
        filtered_df = instruments_df[instruments_df["tradingsymbol"].str.upper().isin(test_symbols_upper)].copy()

        self.logger.info(f"Found {len(filtered_df)} instruments matching test symbols:")
        for _, row in filtered_df.iterrows():
            self.logger.info(f"  - {row['tradingsymbol']} ({row['exchange']}) - Token: {row['instrument_token']}")

        return filtered_df

    def _process_single_instrument(self, row, current_index, total_instruments):
        """Process a single instrument to download historical data using backward pagination"""
        try:
            instrument_token = row["instrument_token"]
            tradingsymbol = row["tradingsymbol"]
            exchange = row["exchange"]
            instrument_type = row["instrument_type"]

            self.logger.info(
                f"Processing {current_index + 1}/{total_instruments}: {tradingsymbol} ({exchange} {instrument_type})"
            )

            # All instruments here already have valid names, so proceed directly with API call
            records_downloaded = self.download_historical_data_backward(instrument_token, tradingsymbol, exchange)

            if records_downloaded > 0:
                self.processing_stats["successful_instruments"] += 1
                self.logger.info(f"✓ SUCCESS: {tradingsymbol} - {records_downloaded:,} records")
            else:
                self.processing_stats["failed_instruments"] += 1
                self.processing_stats["failed_symbols"].append(tradingsymbol)
                self.logger.warning(f"⚠ FAILED: {tradingsymbol} - No records downloaded")

            self.processing_stats["processed_instruments"] += 1

            # Log stats more frequently for better monitoring
            stats_interval = 1 if total_instruments <= 5 else (2 if total_instruments <= 10 else 5)
            if (current_index + 1) % stats_interval == 0:
                self._log_processing_stats()

            return records_downloaded > 0

        except Exception as e:
            self.processing_stats["failed_instruments"] += 1
            self.processing_stats["processed_instruments"] += 1
            symbol = row.get("tradingsymbol", "Unknown")
            self.processing_stats["failed_symbols"].append(symbol)
            self.logger.exception(f"✗ ERROR processing {symbol}: {e}")
            return False

    def process_all_instruments(self, limit=None, test_symbols=None):
        """Process all instruments to download historical data using backward pagination"""
        try:
            instruments_df = self._load_instruments_from_csv()
            if instruments_df is None:
                return False

            if test_symbols:
                instruments_df = self._filter_test_symbols(instruments_df, test_symbols)
                if len(instruments_df) == 0:
                    self.logger.error(f"No instruments found for test symbols: {test_symbols}")
                    return False

            if limit:
                instruments_df = instruments_df.head(limit)
                self.logger.info(f"Processing limited to first {limit} instruments")

            total_instruments = len(instruments_df)
            self.processing_stats["total_instruments"] = total_instruments
            self.processing_stats["start_time"] = datetime.now()

            mode = "TEST MODE" if test_symbols else "FULL PROCESSING"

            self.logger.info("=" * 80)
            self.logger.info(f"STARTING {mode}: {total_instruments} INSTRUMENTS")
            if test_symbols:
                self.logger.info(f"TEST SYMBOLS: {test_symbols}")
            self.logger.info(f"PAGINATION CONFIG: {self.PAGINATION_CONFIG['days_per_batch']} days per batch")
            self.logger.info("=" * 80)

            for index, (_, row) in enumerate(instruments_df.iterrows()):
                self._process_single_instrument(row, index, total_instruments)

            self._log_processing_stats()

            success_rate = (
                (self.processing_stats["successful_instruments"] / total_instruments) * 100
                if total_instruments > 0
                else 0
            )
            self.logger.info("=" * 80)
            self.logger.info(f"{mode} COMPLETED - SUCCESS RATE: {success_rate:.1f}%")
            self.logger.info("=" * 80)

            return True

        except Exception as e:
            self.logger.exception(f"✗ Failed to process instruments: {e}")
            return False

    def run(self, test_mode=False, test_symbols=None, limit=None):
        """Main method to run the entire backward pagination process"""
        try:
            if test_mode and not test_symbols:
                test_symbols = ["RELIANCE", "HDFCBANK"]

            mode_info = "TEST MODE" if (test_mode or test_symbols) else "FULL PROCESSING"
            self.logger.info(f"🚀 Starting Kite Historical Data Downloader - {mode_info}")
            self.logger.info(f"📊 Backward Pagination: {self.PAGINATION_CONFIG['days_per_batch']} days per batch")

            if test_symbols:
                self.logger.info(f"🧪 Test symbols: {test_symbols}")

            if not self.authenticate_kite():
                self.logger.error("❌ Authentication failed. Exiting.")
                return False

            if not self.create_database_tables():
                self.logger.error("❌ Database setup failed. Exiting.")
                return False

            # ALWAYS download fresh instruments and save to DB
            self.logger.info("📥 Downloading fresh instruments from Kite API...")
            instruments = self.download_instruments()
            if not instruments:
                self.logger.error("❌ Failed to download instruments. Exiting.")
                return False

            self.logger.info("💾 Saving filtered instruments to database...")
            if not self.save_instruments_to_db(instruments):
                self.logger.error("❌ Failed to save instruments to database. Exiting.")
                return False

            if not self.process_all_instruments(limit=limit, test_symbols=test_symbols):
                self.logger.error("❌ Failed to process instruments. Exiting.")
                return False

            self.logger.info("🎉 Backward pagination historical data download process completed successfully!")
            return True

        except Exception as e:
            self.logger.exception(f"💥 Main process failed: {e}")
            return False


def main():
    """Main function with enhanced configuration for backward pagination"""

    # ============================================
    # CONFIGURATION - MODIFY THESE SETTINGS
    # ============================================

    # For testing with specific symbols (set to True)
    TEST_MODE = False

    # Custom test symbols (leave None to use default RELIANCE, HDFCBANK)
    CUSTOM_TEST_SYMBOLS = ["RELIANCE", "HDFCBANK"]  # or None for default

    # Limit number of instruments (None for no limit)
    LIMIT = None

    # ============================================

    downloader = KiteHistoricalDataDownloader()

    if TEST_MODE:
        print("=" * 60)
        print("🧪 RUNNING IN TEST MODE WITH BACKWARD PAGINATION")
        print("=" * 60)
        print("Features enabled:")
        print("✓ Fresh instrument download and filtering")
        print("✓ Only non-empty names processed")
        print("✓ Exchange + lot_size + name filtering")
        print("✓ Backward pagination (1800 days per batch)")
        print("=" * 60)

        success = downloader.run(test_mode=True, test_symbols=CUSTOM_TEST_SYMBOLS, limit=LIMIT)
    else:
        print("=" * 60)
        print("🏭 RUNNING FULL PROCESSING WITH BACKWARD PAGINATION")
        print("=" * 60)
        print("Features enabled:")
        print("✓ Fresh instrument download and filtering")
        print("✓ Only non-empty names processed")
        print("✓ Exchange + lot_size + name filtering")
        print("✓ Backward pagination (1800 days per batch)")
        print("-" * 60)
        print("Processing ONLY instruments with valid names")
        print("=" * 60)

        success = downloader.run(test_mode=False, limit=LIMIT)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
