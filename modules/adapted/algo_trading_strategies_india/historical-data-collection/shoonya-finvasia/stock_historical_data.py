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


#!/usr/bin/env python3
import argparse
import contextlib
import csv
import datetime
import io
import json
import os
import signal
import sys
import time
import traceback

import psycopg2
import psycopg2.extras  # For batch operations
import pyotp
import requests
from api_helper import ShoonyaApiPy

# ─ Shoonya API credentials ───────────────────────────────────
VENDOR_CODE = "YOUR_VENDOR_CODE"  # Provided by Finvasia
API_KEY = "your_api_key"  # Your API secret key
IMEI = "your_imei"  # Device identifier
USER_ID = "your_user_id"  # Your Shoonya user ID
PASSWORD = "your_password"  # Your login password
TOTP_SECRET = "your_totp_secret"  # From authenticator app (Google Authenticator

# ─ PostgreSQL connection details ──────────────────────────────
DB_PARAMS = {
    "dbname": "your_database_name",
    "user": "your_username",
    "password": "your_password",
    "host": "your_host",
    "port": 5432,
}

# ─ Input symbols files ─────────────────────────────────────────
NSE_SYMBOLS_FILE = "NSE_symbols.txt"
BSE_SYMBOLS_FILE = "BSE_symbols.txt"

# ─ Symbol processing configuration ─────────────────────────────
PROCESS_NSE = True  # Default value, can be overridden with command-line arguments
PROCESS_BSE = True  # Default value, can be overridden with command-line arguments

# ─ Batch and logging configuration ───────────────────────────────
BATCH_SIZE = 1000  # Number of records to insert in one batch
VERBOSE_LOGGING = True  # Set to False to reduce API response logging
MAX_LOG_ITEMS = 5  # Maximum number of records to display from API response
API_TIMEOUT = 10  # Timeout for API calls in seconds
STATUS_UPDATE_INTERVAL = 5  # How often to print status updates (seconds)

# ─ Enhanced error handling ─────────────────────────────
MAX_RETRIES = 3  # Increased from 3 to 5
MAX_API_RETRIES = 1  # Special higher retry count for API calls
API_RETRY_DELAY = 5  # Increased delay between API retries
DB_RETRY_DELAY = 8  # Longer delay for database retries
API_FAILURE_RATE_THRESHOLD = 10  # Number of consecutive failures before longer pause
MAX_CONSECUTIVE_FAILURES = 10  # Max consecutive failures before taking a longer break
FAILURE_RECOVERY_PAUSE = 10  # Pause for 5 minutes after hitting failure threshold
KEEP_RUNNING = True  # Global flag for script control

# ─ Global counters for stats ───────────────────────────────
success_count = 0
error_count = 0
skipped_count = 0
timeout_count = 0
retry_count = 0
total_records = 0
total_api_time = 0
total_db_time = 0
last_successful_symbol = ""
consecutive_failures = 0
last_status_time = time.time()

# Setup a checkpoint file for tracking progress
CHECKPOINT_FILE = "historical_data_checkpoint.txt"
PROGRESS_FILE = "historical_data_progress.json"


def parse_arguments():
    """Parse command-line arguments for script configuration"""
    parser = argparse.ArgumentParser(description="Historical Data Downloader for Shoonya API")
    parser.add_argument("--nse", action="store_true", help="Process NSE symbols only")
    parser.add_argument("--bse", action="store_true", help="Process BSE symbols only")
    parser.add_argument("--both", action="store_true", help="Process both NSE and BSE symbols (default)")
    parser.add_argument("--skip-download", action="store_true", help="Skip downloading symbol files (not recommended)")
    args = parser.parse_args()

    # Set the processing flags based on arguments
    global PROCESS_NSE, PROCESS_BSE

    # If no specific exchange is specified, or if --both is specified, process both
    if (not args.nse and not args.bse) or args.both:
        PROCESS_NSE = True
        PROCESS_BSE = True
    else:
        PROCESS_NSE = args.nse
        PROCESS_BSE = args.bse

    return args


# Create a robust print function
def safe_print(*args, **kwargs):
    """Thread-safe print function with timestamp that never fails"""
    try:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        print(f"[{timestamp}]", *args, **kwargs)
        sys.stdout.flush()  # Force flush to ensure output is written immediately
    except Exception as e:
        # Even if print fails, we don't want to crash
        try:
            with open("print_errors.log", "a") as f:
                f.write(f"Print error: {e!s}\n")
        except:
            pass  # If even error logging fails, just continue silently


def log_exception(prefix="EXCEPTION"):
    """Log the full exception traceback with prefix"""
    try:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        error_msg = f"\n[{timestamp}][{prefix}] {'=' * 60}\n"
        error_msg += traceback.format_exc()
        error_msg += f"\n[{timestamp}][{prefix}] {'=' * 60}\n"

        print(error_msg)
        sys.stdout.flush()

        # Also log to file for recovery purposes
        with open("error_log.txt", "a") as f:
            f.write(error_msg)
    except Exception as e:
        # If logging fails, try one more simple approach
        try:
            with open("emergency_error_log.txt", "a") as f:
                f.write(f"Error logging exception: {e!s}\n")
        except:
            pass  # Total silence if all fails


def write_checkpoint(stage):
    """Write a checkpoint to a file for recovery"""
    try:
        with open(CHECKPOINT_FILE, "a") as f:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{timestamp}] {stage}\n")
    except Exception as e:
        safe_print(f"Failed to write checkpoint: {e}")


def save_progress(all_symbols, current_index):
    """Save current progress for potential restart"""
    try:
        progress = {
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_symbols": len(all_symbols),
            "current_index": current_index,
            "success_count": success_count,
            "error_count": error_count,
            "skipped_count": skipped_count,
            "total_records": total_records,
            "last_successful_symbol": last_successful_symbol,
        }

        with open(PROGRESS_FILE, "w") as f:
            json.dump(progress, f, indent=2)
    except Exception as e:
        safe_print(f"Failed to save progress: {e}")


def signal_handler(sig, frame):
    """Handle CTRL+C and other termination signals with graceful shutdown"""
    global KEEP_RUNNING
    safe_print("\n[!] Received termination signal. Starting graceful shutdown...")
    safe_print("[!] This may take a moment to complete current operations.")
    KEEP_RUNNING = False
    time.sleep(1)  # Give a moment for operations to notice the flag change


# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def setup_database():
    """Setup database with optimized configuration for batch inserts"""
    max_retries = 5
    retry_delay = 10

    for retry in range(max_retries):
        try:
            safe_print(f"Setting up database connection (attempt {retry + 1}/{max_retries})...")
            conn = psycopg2.connect(**DB_PARAMS)
            conn.autocommit = True  # Setting autocommit to True

            with conn.cursor() as cur:
                # Create table if it doesn't exist
                cur.execute("""
                            CREATE TABLE IF NOT EXISTS z_shoonya_stock_historical_data
                            (
                                id         SERIAL PRIMARY KEY,
                                exchange   VARCHAR(10),
                                token      INTEGER,
                                symbol     VARCHAR(50),
                                event_time TIMESTAMP,
                                open       NUMERIC,
                                high       NUMERIC,
                                low        NUMERIC,
                                close      NUMERIC,
                                volume     NUMERIC
                            );
                            """)

                # Create regular index if it doesn't exist
                cur.execute("""
                            DO $$
                            BEGIN
                                IF NOT EXISTS (
                                    SELECT 1 FROM pg_indexes
                                    WHERE tablename = 'z_shoonya_stock_historical_data'
                                    AND indexname = 'z_shoonya_stock_historical_data_symbol_event_time_idx'
                                ) THEN
                                    CREATE INDEX z_shoonya_stock_historical_data_symbol_event_time_idx
                                    ON z_shoonya_stock_historical_data(symbol, event_time);
                                END IF;
                            END
                            $$;
                            """)

                # Check if unique index exists
                cur.execute("""
                            SELECT 1
                            FROM pg_indexes
                            WHERE tablename = 'z_shoonya_stock_historical_data'
                              AND indexname = 'z_shoonya_stock_historical_data_unique_idx'
                            """)
                unique_index_exists = cur.fetchone() is not None

                # Create unique index concurrently if it doesn't exist
                if not unique_index_exists:
                    safe_print("Creating unique index concurrently - this may take some time...")
                    # This needs to be run outside a transaction
                    cur.execute("""
                                CREATE UNIQUE INDEX CONCURRENTLY z_shoonya_stock_historical_data_unique_idx
                                    ON z_shoonya_stock_historical_data (exchange, symbol, event_time);
                                """)
                    safe_print("Unique index created successfully.")

                # Disable triggers temporarily for faster inserts
                cur.execute("ALTER TABLE z_shoonya_stock_historical_data DISABLE TRIGGER ALL;")

                # Set table storage parameters for faster inserts
                cur.execute("""
                            ALTER TABLE z_shoonya_stock_historical_data
                                SET (autovacuum_enabled = false, toast.autovacuum_enabled = false);
                            """)

            safe_print("Database prepared for high-speed inserts.")
            return conn

        except Exception as e:
            safe_print(f"Database setup error (attempt {retry + 1}/{max_retries}): {e}")
            log_exception("DB_SETUP")

            if retry < max_retries - 1:
                safe_print(f"Retrying database setup in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                safe_print("All database setup attempts failed!")
                # Instead of exiting, we'll return None and handle it in the main function
                return None
    return None


def cleanup_database(conn):
    """Re-enable triggers and reset table parameters"""
    if conn is None:
        safe_print("No database connection to clean up.")
        return

    try:
        safe_print("Restoring database to normal operation...")
        with conn.cursor() as cur:
            # Re-enable triggers
            cur.execute("ALTER TABLE z_shoonya_stock_historical_data ENABLE TRIGGER ALL;")

            # Reset table storage parameters
            cur.execute("""
                        ALTER TABLE z_shoonya_stock_historical_data
                            SET (autovacuum_enabled = true, toast.autovacuum_enabled = true);
                        """)

            # Run ANALYZE to update statistics
            cur.execute("ANALYZE z_shoonya_stock_historical_data;")

        safe_print("Database restored to normal operation.")
    except Exception as e:
        safe_print(f"Database cleanup warning (non-fatal): {e}")
        log_exception("DB_CLEANUP_WARNING")
    finally:
        # Close connection
        try:
            conn.close()
            safe_print("Database connection closed.")
        except Exception as e:
            safe_print(f"Error closing database connection (non-fatal): {e}")


def parse_csv_symbols(file_path, exchange):
    """Read CSV and return list of {'exchange','token','symbol'} for specified exchange.
    For NSE, only process 'EQ' instruments.
    For BSE, process all instruments except 'F'."""

    symbols = []
    safe_print(f"Reading symbols from {file_path} for {exchange}...")

    # Handle missing file with more resilience
    retry_count = 0
    max_retries = 3

    while retry_count < max_retries:
        if not os.path.exists(file_path):
            safe_print(f"WARNING: Symbol file {file_path} not found (attempt {retry_count + 1}/{max_retries}).")

            # Try to download the file
            if download_symbols():
                safe_print("Successfully downloaded symbol files, retrying...")
            else:
                safe_print("Failed to download symbol files. Waiting before retry...")
                time.sleep(30)  # Wait before retry

            retry_count += 1
            continue

        # File exists, try to process it
        try:
            with open(file_path, newline="", encoding="utf-8-sig") as csvfile:
                # Try to detect dialect
                sample = csvfile.read(1024)
                csvfile.seek(0)

                try:
                    dialect = csv.Sniffer().sniff(sample)
                except:
                    safe_print("Failed to detect CSV dialect, using default.")
                    dialect = csv.excel

                reader = csv.DictReader(csvfile, dialect=dialect)

                # Check if required columns exist
                header = reader.fieldnames
                if not header:
                    safe_print(f"ERROR: Could not read header from {file_path}")
                    return []

                required_cols = ["Token", "TradingSymbol"]
                if exchange == "NSE":
                    required_cols.append("Instrument")

                missing_cols = [col for col in required_cols if col not in header]
                if missing_cols:
                    safe_print(f"ERROR: Missing required columns in {file_path}: {missing_cols}")
                    safe_print(f"Found columns: {header}")
                    return []

                for row in reader:
                    instrument = row.get("Instrument", "")

                    # Different processing logic based on exchange
                    if exchange == "NSE":
                        # For NSE, only include EQ instruments
                        if instrument == "EQ":
                            trading_symbol = row["TradingSymbol"]
                            # Remove -EQ suffix if present
                            symbol = (
                                trading_symbol.replace("-EQ", "") if trading_symbol.endswith("-EQ") else trading_symbol
                            )

                            try:
                                token = int(row["Token"])
                                symbols.append({"exchange": "NSE", "token": token, "symbol": symbol})
                            except ValueError:
                                safe_print(
                                    f"WARNING: Invalid token in {file_path}: {row['Token']} for symbol {trading_symbol}"
                                )

                    elif exchange == "BSE":
                        # For BSE, include all instruments except 'F'
                        if instrument != "F":
                            try:
                                token = int(row["Token"])
                                symbols.append({"exchange": "BSE", "token": token, "symbol": row["TradingSymbol"]})
                            except ValueError:
                                safe_print(
                                    f"WARNING: Invalid token in {file_path}: {row['Token']} for symbol {row['TradingSymbol']}"
                                )

            # If we get here, we've successfully processed the file
            break

        except Exception as e:
            safe_print(f"ERROR parsing symbols file {file_path} (attempt {retry_count + 1}/{max_retries}): {e}")
            log_exception(f"PARSE_{exchange}")
            retry_count += 1

            if retry_count < max_retries:
                time.sleep(10)  # Wait before retry
            else:
                safe_print(f"Failed to parse symbols after {max_retries} attempts. Returning empty list.")
                return []

    # Log some sample symbols for verification
    if symbols:
        safe_print(f"Loaded {len(symbols)} symbols from {exchange} for processing.")
        safe_print(f"Sample symbols from {exchange}:")
        for i, sym in enumerate(symbols[:5]):
            safe_print(f"  {i + 1}. {sym['symbol']} (Token: {sym['token']})")
        if len(symbols) > 5:
            safe_print(f"  ... and {len(symbols) - 5} more symbols")
    else:
        safe_print(f"WARNING: No valid symbols found in {file_path}!")

    return symbols


def fetch_symbol_data(api, symbol_data, index, total_symbols, conn):
    """Fetch data for a single symbol and insert directly into database"""
    global success_count, error_count, skipped_count, timeout_count, retry_count
    global total_records, total_api_time, total_db_time, last_successful_symbol, consecutive_failures, KEEP_RUNNING

    # Check if we should continue processing
    if not KEEP_RUNNING:
        return False

    # Check if we're in the API reset window
    current_time = datetime.datetime.now()

    # Determine timezone and set appropriate reset window
    # Try to detect timezone automatically
    timezone_str = time.strftime("%Z", time.localtime())

    # Define reset windows based on timezone
    if timezone_str in ["SGT", "+08"]:  # Singapore timezone
        reset_start_hour = 8
        reset_end_hour = 11
        reset_end_minute = 30
        timezone_name = "SGT"
    else:  # Default to IST
        reset_start_hour = 5
        reset_end_hour = 9
        reset_end_minute = 0
        timezone_name = "IST"

    # Check if current time is in the reset window
    in_reset_window = (
        current_time.hour > reset_start_hour or (current_time.hour == reset_start_hour and current_time.minute >= 0)
    ) and (
        current_time.hour < reset_end_hour
        or (current_time.hour == reset_end_hour and current_time.minute < reset_end_minute)
    )

    if in_reset_window:
        # Calculate time until reset window ends
        if current_time.hour < reset_end_hour:
            wait_hours = reset_end_hour - current_time.hour
            wait_minutes = reset_end_minute - current_time.minute
        else:  # Same hour, waiting for minutes
            wait_hours = 0
            wait_minutes = reset_end_minute - current_time.minute

        if wait_minutes < 0:
            wait_hours -= 1
            wait_minutes += 60

        wait_seconds = wait_hours * 3600 + wait_minutes * 60

        # Log the wait
        safe_print(
            f"[API RESET] Currently in API reset window ({timezone_name}): {current_time.hour:02}:{current_time.minute:02}"
        )
        safe_print(
            f"[API RESET] Pausing operations for {wait_hours}h {wait_minutes}m until {reset_end_hour:02}:{reset_end_minute:02}"
        )

        # Only wait if we need to wait more than 1 minute
        if wait_seconds > 60:
            # Wait in 5-minute increments, checking KEEP_RUNNING flag
            for i in range(0, wait_seconds, 300):  # 300 seconds = 5 minutes
                if not KEEP_RUNNING:
                    return False

                remaining = wait_seconds - i
                if remaining > 300:
                    safe_print(
                        f"[API RESET] Still waiting... {remaining // 3600}h {(remaining % 3600) // 60}m remaining"
                    )
                    time.sleep(300)
                else:
                    safe_print(f"[API RESET] Final wait of {remaining // 60}m {remaining % 60}s")
                    time.sleep(remaining)
                    break

        safe_print("[API RESET] Reset window passed. Resuming operations.")

    exch = symbol_data["exchange"]  # This will be 'NSE' or 'BSE'
    sym = symbol_data["symbol"]  # Symbol without suffix for NSE, original symbol for BSE
    token = symbol_data["token"]

    # For API call, we need to handle exchange-specific formatting
    api_symbol = sym
    if exch == "NSE" and not sym.endswith("-EQ"):
        api_symbol = f"{sym}-EQ"

    progress = f"[{index + 1}/{total_symbols}]"

    try:
        safe_print(f"{progress} Processing {exch}:{sym} (Token: {token})...")
        api_retry_count = 0
        api_data = None

        while api_retry_count < MAX_API_RETRIES and KEEP_RUNNING:
            # Check for too many consecutive failures
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                safe_print(
                    f"WARNING: Hit {consecutive_failures} consecutive failures. Taking a break for {FAILURE_RECOVERY_PAUSE / 60} minutes..."
                )
                time.sleep(FAILURE_RECOVERY_PAUSE)
                consecutive_failures = 0  # Reset counter after pause

            # API request
            try:
                safe_print(
                    f"{progress} Fetching data from Shoonya API for {exch}:{sym} (Attempt {api_retry_count + 1}/{MAX_API_RETRIES})..."
                )
                req_start = time.time()

                start_ts = 0  # 1 Jan 1970
                end_ts = int(time.time())  # now

                # Make API call with timeout awareness
                api_data = api.get_daily_price_series(
                    exchange=exch, tradingsymbol=api_symbol, startdate=str(start_ts), enddate=str(end_ts)
                )

                req_time = time.time() - req_start
                total_api_time += req_time

                # Handle empty response
                if not api_data:
                    safe_print(f"{progress} No data received for {exch}:{sym} after {req_time:.2f}s.")
                    skipped_count += 1
                    consecutive_failures = 0  # Reset on empty data (not an error)
                    return True  # Still return success to move to next symbol

                safe_print(f"{progress} Received {len(api_data)} records in {req_time:.2f}s.")
                consecutive_failures = 0  # Reset counter on success
                last_successful_symbol = f"{exch}:{sym}"
                break  # Break out of retry loop on success

            except Exception as e:
                req_time = time.time() - req_start if "req_start" in locals() else 0
                api_retry_count += 1
                retry_count += 1
                consecutive_failures += 1

                # Check if it's a connection refused error, which might indicate API reset
                if "Connection refused" in str(e):
                    safe_print(f"{progress} CONNECTION REFUSED ERROR - possibly in API reset period. Checking time...")

                    # Re-check if we entered a reset window
                    current_time = datetime.datetime.now()
                    in_reset_window = (
                        current_time.hour > reset_start_hour
                        or (current_time.hour == reset_start_hour and current_time.minute >= 0)
                    ) and (
                        current_time.hour < reset_end_hour
                        or (current_time.hour == reset_end_hour and current_time.minute < reset_end_minute)
                    )

                    if in_reset_window:
                        safe_print(
                            f"{progress} We are now in the API reset window. Pausing this symbol and will resume after reset period."
                        )
                        # Set this to max retries to skip this symbol and move to next
                        api_retry_count = MAX_API_RETRIES
                        continue

                safe_print(
                    f"{progress} API CALL ERROR for {exch}:{sym} after {req_time:.2f}s: {e!s} (Attempt {api_retry_count}/{MAX_API_RETRIES})"
                )

                if api_retry_count < MAX_API_RETRIES and KEEP_RUNNING:
                    # Calculate adaptive retry delay based on consecutive failures
                    adaptive_delay = API_RETRY_DELAY * min(10, consecutive_failures)
                    safe_print(f"{progress} Retrying {exch}:{sym} in {adaptive_delay}s...")
                    time.sleep(adaptive_delay)
                else:
                    log_exception(f"API_{exch}_{sym}")
                    error_count += 1
                    return True  # Return True to move to the next symbol even on error

        # Handle case where we exhausted all retries
        if api_retry_count >= MAX_API_RETRIES:
            safe_print(
                f"{progress} FAILED to fetch data for {exch}:{sym} after {MAX_API_RETRIES} attempts. Skipping symbol."
            )
            error_count += 1
            return True

        # If no data after retries, skip this symbol
        if not api_data:
            safe_print(f"{progress} No valid data for {exch}:{sym} after all retries. Skipping symbol.")
            skipped_count += 1
            return True

        # Log API response data for debugging
        if VERBOSE_LOGGING:
            safe_print(f"{progress} API Response Sample (showing max {MAX_LOG_ITEMS} of {len(api_data)} records):")
            sample_data = api_data[:MAX_LOG_ITEMS]
            for i, item in enumerate(sample_data):
                if isinstance(item, str):
                    with contextlib.suppress(BaseException):
                        item = json.loads(item)
                safe_print(f"  Record {i + 1}: {json.dumps(item, indent=2)}")

            if len(api_data) > MAX_LOG_ITEMS:
                safe_print(f"  ... and {len(api_data) - MAX_LOG_ITEMS} more records")

        # Prepare data for insertion
        batch_data = []
        for rec in api_data:
            if isinstance(rec, str):
                try:
                    rec = json.loads(rec)
                except Exception as e:
                    safe_print(f"{progress} Error parsing JSON response: {e}")
                    safe_print(f"Problematic record: {rec}")
                    continue

            # Parse fields
            try:
                evt_time = datetime.datetime.fromtimestamp(int(rec["ssboe"]))
                batch_data.append(
                    {
                        "exchange": exch,
                        "token": token,
                        "symbol": sym,
                        "event_time": evt_time,
                        "open": rec["into"],
                        "high": rec["inth"],
                        "low": rec["intl"],
                        "close": rec["intc"],
                        "volume": rec["intv"],
                    }
                )
            except KeyError as e:
                safe_print(f"{progress} Missing key in API response: {e}")
                safe_print(f"Problem record structure: {rec}")
                continue
            except Exception as e:
                safe_print(f"{progress} Error processing record: {e}")
                safe_print(f"Problem record: {rec}")
                continue

        # Check if we have any valid records after processing
        if not batch_data:
            safe_print(f"{progress} No valid records after processing API data for {exch}:{sym}. Skipping insertion.")
            skipped_count += 1
            return True

        safe_print(
            f"{progress} Successfully processed {len(batch_data)} of {len(api_data)} records for database insertion"
        )

        # Now insert the data with retry logic
        db_retry_count = 0
        insertion_success = False

        while db_retry_count < MAX_RETRIES and not insertion_success and KEEP_RUNNING:
            try:
                # Handle potential database connection issues
                if conn is None or conn.closed:
                    safe_print(f"{progress} Database connection is None or closed. Attempting to reconnect...")
                    try:
                        conn = psycopg2.connect(**DB_PARAMS)
                        conn.autocommit = False
                        safe_print(f"{progress} Successfully reconnected to database.")
                    except Exception as e:
                        safe_print(f"{progress} Failed to reconnect to database: {e}")
                        db_retry_count += 1
                        time.sleep(DB_RETRY_DELAY)
                        continue

                safe_print(
                    f"{progress} Inserting {len(batch_data)} records into database (Attempt {db_retry_count + 1}/{MAX_RETRIES})..."
                )
                db_start = time.time()

                # Process in batches for better performance
                records_inserted = 0
                for i in range(0, len(batch_data), BATCH_SIZE):
                    if not KEEP_RUNNING:
                        break

                    batch = batch_data[i : i + BATCH_SIZE]
                    if not batch:
                        continue

                    try:
                        # Create a new cursor for each batch
                        with conn.cursor() as cur:
                            # Use executemany for efficient batch insert
                            psycopg2.extras.execute_batch(
                                cur,
                                """
                                INSERT INTO z_shoonya_stock_historical_data
                                    (exchange, token, symbol, event_time, open, high, low, close, volume)
                                VALUES (%(exchange)s, %(token)s, %(symbol)s, %(event_time)s, %(open)s,
                                        %(high)s, %(low)s, %(close)s, %(volume)s)
                                ON CONFLICT DO NOTHING;
                                """,
                                batch,
                            )

                        # Commit after each batch
                        conn.commit()
                        records_inserted += len(batch)

                    except Exception as e:
                        safe_print(f"{progress} Error inserting batch {i // BATCH_SIZE + 1}: {e}")
                        # Try to recover
                        with contextlib.suppress(BaseException):
                            conn.rollback()

                        raise  # Re-raise to trigger outer retry

                db_time = time.time() - db_start
                total_db_time += db_time

                # Update stats
                total_records += records_inserted

                safe_print(
                    f"{progress} Successfully inserted {records_inserted}/{len(batch_data)} records in {db_time:.2f}s"
                )
                insertion_success = True

            except Exception as e:
                safe_print(f"{progress} Database insertion error: {e}")
                log_exception(f"DB_{exch}_{sym}")

                db_retry_count += 1
                if db_retry_count < MAX_RETRIES and KEEP_RUNNING:
                    safe_print(
                        f"{progress} Retrying database insertion in {DB_RETRY_DELAY}s (Attempt {db_retry_count}/{MAX_RETRIES})..."
                    )
                    time.sleep(DB_RETRY_DELAY)
                else:
                    safe_print(f"{progress} Failed to insert data after {MAX_RETRIES} attempts.")

        # Record success or failure
        if insertion_success:
            success_count += 1
            return True
        error_count += 1
        return True  # Still return True to move to the next symbol

    except Exception as e:
        safe_print(f"{progress} UNHANDLED ERROR for {exch}:{sym}: {e!s}")
        log_exception(f"UNHANDLED_{exch}_{sym}")
        error_count += 1
        consecutive_failures += 1
        return True  # Return True to continue with next symbol despite error


def download_symbols():
    """Download and extract symbol files if they don't exist. This is always attempted
    regardless of whether the files exist or not, as per requirements."""
    safe_print("Downloading symbol files...")

    try:
        # Try to import the download_symbols module
        try:
            import download_symbols

            safe_print("Found download_symbols.py module. Using it to download symbol files...")
            result = download_symbols.main()
            if result == 0:
                safe_print("Symbol files downloaded successfully using download_symbols.py")
                return True
            safe_print("download_symbols.py failed. Trying built-in download method...")
        except ImportError:
            safe_print("download_symbols.py not found. Using built-in download method...")

        # Import locally to avoid dependency if files already exist
        import zipfile

        import requests

        exchanges = ["NSE", "BSE"]
        for exchange in exchanges:
            url = f"https://api.shoonya.com/{exchange}_symbols.txt.zip"
            filename = f"{exchange}_symbols.txt.zip"

            retry_count = 0
            max_retries = 3

            while retry_count < max_retries:
                try:
                    safe_print(f"Downloading {url} (attempt {retry_count + 1}/{max_retries})...")
                    response = requests.get(url, stream=True, timeout=60)
                    response.raise_for_status()

                    with open(filename, "wb") as f:
                        f.writelines(response.iter_content(chunk_size=8192))

                    safe_print(f"Extracting {filename}...")
                    with zipfile.ZipFile(filename, "r") as zip_ref:
                        zip_ref.extractall(".")

                    # Clean up zip file
                    try:
                        os.remove(filename)
                    except:
                        safe_print(f"Warning: Could not remove zip file {filename}")

                    # Verify the file was extracted
                    if not os.path.exists(f"{exchange}_symbols.txt"):
                        safe_print(f"Error: Failed to extract {exchange}_symbols.txt")
                        retry_count += 1
                        if retry_count < max_retries:
                            time.sleep(10)
                        continue

                    safe_print(f"Successfully downloaded and extracted {exchange}_symbols.txt")
                    break  # Exit retry loop on success

                except Exception as e:
                    safe_print(f"Error downloading {exchange} symbols (attempt {retry_count + 1}/{max_retries}): {e}")
                    retry_count += 1
                    if retry_count < max_retries:
                        time.sleep(30)  # Longer delay between retries
                    else:
                        safe_print(f"Failed to download {exchange} symbols after {max_retries} attempts.")
                        return False

        # Check if all files were successfully downloaded
        for exchange in exchanges:
            if not os.path.exists(f"{exchange}_symbols.txt"):
                safe_print(f"Error: Failed to download {exchange}_symbols.txt after multiple attempts.")
                return False

        return True

    except Exception as e:
        safe_print(f"Error in download_symbols function: {e}")
        log_exception("SYMBOL_DOWNLOAD")
        return False


def display_status_update(start_time, total_symbols):
    """Display a status update with progress information"""
    global last_status_time

    current_time = time.time()
    elapsed = current_time - start_time

    # Only update status every STATUS_UPDATE_INTERVAL seconds
    if current_time - last_status_time < STATUS_UPDATE_INTERVAL:
        return

    last_status_time = current_time

    current_count = success_count + error_count + skipped_count + timeout_count

    safe_print("\n--- STATUS UPDATE ---")
    safe_print(f"Processed {current_count}/{total_symbols} symbols ({current_count / total_symbols * 100:.1f}%)")
    safe_print(
        f"Success: {success_count}, Errors: {error_count}, Skipped: {skipped_count}, Timeouts: {timeout_count}, Retries: {retry_count}"
    )
    safe_print(f"Current symbol: {last_successful_symbol}")
    safe_print(f"Total records inserted: {total_records}")
    safe_print(f"Time elapsed: {elapsed:.1f}s")
    if current_count > 0 and elapsed > 0:
        safe_print(f"Avg API time: {total_api_time / max(1, current_count):.2f}s per symbol")
        safe_print(f"Avg DB time: {total_db_time / max(1, success_count):.2f}s per symbol")
        safe_print(f"Estimated time remaining: {elapsed / current_count * (total_symbols - current_count):.1f}s")
    safe_print(f"Processing rate: {current_count / max(1, elapsed):.2f} symbols/second")
    safe_print(f"Insertion rate: {total_records / max(1, elapsed):.2f} records/second")
    safe_print(f"Consecutive failures: {consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}")
    safe_print("---------------------")


def load_checkpoint():
    """Try to load previous progress to resume from where we left off"""
    try:
        if os.path.exists(PROGRESS_FILE):
            with open(PROGRESS_FILE) as f:
                progress = json.load(f)

            safe_print(f"Found previous progress from {progress.get('timestamp', 'unknown time')}:")
            safe_print(f"  Processed {progress.get('current_index', 0)}/{progress.get('total_symbols', 0)} symbols")
            safe_print(f"  Success: {progress.get('success_count', 0)}, Errors: {progress.get('error_count', 0)}")
            safe_print(f"  Records inserted: {progress.get('total_records', 0)}")

            return progress.get("current_index", 0)
    except Exception as e:
        safe_print(f"Error loading checkpoint (will start from beginning): {e}")

    return 0  # Default to starting from the beginning


def main():
    global KEEP_RUNNING, success_count, error_count, skipped_count, total_records, PROCESS_NSE, PROCESS_BSE

    # Parse command-line arguments
    args = parse_arguments()

    # Display configuration
    safe_print("Configuration:")
    safe_print(f"  Process NSE: {PROCESS_NSE}")
    safe_print(f"  Process BSE: {PROCESS_BSE}")
    safe_print(f"  Skip symbol download: {args.skip_download}")

    # Check if we're in the API reset window
    current_time = datetime.datetime.now()

    # Determine timezone and set appropriate reset window
    timezone_str = time.strftime("%Z", time.localtime())

    # Define reset windows based on timezone
    if timezone_str in ["SGT", "+08"]:  # Singapore timezone
        reset_start_hour = 8
        reset_end_hour = 11
        reset_end_minute = 30
        timezone_name = "SGT"
    else:  # Default to IST
        reset_start_hour = 5
        reset_end_hour = 9
        reset_end_minute = 0
        timezone_name = "IST"

    # Check if current time is in the reset window
    in_reset_window = (current_time.hour >= reset_start_hour) and (
        current_time.hour < reset_end_hour
        or (current_time.hour == reset_end_hour and current_time.minute < reset_end_minute)
    )

    if in_reset_window:
        # Calculate time until reset window ends
        if current_time.hour < reset_end_hour:
            wait_hours = reset_end_hour - current_time.hour
            wait_minutes = reset_end_minute - current_time.minute
        else:  # Same hour, waiting for minutes
            wait_hours = 0
            wait_minutes = reset_end_minute - current_time.minute

        if wait_minutes < 0:
            wait_hours -= 1
            wait_minutes += 60

        wait_seconds = wait_hours * 3600 + wait_minutes * 60

        # Log the wait
        safe_print(
            f"\n[API RESET] Script started during API reset window ({timezone_name}): {current_time.hour:02}:{current_time.minute:02}"
        )
        safe_print(
            f"[API RESET] Pausing operations for {wait_hours}h {wait_minutes}m until {reset_end_hour:02}:{reset_end_minute:02}"
        )

        # Only wait if we need to wait more than 1 minute
        if wait_seconds > 60:
            # Wait in 5-minute increments, checking KEEP_RUNNING flag
            for i in range(0, wait_seconds, 300):  # 300 seconds = 5 minutes
                if not KEEP_RUNNING:
                    return

                remaining = wait_seconds - i
                if remaining > 300:
                    safe_print(
                        f"[API RESET] Still waiting... {remaining // 3600}h {(remaining % 3600) // 60}m remaining"
                    )
                    time.sleep(300)
                else:
                    safe_print(f"[API RESET] Final wait of {remaining // 60}m {remaining % 60}s")
                    time.sleep(remaining)
                    break

        safe_print("[API RESET] Reset window passed. Starting operations.")

    # Clear the checkpoint file to start fresh
    try:
        with open(CHECKPOINT_FILE, "w") as f:
            f.write("")  # Empty the file
    except Exception as e:
        safe_print(f"Warning: Could not clear checkpoint file: {e}")

    # 0) Print startup banner
    safe_print("\n" + "=" * 80)
    safe_print("STARTING HISTORICAL DATA DOWNLOAD (SINGLE-THREADED, MAX RESILIENCE)")
    safe_print("=" * 80)
    start_time = time.time()

    write_checkpoint("Script started")

    # Try to check if we should resume from a previous run
    start_index = load_checkpoint()

    # 1) Always download symbol files first
    safe_print("\n[1/6] Downloading symbol files...")
    if not args.skip_download:
        if not download_symbols():
            safe_print("Warning: Problems downloading symbol files. Will continue but may encounter issues.")
    else:
        safe_print("Symbol file download skipped as requested.")

    write_checkpoint("Symbol files verification completed")

    # 2) Generate TOTP using original logic
    try:
        safe_print("\n[2/6] Generating TOTP authentication code...")
        totp = pyotp.TOTP(TOTP_SECRET)
        current_totp = totp.now()
        safe_print(f"Generated TOTP: {current_totp}")
        write_checkpoint("TOTP generated")
    except Exception as e:
        safe_print(f"Error generating TOTP: {e}")
        log_exception("TOTP")
        sys.exit(1)

    # 3) Login to Shoonya using original logic
    try:
        safe_print("\n[3/6] Logging into Shoonya API...")
        api = ShoonyaApiPy()
        api.debug = True  # Enable debug mode to see more API response details

        login_ret = api.login(
            userid=USER_ID,
            password=PASSWORD,
            twoFA=current_totp,
            vendor_code=VENDOR_CODE,
            api_secret=API_KEY,
            imei=IMEI,
        )
        safe_print(f"Login response: {json.dumps(login_ret, indent=2)}")

        if "stat" in login_ret and login_ret["stat"] != "Ok":
            safe_print(f"Login failed: {login_ret.get('emsg', 'Unknown error')}")
            sys.exit(1)
        safe_print("Login successful.")
        write_checkpoint("API login successful")
    except Exception as e:
        safe_print(f"Error during login: {e}")
        log_exception("LOGIN")
        sys.exit(1)

    # 4) Setup database with optimized configuration
    safe_print("\n[4/6] Setting up optimized database connection...")
    db_conn = setup_database()

    if db_conn is None:
        safe_print("Warning: Could not establish initial database connection.")
        safe_print("Will attempt to connect during processing...")

    write_checkpoint("Database setup attempted")

    # 5) Load symbols based on configuration
    safe_print("\n[5/6] Loading symbols based on configuration...")

    nse_symbols = []
    bse_symbols = []

    if PROCESS_NSE:
        safe_print("Loading NSE symbols...")
        nse_symbols = parse_csv_symbols(NSE_SYMBOLS_FILE, "NSE")

    if PROCESS_BSE:
        safe_print("Loading BSE symbols...")
        bse_symbols = parse_csv_symbols(BSE_SYMBOLS_FILE, "BSE")

    write_checkpoint("Symbols loaded")

    # Combine symbols from selected exchanges
    all_symbols = []
    if PROCESS_NSE:
        all_symbols.extend(nse_symbols)
    if PROCESS_BSE:
        all_symbols.extend(bse_symbols)

    safe_print(
        f"Total symbols to process: {len(all_symbols)} (NSE: {len(nse_symbols) if PROCESS_NSE else 0}, BSE: {len(bse_symbols) if PROCESS_BSE else 0})"
    )

    if not all_symbols:
        safe_print("No symbols found to process! Exiting.")
        if db_conn:
            cleanup_database(db_conn)
        with contextlib.suppress(BaseException):
            api.logout()
        return

    # Uncomment to limit processing to a subset for testing
    # max_symbols = 10
    # if len(all_symbols) > max_symbols:
    #     safe_print(f"NOTE: Limiting processing to first {max_symbols} symbols for testing")
    #     all_symbols = all_symbols[:max_symbols]

    # If we're resuming, we need to set the counters based on our progress
    if start_index > 0:
        if start_index < len(all_symbols):
            safe_print(f"Resuming from symbol {start_index + 1}/{len(all_symbols)}")
            # Keep only the remaining symbols
            all_symbols = all_symbols[start_index:]
        else:
            safe_print(f"Previous run already processed all {len(all_symbols)} symbols.")
            safe_print("Nothing more to do. Exiting.")
            if db_conn:
                cleanup_database(db_conn)
            with contextlib.suppress(BaseException):
                api.logout()
            return

    # 6) Process symbols - single-threaded for maximum reliability
    safe_print(f"\n[6/6] Beginning data download for {len(all_symbols)} symbols (single-threaded)...")
    write_checkpoint("Starting symbol processing")

    # Process each symbol one at a time
    for i, symbol_data in enumerate(all_symbols):
        if not KEEP_RUNNING:
            safe_print("Script termination requested. Stopping processing.")
            break

        # Check if we've entered the API reset window during processing
        current_time = datetime.datetime.now()
        in_reset_window = (current_time.hour >= reset_start_hour) and (
            current_time.hour < reset_end_hour
            or (current_time.hour == reset_end_hour and current_time.minute < reset_end_minute)
        )

        if in_reset_window:
            # Calculate time until reset window ends
            if current_time.hour < reset_end_hour:
                wait_hours = reset_end_hour - current_time.hour
                wait_minutes = reset_end_minute - current_time.minute
            else:  # Same hour, waiting for minutes
                wait_hours = 0
                wait_minutes = reset_end_minute - current_time.minute

            if wait_minutes < 0:
                wait_hours -= 1
                wait_minutes += 60

            wait_seconds = wait_hours * 3600 + wait_minutes * 60

            # Log the wait
            safe_print(
                f"\n[API RESET] Entered API reset window during processing ({timezone_name}): {current_time.hour:02}:{current_time.minute:02}"
            )
            safe_print(
                f"[API RESET] Pausing operations for {wait_hours}h {wait_minutes}m until {reset_end_hour:02}:{reset_end_minute:02}"
            )

            # Wait in 5-minute increments, checking KEEP_RUNNING flag
            for j in range(0, wait_seconds, 300):  # 300 seconds = 5 minutes
                if not KEEP_RUNNING:
                    break

                remaining = wait_seconds - j
                if remaining > 300:
                    safe_print(
                        f"[API RESET] Still waiting... {remaining // 3600}h {(remaining % 3600) // 60}m remaining"
                    )
                    time.sleep(300)
                else:
                    safe_print(f"[API RESET] Final wait of {remaining // 60}m {remaining % 60}s")
                    time.sleep(remaining)
                    break

            safe_print("[API RESET] Reset window passed. Resuming operations.")

        # Show status periodically
        display_status_update(start_time, len(all_symbols))

        # Process symbol with maximum error resilience
        try:
            fetch_symbol_data(api, symbol_data, i, len(all_symbols), db_conn)

            # Save progress after each symbol
            if (i + 1) % 10 == 0 or i == len(all_symbols) - 1:
                save_progress(all_symbols, start_index + i + 1)

        except Exception as e:
            safe_print(f"Unhandled error processing symbol {i + 1}/{len(all_symbols)}: {e}")
            log_exception("SYMBOL_PROCESSING")
            # Continue to next symbol despite errors
            error_count += 1

        # Small delay between symbols to avoid overwhelming the API
        time.sleep(0.5)

    write_checkpoint("Finished processing symbols")

    # Final cleanup
    safe_print("\nFinalizing and cleaning up...")

    if db_conn:
        try:
            cleanup_database(db_conn)
        except Exception as e:
            safe_print(f"Error during database cleanup (non-fatal): {e}")

    try:
        api.logout()
        safe_print("Logged out from Shoonya API.")
    except Exception as e:
        safe_print(f"Error during API logout (non-fatal): {e}")

    # Final statistics
    total_time = time.time() - start_time
    safe_print("\n" + "=" * 80)
    safe_print("DOWNLOAD SUMMARY")
    safe_print("=" * 80)
    safe_print(f"Exchanges processed: {', '.join([e for e, f in [('NSE', PROCESS_NSE), ('BSE', PROCESS_BSE)] if f])}")
    safe_print(f"Total symbols processed: {success_count + error_count + skipped_count}")
    safe_print(f"Success: {success_count}, Errors: {error_count}, Skipped: {skipped_count}, Retries: {retry_count}")
    safe_print(f"Total records inserted: {total_records}")
    safe_print(f"Total execution time: {total_time:.2f}s")
    safe_print(f"API fetch time: {total_api_time:.2f}s")
    safe_print(f"Database insert time: {total_db_time:.2f}s")

    if success_count > 0:
        safe_print(f"Average time per symbol: {total_time / (success_count + error_count + skipped_count):.2f}s")
        safe_print(f"Average records per successful symbol: {total_records / success_count:.2f}")

    safe_print(
        f"Overall processing rate: {(success_count + error_count + skipped_count) / max(1, total_time):.2f} symbols/second"
    )
    safe_print(f"Overall insertion rate: {total_records / max(1, total_time):.2f} records/second")
    safe_print("=" * 80)

    write_checkpoint("Script completed successfully")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        safe_print(f"Critical error in main function: {e}")
        log_exception("MAIN")

        # Even for critical errors, try to restart
        safe_print("Attempting to restart after critical error...")
        time.sleep(60)  # Wait before restart
        try:
            main()  # Try again
        except Exception as e2:
            safe_print(f"Second critical error in main function: {e2}")
            log_exception("MAIN_RETRY")
            sys.exit(1)
