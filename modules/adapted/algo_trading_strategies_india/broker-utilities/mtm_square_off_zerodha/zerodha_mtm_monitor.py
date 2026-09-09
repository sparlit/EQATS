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


"""
Enhanced Zerodha MTM Monitor - Fixed Order Execution Issues
File: zerodha_mtm_monitor.py

Key fixes:
1. Added timeout mechanisms for all API calls
2. Enhanced error handling with detailed logging
3. Non-blocking order placement with retry logic
4. Better exception handling for network issues
5. Fallback mechanisms for failed orders
6. Comprehensive logging throughout order flow
"""

import json
import logging
import signal
import sqlite3
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from datetime import datetime, timedelta
from threading import Lock
from typing import Dict, List, Optional, Tuple

import yaml
from kiteconnect import KiteConnect


class EnhancedMTMMonitor:
    """
    Enhanced MTM Monitor with bulletproof order execution
    """

    def __init__(self, config_path: str = "config.yaml"):
        # Initialize logging first
        self.setup_logging()

        # Initialize default timeout settings BEFORE loading config
        self.api_timeout = 15  # seconds for API calls
        self.order_placement_timeout = 30  # seconds for order placement
        self.order_verification_timeout = 45  # seconds for order verification

        # Now load config and setup other components
        self.load_config(config_path)
        self.setup_kite_client()
        self.setup_databases()

        # Thread safety
        self.db_lock = Lock()
        self.ltp_db_lock = Lock()

        # State tracking
        self.last_positions_check = 0
        self.positions_cache = {}
        self.mtm_history = []

        # Square-off state
        self.square_off_in_progress = False
        self.order_retry_count = {}
        self.max_order_retries = 3

        # Trading discipline tracking
        self.daily_max_mtm = 0.0
        self.daily_max_profit_reached = False
        self.current_trading_date = datetime.now().date()

        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        # Thread pool for non-blocking operations
        self.executor = ThreadPoolExecutor(max_workers=4)

    def signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        self.logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.cleanup()
        sys.exit(0)

    def setup_logging(self):
        """Setup enhanced logging configuration"""
        # Create formatters for different log levels
        detailed_formatter = logging.Formatter("%(asctime)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s")
        simple_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

        # Setup file handler with detailed logging
        file_handler = logging.FileHandler("mtm_monitor.log")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(detailed_formatter)

        # Setup console handler with simple logging
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(simple_formatter)

        # Configure logger
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

        # Prevent duplicate logs
        self.logger.propagate = False

    def load_config(self, config_path: str):
        """Load configuration with enhanced settings"""
        try:
            with open(config_path) as file:
                self.config = yaml.safe_load(file)

            # Extract configuration with enhanced defaults
            self.api_key = self.config["zerodha"]["api_key"]
            self.api_secret = self.config["zerodha"]["api_secret"]
            self.mtm_threshold = self.config["trading"]["mtm_loss_threshold"]
            self.daily_max_profit_target = self.config["trading"].get("daily_max_profit_target", 100)
            self.monitor_interval = 3  # Fixed to 3 seconds
            self.auto_square_off = self.config["risk_management"].get("auto_square_off_enabled", True)

            # Enhanced order settings (update from config if available)
            risk_mgmt = self.config.get("risk_management", {})
            self.max_order_retries = risk_mgmt.get("max_order_retries", 3)
            self.order_retry_delay = risk_mgmt.get("order_retry_delay", 2)
            self.order_status_check_interval = risk_mgmt.get("order_status_check_interval", 2)

            # Update timeout settings from config if available
            if "api_call_timeout" in risk_mgmt:
                self.api_timeout = risk_mgmt["api_call_timeout"]
            if "order_placement_timeout" in risk_mgmt:
                self.order_placement_timeout = risk_mgmt["order_placement_timeout"]
            if "order_verification_timeout" in risk_mgmt:
                self.order_verification_timeout = risk_mgmt["order_verification_timeout"]

            # Volume freeze quantities
            self.freeze_quantities = self.config.get("instruments", {})

            # LTP freshness threshold
            self.ltp_freshness_threshold = self.config.get("ltp_management", {}).get("freshness_threshold_seconds", 10)

            self.logger.info(f"Enhanced configuration loaded. MTM threshold: {self.mtm_threshold}")
            self.logger.info(
                f"Monitor interval: {self.monitor_interval}s, LTP freshness: {self.ltp_freshness_threshold}s"
            )
            self.logger.info(
                f"Order timeouts - Placement: {self.order_placement_timeout}s, Verification: {self.order_verification_timeout}s"
            )

        except Exception as e:
            self.logger.exception(f"Error loading config: {e}")
            raise

    def check_daily_reset(self):
        """Check if we need to reset daily tracking for new trading day"""
        today = datetime.now().date()

        if today != self.current_trading_date:
            self.logger.info(f"🌅 New trading day detected: {today}")
            self.logger.info(f"📊 Previous day max MTM: ₹{self.daily_max_mtm:.2f}")

            # Reset daily tracking
            self.daily_max_mtm = 0.0
            self.daily_max_profit_reached = False
            self.current_trading_date = today

            self.logger.info(f"✅ Daily tracking reset for {today}")
            self.logger.info(f"🎯 Daily max profit target: ₹{self.daily_max_profit_target}")

    def update_daily_max_mtm(self, current_mtm: float):
        """Update daily max MTM and check if target reached"""
        if current_mtm > self.daily_max_mtm:
            self.daily_max_mtm = current_mtm
            self.logger.debug(f"📈 New daily max MTM: ₹{self.daily_max_mtm:.2f}")

        # Check if we hit the daily max profit target for the first time
        if not self.daily_max_profit_reached and self.daily_max_mtm >= self.daily_max_profit_target:
            self.daily_max_profit_reached = True
            self.logger.critical("🎯 DAILY MAX PROFIT TARGET REACHED!")
            self.logger.critical(f"   Max MTM achieved: ₹{self.daily_max_mtm:.2f}")
            self.logger.critical(f"   Target was: ₹{self.daily_max_profit_target}")
            self.logger.critical("🚫 TRADING DISCIPLINE MODE ACTIVATED - ANY NEW POSITIONS WILL BE SQUARED OFF!")
            return True

        return False

    def setup_kite_client(self):
        """Initialize Kite Connect client with timeout"""
        try:
            self.kite = KiteConnect(api_key=self.api_key, timeout=self.api_timeout)

            # Load access token
            access_token_path = "/home/ubuntu/utilities/kite_connect_data/tickjournal/key_files/access_token.txt"
            with open(access_token_path) as f:
                access_token = f.read().strip()

            self.kite.set_access_token(access_token)

            # Test connection with timeout
            profile = self.kite.profile()
            self.logger.info(f"Connected to Kite API. User: {profile['user_name']}")

        except Exception as e:
            self.logger.exception(f"Error setting up Kite client: {e}")
            raise

    def setup_databases(self):
        """Setup separate databases to avoid locking issues"""
        try:
            # MTM Monitor database (separate from LTP data)
            self.mtm_conn = sqlite3.connect("zerodha_mtm.db", check_same_thread=False, timeout=30)
            self.mtm_cursor = self.mtm_conn.cursor()

            # LTP data database (read-only access)
            self.ltp_conn = sqlite3.connect("zerodha_trading.db", check_same_thread=False, timeout=30)
            self.ltp_cursor = self.ltp_conn.cursor()

            # Enable WAL mode for better concurrent access
            self.mtm_cursor.execute("PRAGMA journal_mode=WAL")
            self.ltp_cursor.execute("PRAGMA journal_mode=WAL")

            # Create MTM tracking tables
            self.create_mtm_tables()

            self.logger.info("Enhanced database setup completed with separate databases")

        except Exception as e:
            self.logger.exception(f"Error setting up databases: {e}")
            raise

    def create_mtm_tables(self):
        """Create enhanced MTM tracking tables"""
        try:
            # MTM history table
            self.mtm_cursor.execute("""
                CREATE TABLE IF NOT EXISTS mtm_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    total_mtm REAL NOT NULL,
                    position_count INTEGER NOT NULL,
                    threshold_status TEXT NOT NULL,
                    auto_square_off_enabled INTEGER DEFAULT 1,
                    details TEXT
                )
            """)

            # Enhanced square-off tracking
            self.mtm_cursor.execute("""
                CREATE TABLE IF NOT EXISTS square_off_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    trigger_mtm REAL NOT NULL,
                    total_positions INTEGER NOT NULL,
                    sell_positions INTEGER DEFAULT 0,
                    buy_positions INTEGER DEFAULT 0,
                    phase TEXT NOT NULL,
                    status TEXT NOT NULL,
                    details TEXT,
                    error_details TEXT
                )
            """)

            # Enhanced order tracking table
            self.mtm_cursor.execute("""
                CREATE TABLE IF NOT EXISTS order_tracking (
                    order_id TEXT PRIMARY KEY,
                    instrument_token INTEGER NOT NULL,
                    tradingsymbol TEXT NOT NULL,
                    transaction_type TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    product TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    retry_count INTEGER DEFAULT 0,
                    api_response TEXT,
                    error_message TEXT,
                    placement_time REAL DEFAULT 0,
                    verification_time REAL DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Thread pool shutdown fix
            self.shutdown_timeout = 5  # seconds

            # Order execution details table
            self.mtm_cursor.execute("""
                CREATE TABLE IF NOT EXISTS order_executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT NOT NULL,
                    execution_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    execution_price REAL,
                    executed_quantity INTEGER,
                    pending_quantity INTEGER,
                    order_status TEXT,
                    status_message TEXT,
                    FOREIGN KEY (order_id) REFERENCES order_tracking (order_id)
                )
            """)

            self.mtm_conn.commit()

        except Exception as e:
            self.logger.exception(f"Error creating MTM tables: {e}")
            raise

    def safe_api_call(self, func, *args, **kwargs):
        """Execute API call with timeout and error handling"""
        try:
            self.logger.debug(f"Making API call: {func.__name__}")
            start_time = time.time()

            # Use thread pool for timeout capability
            future = self.executor.submit(func, *args, **kwargs)
            result = future.result(timeout=self.api_timeout)

            elapsed = time.time() - start_time
            self.logger.debug(f"API call {func.__name__} completed in {elapsed:.2f}s")

            return result, None

        except FuturesTimeoutError:
            self.logger.exception(f"API call {func.__name__} timed out after {self.api_timeout}s")
            return None, f"Timeout after {self.api_timeout}s"
        except Exception as e:
            self.logger.exception(f"API call {func.__name__} failed: {e}")
            return None, str(e)

    def fetch_current_positions(self) -> list[dict]:
        """Fetch current positions from Kite API with timeout"""
        try:
            self.logger.debug("Fetching current positions from API...")

            # Use safe API call
            response, error = self.safe_api_call(self.kite.positions)

            if error:
                self.logger.error(f"Failed to fetch positions: {error}")
                return []

            if not response:
                self.logger.warning("Empty response from positions API")
                return []

            net_positions = response.get("net", [])

            # Filter positions with non-zero quantity
            open_positions = [pos for pos in net_positions if pos.get("quantity", 0) != 0]

            self.logger.info(f"Fetched {len(open_positions)} open positions from API")

            # Log position details for debugging
            for pos in open_positions:
                self.logger.debug(
                    f"Position: {pos['tradingsymbol']} | Qty: {pos['quantity']} | Product: {pos['product']}"
                )

            return open_positions

        except Exception as e:
            self.logger.exception(f"Error fetching positions: {e}")
            return []

    def categorize_positions_for_square_off(self, positions: list[dict]) -> tuple[list[dict], list[dict]]:
        """Categorize positions into SELL and BUY for prioritized square-off"""
        sell_positions = []  # Short positions (quantity < 0)
        buy_positions = []  # Long positions (quantity > 0)

        self.logger.info(f"Categorizing {len(positions)} positions for square-off...")

        for position in positions:
            qty = position["quantity"]
            symbol = position["tradingsymbol"]

            if qty < 0:
                sell_positions.append(position)
                self.logger.debug(f"SELL position: {symbol} | Qty: {qty}")
            else:
                buy_positions.append(position)
                self.logger.debug(f"BUY position: {symbol} | Qty: {qty}")

        # Sort by risk - higher risk first
        sell_positions.sort(key=lambda x: abs(x["quantity"] * x.get("average_price", 0)), reverse=True)
        buy_positions.sort(key=lambda x: abs(x["quantity"] * x.get("average_price", 0)), reverse=True)

        self.logger.info(
            f"Position categorization: {len(sell_positions)} SELL positions, {len(buy_positions)} BUY positions"
        )

        # Log categorization details
        if sell_positions:
            self.logger.info("SELL positions (shorts to cover):")
            for i, pos in enumerate(sell_positions, 1):
                value = abs(pos["quantity"] * pos.get("average_price", 0))
                self.logger.info(f"  {i}. {pos['tradingsymbol']} | Qty: {pos['quantity']} | Value: ₹{value:.2f}")

        if buy_positions:
            self.logger.info("BUY positions (longs to sell):")
            for i, pos in enumerate(buy_positions, 1):
                value = abs(pos["quantity"] * pos.get("average_price", 0))
                self.logger.info(f"  {i}. {pos['tradingsymbol']} | Qty: {pos['quantity']} | Value: ₹{value:.2f}")

        return sell_positions, buy_positions

    def get_freeze_quantity(self, tradingsymbol: str) -> int:
        """Get volume freeze quantity for an instrument"""
        for symbol, config in self.freeze_quantities.items():
            if tradingsymbol.startswith(symbol):
                freeze_qty = config.get("volume_freeze_quantity", 1000)
                self.logger.debug(f"Freeze quantity for {tradingsymbol}: {freeze_qty}")
                return freeze_qty

        default_freeze = 1000
        self.logger.debug(f"Using default freeze quantity for {tradingsymbol}: {default_freeze}")
        return default_freeze

    def place_order_with_timeout(self, order_params: dict) -> tuple[str | None, str | None]:
        """Place order with timeout and comprehensive error handling"""
        try:
            self.logger.info(
                f"🔄 Placing order: {order_params['tradingsymbol']} | {order_params['transaction_type']} {order_params['quantity']}"
            )

            start_time = time.time()

            # Log detailed order parameters
            self.logger.debug(f"Order parameters: {json.dumps(order_params, indent=2)}")

            # Use safe API call for order placement
            order_id, error = self.safe_api_call(
                self.kite.place_order,
                variety=order_params["variety"],
                exchange=order_params["exchange"],
                tradingsymbol=order_params["tradingsymbol"],
                transaction_type=order_params["transaction_type"],
                quantity=order_params["quantity"],
                product=order_params["product"],
                order_type=order_params["order_type"],
            )

            placement_time = time.time() - start_time

            if error:
                self.logger.error(f"❌ Order placement failed: {error}")
                return None, error

            if not order_id:
                error_msg = "Order placement returned empty order ID"
                self.logger.error(f"❌ {error_msg}")
                return None, error_msg

            self.logger.info(f"✅ Order placed successfully in {placement_time:.2f}s: {order_id}")

            # Store order tracking immediately
            self.store_order_tracking(
                order_id,
                order_params.get("instrument_token", 0),
                order_params["tradingsymbol"],
                order_params["transaction_type"],
                order_params["quantity"],
                order_params["product"],
                "PLACED",
                placement_time=placement_time,
            )

            return order_id, None

        except Exception as e:
            error_msg = f"Exception in order placement: {e!s}"
            self.logger.exception(f"❌ {error_msg}")
            self.logger.exception(f"❌ Stack trace: {traceback.format_exc()}")
            return None, error_msg

    def verify_order_execution_enhanced(self, order_id: str, expected_qty: int, symbol: str) -> dict:
        """Enhanced order execution verification with detailed logging"""
        try:
            self.logger.info(f"🔍 Verifying order execution: {order_id} for {symbol}")

            start_time = time.time()
            check_count = 0
            max_checks = self.order_verification_timeout // self.order_status_check_interval

            # Define status categories
            FINAL_STATUSES = {"COMPLETE", "REJECTED", "CANCELLED"}
            PENDING_STATUSES = {
                "PUT ORDER REQ RECEIVED",
                "VALIDATION PENDING",
                "OPEN PENDING",
                "MODIFY VALIDATION PENDING",
                "MODIFY PENDING",
                "TRIGGER PENDING",
                "CANCEL PENDING",
                "AMO REQ RECEIVED",
                "OPEN",
            }

            last_status = None
            status_changes = []

            while time.time() - start_time < self.order_verification_timeout and check_count < max_checks:
                check_count += 1

                try:
                    elapsed = time.time() - start_time
                    self.logger.debug(f"Order status check #{check_count} for {order_id} (elapsed: {elapsed:.1f}s)")

                    # Get order status with timeout
                    order_history, error = self.safe_api_call(self.kite.order_history, order_id)

                    if error:
                        self.logger.warning(f"⚠️ Failed to get order status (attempt {check_count}): {error}")
                        if check_count < max_checks:
                            time.sleep(self.order_status_check_interval)
                            continue
                        return {"success": False, "executed_quantity": 0, "reason": f"Status check failed: {error}"}

                    if not order_history or len(order_history) == 0:
                        self.logger.warning(f"⚠️ Empty order history for {order_id}")
                        time.sleep(self.order_status_check_interval)
                        continue

                    latest_status = order_history[-1]
                    status = latest_status.get("status", "").upper()
                    filled_quantity = latest_status.get("filled_quantity", 0)
                    pending_quantity = latest_status.get("pending_quantity", 0)
                    status_message = latest_status.get("status_message", "")

                    # Track status changes
                    if status != last_status:
                        status_changes.append(
                            {
                                "timestamp": time.time(),
                                "status": status,
                                "filled_qty": filled_quantity,
                                "pending_qty": pending_quantity,
                                "message": status_message,
                            }
                        )
                        self.logger.info(
                            f"📋 Order {order_id} status change: {last_status} → {status} | Filled: {filled_quantity}"
                        )
                        last_status = status

                    # Store execution details
                    self.store_order_execution(order_id, latest_status)

                    # Handle final statuses
                    if status in FINAL_STATUSES:
                        elapsed = time.time() - start_time

                        if status == "COMPLETE":
                            self.logger.info(
                                f"✅ Order {order_id} COMPLETED in {elapsed:.2f}s - Filled: {filled_quantity}/{expected_qty}"
                            )

                            return {
                                "success": True,
                                "executed_quantity": filled_quantity,
                                "status": status,
                                "verification_time": elapsed,
                                "status_changes": status_changes,
                            }

                        if status in ["REJECTED", "CANCELLED"]:
                            self.logger.error(
                                f"❌ Order {order_id} {status} in {elapsed:.2f}s - Reason: {status_message}"
                            )

                            return {
                                "success": False,
                                "executed_quantity": filled_quantity,
                                "status": status,
                                "reason": f"Order {status}: {status_message}",
                                "verification_time": elapsed,
                                "status_changes": status_changes,
                            }

                    # Handle pending statuses
                    elif status in PENDING_STATUSES:
                        # Check for partial fills with timeout approaching
                        if filled_quantity > 0:
                            fill_rate = (filled_quantity / expected_qty) * 100

                            if fill_rate >= 80 and elapsed > (self.order_verification_timeout * 0.8):
                                self.logger.info(
                                    f"✅ Accepting partial fill for {order_id}: {fill_rate:.1f}% after {elapsed:.2f}s"
                                )

                                return {
                                    "success": True,
                                    "executed_quantity": filled_quantity,
                                    "status": "PARTIAL_COMPLETE",
                                    "verification_time": elapsed,
                                    "status_changes": status_changes,
                                }

                        # Continue waiting for pending statuses
                        time.sleep(self.order_status_check_interval)
                        continue

                    else:
                        self.logger.warning(f"⚠️ Unknown order status: {status} for order {order_id}")
                        time.sleep(self.order_status_check_interval)
                        continue

                except Exception as status_error:
                    self.logger.warning(f"⚠️ Error checking order status (attempt {check_count}): {status_error}")
                    if check_count < max_checks:
                        time.sleep(self.order_status_check_interval)
                        continue
                    break

            # Timeout reached
            elapsed = time.time() - start_time
            self.logger.warning(
                f"⏰ Order verification timeout for {order_id} after {elapsed:.2f}s ({check_count} checks)"
            )

            # Final status check for partial fills
            try:
                final_status, _ = self.safe_api_call(self.kite.order_history, order_id)
                if final_status and len(final_status) > 0:
                    latest = final_status[-1]
                    final_filled = latest.get("filled_quantity", 0)
                    final_status_text = latest.get("status", "UNKNOWN")

                    if final_filled > 0:
                        self.logger.info(
                            f"🟡 Timeout but found partial fill: {final_filled} qty, status: {final_status_text}"
                        )

                        return {
                            "success": True,
                            "executed_quantity": final_filled,
                            "status": "TIMEOUT_PARTIAL",
                            "reason": f"Timeout but got {final_filled} qty",
                            "verification_time": elapsed,
                            "status_changes": status_changes,
                        }
            except:
                pass

            return {
                "success": False,
                "executed_quantity": 0,
                "reason": f"Verification timeout after {elapsed:.2f}s ({check_count} checks)",
                "verification_time": elapsed,
                "status_changes": status_changes,
            }

        except Exception as e:
            elapsed = time.time() - start_time if "start_time" in locals() else 0
            self.logger.exception(f"💥 Order verification error: {e}")

            return {
                "success": False,
                "executed_quantity": 0,
                "reason": f"Verification error: {e!s}",
                "verification_time": elapsed,
            }

    def place_square_off_order_with_verification(self, position: dict) -> dict:
        """Place square-off order with comprehensive verification and retry"""
        try:
            tradingsymbol = position["tradingsymbol"]
            exchange = position["exchange"]
            quantity = abs(position["quantity"])
            product = position["product"]
            instrument_token = position["instrument_token"]

            # Determine transaction type
            if position["quantity"] > 0:
                transaction_type = self.kite.TRANSACTION_TYPE_SELL
                action = "SELL"
            else:
                transaction_type = self.kite.TRANSACTION_TYPE_BUY
                action = "BUY"

            self.logger.info(f"🔄 Starting square-off for {tradingsymbol}: {action} {quantity} | Product: {product}")

            # Get freeze quantity
            freeze_qty = self.get_freeze_quantity(tradingsymbol)

            # Track order results
            total_quantity = quantity
            remaining_quantity = quantity
            placed_orders = []
            successful_executions = 0
            failed_orders = []

            # Overall timeout for the entire square-off process
            square_off_start_time = time.time()
            max_square_off_time = 120  # 2 minutes max for entire square-off

            # Split orders if needed due to volume freeze
            order_sequence = 0
            while remaining_quantity > 0 and (time.time() - square_off_start_time) < max_square_off_time:
                order_sequence += 1
                order_qty = min(freeze_qty, remaining_quantity)

                self.logger.info(
                    f"📝 Placing order {order_sequence}/{((total_quantity - 1) // freeze_qty) + 1}: {action} {order_qty} of {tradingsymbol}"
                )

                # Prepare order parameters
                order_params = {
                    "variety": self.kite.VARIETY_REGULAR,
                    "exchange": exchange,
                    "tradingsymbol": tradingsymbol,
                    "transaction_type": transaction_type,
                    "quantity": order_qty,
                    "product": product,
                    "order_type": self.kite.ORDER_TYPE_MARKET,
                    "instrument_token": instrument_token,
                }

                # Place order with timeout
                order_placement_start = time.time()
                order_id, placement_error = self.place_order_with_timeout(order_params)
                order_placement_time = time.time() - order_placement_start

                if placement_error:
                    self.logger.error(f"❌ Order {order_sequence} placement failed: {placement_error}")

                    failed_orders.append(
                        {
                            "order_id": None,
                            "quantity": order_qty,
                            "reason": placement_error,
                            "sequence": order_sequence,
                            "placement_time": order_placement_time,
                        }
                    )

                    # Simple retry logic
                    retry_key = f"{tradingsymbol}_{order_sequence}"
                    retry_count = self.order_retry_count.get(retry_key, 0)

                    if retry_count < self.max_order_retries:
                        self.order_retry_count[retry_key] = retry_count + 1
                        self.logger.info(
                            f"🔄 Retrying order {order_sequence} for {tradingsymbol} (attempt {retry_count + 1})"
                        )
                        time.sleep(self.order_retry_delay)
                        continue
                    self.logger.error(f"🚫 Max retries exceeded for {tradingsymbol} order {order_sequence}")
                    remaining_quantity -= order_qty  # Skip this quantity
                    continue

                # Order placed successfully, now verify execution
                order_info = {
                    "order_id": order_id,
                    "quantity": order_qty,
                    "status": "PLACED",
                    "execution_qty": 0,
                    "placement_time": order_placement_time,
                    "sequence": order_sequence,
                }
                placed_orders.append(order_info)

                # Verify order execution
                self.logger.info(f"🔍 Verifying execution for order {order_sequence}: {order_id}")
                verification_start = time.time()
                execution_result = self.verify_order_execution_enhanced(order_id, order_qty, tradingsymbol)
                verification_time = time.time() - verification_start

                self.logger.info(f"📊 Order {order_sequence} verification completed in {verification_time:.2f}s")

                if execution_result["success"]:
                    executed_qty = execution_result["executed_quantity"]
                    remaining_quantity -= executed_qty
                    successful_executions += executed_qty
                    order_info["status"] = "EXECUTED"
                    order_info["execution_qty"] = executed_qty
                    order_info["verification_time"] = verification_time

                    status_emoji = "✅" if executed_qty == order_qty else "🟡"
                    self.logger.info(f"{status_emoji} Order {order_sequence} executed: {executed_qty}/{order_qty} qty")

                    # Update order tracking
                    self.update_order_tracking(order_id, "EXECUTED", execution_result)

                    # Brief pause before next order
                    if remaining_quantity > 0:
                        time.sleep(1)

                else:
                    # Order failed execution
                    failed_orders.append(
                        {
                            "order_id": order_id,
                            "quantity": order_qty,
                            "reason": execution_result.get("reason", "Unknown execution failure"),
                            "verification_time": verification_time,
                            "sequence": order_sequence,
                        }
                    )

                    self.logger.error(
                        f"❌ Order {order_sequence} execution failed: {execution_result.get('reason', 'Unknown')}"
                    )

                    # Update order tracking
                    self.update_order_tracking(order_id, "FAILED", execution_result)

                    # Skip this quantity and continue
                    remaining_quantity -= order_qty

            # Check for overall timeout
            total_time = time.time() - square_off_start_time
            if total_time >= max_square_off_time:
                self.logger.warning(f"⏰ Square-off timeout after {total_time:.2f}s for {tradingsymbol}")

            # Calculate success rate
            success_rate = (successful_executions / total_quantity) * 100 if total_quantity > 0 else 0

            result = {
                "symbol": tradingsymbol,
                "total_quantity": total_quantity,
                "executed_quantity": successful_executions,
                "remaining_quantity": remaining_quantity,
                "success_rate": success_rate,
                "placed_orders": placed_orders,
                "failed_orders": failed_orders,
                "fully_executed": remaining_quantity == 0,
                "total_time": total_time,
                "timeout_occurred": total_time >= max_square_off_time,
                "orders_attempted": order_sequence,
            }

            status_emoji = "✅" if result["fully_executed"] else "🟡" if successful_executions > 0 else "❌"
            self.logger.info(
                f"{status_emoji} Square-off result for {tradingsymbol}: {successful_executions}/{total_quantity} executed ({success_rate:.1f}%) in {total_time:.2f}s"
            )

            return result

        except Exception as e:
            self.logger.exception(
                f"💥 Critical error in square-off for {position.get('tradingsymbol', 'Unknown')}: {e}"
            )
            self.logger.exception(f"💥 Stack trace: {traceback.format_exc()}")

            return {
                "symbol": position.get("tradingsymbol", "Unknown"),
                "total_quantity": abs(position.get("quantity", 0)),
                "executed_quantity": 0,
                "success_rate": 0,
                "fully_executed": False,
                "error": str(e),
                "total_time": 0,
            }

    def store_order_tracking(
        self,
        order_id: str,
        instrument_token: int,
        tradingsymbol: str,
        transaction_type: str,
        quantity: int,
        product: str,
        status: str,
        placement_time: float = 0,
        api_response: str | None = None,
        error_message: str | None = None,
    ):
        """Store comprehensive order tracking information"""
        try:
            with self.db_lock:
                self.mtm_cursor.execute(
                    """
                    INSERT OR REPLACE INTO order_tracking
                    (order_id, instrument_token, tradingsymbol, transaction_type,
                     quantity, product, order_type, status, placement_time,
                     api_response, error_message, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                    (
                        order_id,
                        instrument_token,
                        tradingsymbol,
                        transaction_type,
                        quantity,
                        product,
                        "MARKET",
                        status,
                        placement_time,
                        api_response,
                        error_message,
                    ),
                )

                self.mtm_conn.commit()
                self.logger.debug(f"Stored order tracking for {order_id}")

        except Exception as e:
            self.logger.warning(f"Error storing order tracking (non-critical): {e}")

    def update_order_tracking(self, order_id: str, status: str, execution_details: dict):
        """Update order tracking with execution details"""
        try:
            with self.db_lock:
                verification_time = execution_details.get("verification_time", 0)
                details_json = json.dumps(execution_details)

                self.mtm_cursor.execute(
                    """
                    UPDATE order_tracking
                    SET status = ?, verification_time = ?, api_response = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE order_id = ?
                """,
                    (status, verification_time, details_json, order_id),
                )

                self.mtm_conn.commit()

        except Exception as e:
            self.logger.warning(f"Error updating order tracking (non-critical): {e}")

    def store_order_execution(self, order_id: str, order_data: dict):
        """Store detailed order execution information"""
        try:
            with self.db_lock:
                self.mtm_cursor.execute(
                    """
                    INSERT OR REPLACE INTO order_executions
                    (order_id, execution_price, executed_quantity, pending_quantity,
                     order_status, status_message)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (
                        order_id,
                        order_data.get("average_price", 0),
                        order_data.get("filled_quantity", 0),
                        order_data.get("pending_quantity", 0),
                        order_data.get("status", ""),
                        order_data.get("status_message", ""),
                    ),
                )

                self.mtm_conn.commit()

        except Exception as e:
            self.logger.debug(f"Error storing order execution (non-critical): {e}")

    def enhanced_square_off_all_positions(self) -> dict:
        """Enhanced square-off with bulletproof execution"""
        if self.square_off_in_progress:
            self.logger.warning("Square-off already in progress, skipping")
            return {"status": "ALREADY_IN_PROGRESS"}

        self.square_off_in_progress = True
        square_off_start_time = time.time()

        self.logger.warning("🚨 INITIATING ENHANCED EMERGENCY SQUARE-OFF 🚨")
        self.logger.warning("🚨 BULLETPROOF EXECUTION MODE ACTIVATED 🚨")

        try:
            # Get current positions with retry
            max_position_fetch_attempts = 3
            positions = None

            for attempt in range(max_position_fetch_attempts):
                self.logger.info(f"Fetching positions (attempt {attempt + 1}/{max_position_fetch_attempts})")
                positions = self.fetch_current_positions()

                if positions is not None:
                    break

                if attempt < max_position_fetch_attempts - 1:
                    self.logger.warning("Position fetch failed, retrying in 3 seconds...")
                    time.sleep(3)

            if not positions:
                self.logger.error("❌ Failed to fetch positions after multiple attempts")
                return {
                    "error": "Failed to fetch positions",
                    "total_positions": 0,
                    "total_success": 0,
                    "total_failed": 0,
                }

            if len(positions) == 0:
                self.logger.info("✅ No positions to square off")
                return {
                    "total_positions": 0,
                    "total_success": 0,
                    "total_failed": 0,
                    "message": "No open positions found",
                }

            self.logger.critical(f"🎯 TARGET: {len(positions)} positions to square off")

            # Categorize positions
            sell_positions, buy_positions = self.categorize_positions_for_square_off(positions)

            # Initialize tracking
            square_off_id = self.store_square_off_initiation(len(positions), len(sell_positions), len(buy_positions))

            all_results = []
            phase_results = {}

            # PHASE 1: Square off SELL positions first (short positions)
            if sell_positions:
                self.logger.warning(f"🔴 PHASE 1: Squaring off {len(sell_positions)} SELL positions (SHORT positions)")

                sell_results = []
                for i, position in enumerate(sell_positions, 1):
                    self.logger.info(
                        f"🔴 Processing SELL position {i}/{len(sell_positions)}: {position['tradingsymbol']}"
                    )

                    try:
                        result = self.place_square_off_order_with_verification(position)
                        sell_results.append(result)
                        all_results.append(result)

                        # Log immediate result
                        if result.get("fully_executed", False):
                            self.logger.info(f"✅ SELL position {i} completed successfully")
                        else:
                            executed = result.get("executed_quantity", 0)
                            total = result.get("total_quantity", 0)
                            self.logger.warning(f"🟡 SELL position {i} partially completed: {executed}/{total}")

                    except Exception as pos_error:
                        self.logger.exception(f"💥 Error processing SELL position {i}: {pos_error}")
                        failed_result = {
                            "symbol": position["tradingsymbol"],
                            "total_quantity": abs(position["quantity"]),
                            "executed_quantity": 0,
                            "success_rate": 0,
                            "fully_executed": False,
                            "error": str(pos_error),
                        }
                        sell_results.append(failed_result)
                        all_results.append(failed_result)

                    # Small delay between positions
                    time.sleep(2)

                sell_success_count = sum(1 for r in sell_results if r.get("fully_executed", False))
                phase_results["sell_phase"] = {
                    "total": len(sell_positions),
                    "success": sell_success_count,
                    "failed": len(sell_positions) - sell_success_count,
                }

                self.logger.warning(f"🔴 SELL phase completed: {sell_success_count}/{len(sell_positions)} successful")
                self.update_square_off_status(square_off_id, "SELL_FIRST", "COMPLETED")

                # Wait between phases
                if buy_positions:
                    self.logger.info("⏳ Waiting 5 seconds between phases...")
                    time.sleep(5)
            else:
                self.logger.info("🔴 PHASE 1: No SELL positions to square off")

            # PHASE 2: Square off BUY positions (long positions)
            if buy_positions:
                self.logger.warning(f"🟢 PHASE 2: Squaring off {len(buy_positions)} BUY positions (LONG positions)")

                buy_results = []
                for i, position in enumerate(buy_positions, 1):
                    self.logger.info(
                        f"🟢 Processing BUY position {i}/{len(buy_positions)}: {position['tradingsymbol']}"
                    )

                    try:
                        result = self.place_square_off_order_with_verification(position)
                        buy_results.append(result)
                        all_results.append(result)

                        # Log immediate result
                        if result.get("fully_executed", False):
                            self.logger.info(f"✅ BUY position {i} completed successfully")
                        else:
                            executed = result.get("executed_quantity", 0)
                            total = result.get("total_quantity", 0)
                            self.logger.warning(f"🟡 BUY position {i} partially completed: {executed}/{total}")

                    except Exception as pos_error:
                        self.logger.exception(f"💥 Error processing BUY position {i}: {pos_error}")
                        failed_result = {
                            "symbol": position["tradingsymbol"],
                            "total_quantity": abs(position["quantity"]),
                            "executed_quantity": 0,
                            "success_rate": 0,
                            "fully_executed": False,
                            "error": str(pos_error),
                        }
                        buy_results.append(failed_result)
                        all_results.append(failed_result)

                    # Small delay between positions
                    time.sleep(2)

                buy_success_count = sum(1 for r in buy_results if r.get("fully_executed", False))
                phase_results["buy_phase"] = {
                    "total": len(buy_positions),
                    "success": buy_success_count,
                    "failed": len(buy_positions) - buy_success_count,
                }

                self.logger.warning(f"🟢 BUY phase completed: {buy_success_count}/{len(buy_positions)} successful")
                self.update_square_off_status(square_off_id, "BUY_SECOND", "COMPLETED")
            else:
                self.logger.info("🟢 PHASE 2: No BUY positions to square off")

            # Calculate overall results
            total_positions = len(positions)
            total_success = sum(1 for r in all_results if r.get("fully_executed", False))
            total_failed = total_positions - total_success
            total_square_off_time = time.time() - square_off_start_time

            # Final result
            final_result = {
                "square_off_id": square_off_id,
                "total_positions": total_positions,
                "total_success": total_success,
                "total_failed": total_failed,
                "success_rate": (total_success / total_positions) * 100 if total_positions > 0 else 0,
                "total_execution_time": total_square_off_time,
                "phase_results": phase_results,
                "detailed_results": all_results,
                "timestamp": datetime.now().isoformat(),
            }

            # Update final status
            final_status = "COMPLETED" if total_failed == 0 else "PARTIAL"
            self.update_square_off_status(square_off_id, "COMPLETED", final_status, final_result)

            # Comprehensive final logging
            self.logger.critical("=" * 80)
            self.logger.critical("🏁 ENHANCED SQUARE-OFF EXECUTION COMPLETED")
            self.logger.critical("=" * 80)
            self.logger.critical("📊 RESULTS SUMMARY:")
            self.logger.critical(f"   Total Positions: {total_positions}")
            self.logger.critical(f"   Successfully Squared: {total_success}")
            self.logger.critical(f"   Failed: {total_failed}")
            self.logger.critical(f"   Success Rate: {final_result['success_rate']:.1f}%")
            self.logger.critical(f"   Total Time: {total_square_off_time:.2f} seconds")

            if phase_results.get("sell_phase"):
                sell_phase = phase_results["sell_phase"]
                self.logger.critical(f"   SELL Phase: {sell_phase['success']}/{sell_phase['total']} successful")

            if phase_results.get("buy_phase"):
                buy_phase = phase_results["buy_phase"]
                self.logger.critical(f"   BUY Phase: {buy_phase['success']}/{buy_phase['total']} successful")

            self.logger.critical("=" * 80)

            return final_result

        except Exception as e:
            total_time = time.time() - square_off_start_time
            self.logger.exception(f"💥 CRITICAL ERROR in enhanced square-off: {e}")
            self.logger.exception(f"💥 Stack trace: {traceback.format_exc()}")

            return {
                "error": str(e),
                "total_positions": 0,
                "total_success": 0,
                "total_failed": 0,
                "total_execution_time": total_time,
            }
        finally:
            self.square_off_in_progress = False
            self.logger.info("🔄 Square-off process flag cleared")

    def store_square_off_initiation(self, total_positions: int, sell_positions: int, buy_positions: int) -> int:
        """Store square-off initiation details"""
        try:
            with self.db_lock:
                # Get current MTM for reference
                current_mtm, _ = self.calculate_total_mtm()

                self.mtm_cursor.execute(
                    """
                    INSERT INTO square_off_history
                    (trigger_mtm, total_positions, sell_positions, buy_positions, phase, status, details)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        current_mtm,
                        total_positions,
                        sell_positions,
                        buy_positions,
                        "INITIATED",
                        "INITIATED",
                        json.dumps(
                            {
                                "trigger_time": datetime.now().isoformat(),
                                "auto_square_off": self.auto_square_off,
                                "api_timeout": self.api_timeout,
                                "order_placement_timeout": self.order_placement_timeout,
                            }
                        ),
                    ),
                )

                square_off_id = self.mtm_cursor.lastrowid
                self.mtm_conn.commit()

                return square_off_id

        except Exception as e:
            self.logger.exception(f"Error storing square-off initiation: {e}")
            return 0

    def update_square_off_status(self, square_off_id: int, phase: str, status: str, details: dict | None = None):
        """Update square-off status"""
        try:
            with self.db_lock:
                details_json = json.dumps(details) if details else None

                self.mtm_cursor.execute(
                    """
                    UPDATE square_off_history
                    SET phase = ?, status = ?, details = ?, timestamp = CURRENT_TIMESTAMP
                    WHERE id = ?
                """,
                    (phase, status, details_json, square_off_id),
                )

                self.mtm_conn.commit()

        except Exception as e:
            self.logger.exception(f"Error updating square-off status: {e}")

    def verify_no_positions_remaining(self) -> dict:
        """Verify that no positions remain after square-off"""
        try:
            self.logger.info("🔍 Verifying no positions remain after square-off...")

            # Wait for positions to update
            time.sleep(5)

            # Fetch current positions with retry
            remaining_positions = None
            for _attempt in range(3):
                remaining_positions = self.fetch_current_positions()
                if remaining_positions is not None:
                    break
                time.sleep(2)

            if remaining_positions is None:
                return {"verification_passed": False, "error": "Failed to fetch positions for verification"}

            if not remaining_positions:
                self.logger.info("✅ Verification successful: No positions remaining")
                return {
                    "verification_passed": True,
                    "remaining_positions": 0,
                    "message": "All positions successfully squared off",
                }
            self.logger.warning(f"⚠️ Verification failed: {len(remaining_positions)} positions still open")

            # Log remaining positions
            for pos in remaining_positions:
                value = abs(pos["quantity"] * pos.get("average_price", 0))
                self.logger.warning(f"Remaining: {pos['tradingsymbol']} | Qty: {pos['quantity']} | Value: ₹{value:.2f}")

            return {
                "verification_passed": False,
                "remaining_positions": len(remaining_positions),
                "positions": [
                    {
                        "symbol": pos["tradingsymbol"],
                        "quantity": pos["quantity"],
                        "value": abs(pos["quantity"] * pos.get("average_price", 0)),
                    }
                    for pos in remaining_positions
                ],
                "message": f"{len(remaining_positions)} positions still open after square-off",
            }

        except Exception as e:
            self.logger.exception(f"Error in post-square-off verification: {e}")
            return {"verification_passed": False, "error": str(e)}

    def get_ltp_with_refresh(self, instrument_token: int, force_refresh: bool = False) -> float | None:
        """Get LTP with automatic refresh for stale data"""
        try:
            with self.ltp_db_lock:
                self.ltp_cursor.execute(
                    """
                    SELECT last_price, timestamp, tradingsymbol
                    FROM ltp_data
                    WHERE instrument_token = ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                """,
                    (instrument_token,),
                )

                result = self.ltp_cursor.fetchone()
                if result:
                    price, timestamp, symbol = result
                    current_time = time.time()
                    data_age = current_time - timestamp

                    if data_age <= self.ltp_freshness_threshold and not force_refresh:
                        return price
                    self.logger.debug(f"Stale LTP data for {symbol}: {data_age:.1f}s old")
                    # Return stale data as fallback for MTM calculation
                    return price

                return None

        except Exception as e:
            self.logger.exception(f"Error getting LTP for token {instrument_token}: {e}")
            return None

    def calculate_total_mtm(self, include_realized: bool = True) -> tuple[float, list[dict]]:
        """Calculate total MTM with enhanced error handling"""
        try:
            # Get current positions
            positions = self.fetch_current_positions()
            if positions is None:
                self.logger.error("Failed to fetch positions for MTM calculation")
                return 0.0, []

            # Calculate unrealized P&L
            unrealized_mtm = 0.0
            position_details = []
            stale_ltp_count = 0

            if positions:
                for position in positions:
                    try:
                        instrument_token = position["instrument_token"]

                        # Get LTP
                        current_price = self.get_ltp_with_refresh(instrument_token)

                        if current_price is None:
                            stale_ltp_count += 1
                            self.logger.warning(f"No LTP data for {position['tradingsymbol']}")
                            continue

                        # Calculate P&L using Zerodha's formula
                        net_quantity = position["quantity"]
                        buy_value = position.get("buy_value", 0.0)
                        sell_value = position.get("sell_value", 0.0)
                        multiplier = position.get("multiplier", 1.0)

                        realized_component = sell_value - buy_value
                        unrealized_component = net_quantity * current_price * multiplier
                        total_pnl = realized_component + unrealized_component

                        unrealized_mtm += total_pnl

                        position_details.append(
                            {
                                "instrument_token": instrument_token,
                                "tradingsymbol": position["tradingsymbol"],
                                "quantity": net_quantity,
                                "current_price": current_price,
                                "average_price": position.get("average_price", 0.0),
                                "buy_value": buy_value,
                                "sell_value": sell_value,
                                "total_pnl": total_pnl,
                                "multiplier": multiplier,
                            }
                        )

                    except Exception as pos_error:
                        self.logger.warning(
                            f"Error calculating P&L for {position.get('tradingsymbol', 'Unknown')}: {pos_error}"
                        )
                        continue

            # Get realized P&L if requested
            realized_pnl = 0.0
            if include_realized:
                try:
                    realized_pnl, _ = self.get_todays_realized_pnl_from_orders()
                except Exception as realized_error:
                    self.logger.warning(f"Error calculating realized P&L: {realized_error}")
                    realized_pnl = 0.0

            total_mtm = unrealized_mtm + realized_pnl

            if stale_ltp_count > 0:
                self.logger.warning(f"MTM calculated with {stale_ltp_count} positions missing LTP data")

            self.logger.info(
                f"MTM Breakdown - Open Positions: ₹{unrealized_mtm:.2f} ({len(position_details)} positions), "
                f"Closed Trades: ₹{realized_pnl:.2f}, Total: ₹{total_mtm:.2f}"
            )

            return total_mtm, position_details

        except Exception as e:
            self.logger.exception(f"Error calculating total MTM: {e}")
            return 0.0, []

    def get_todays_realized_pnl_from_orders(self) -> tuple[float, list[dict]]:
        """Get today's realized P&L from closed trades with timeout"""
        try:
            # Use safe API call for orders
            orders, error = self.safe_api_call(self.kite.orders)

            if error:
                self.logger.warning(f"Failed to fetch orders for realized P&L: {error}")
                return 0.0, []

            if not orders:
                return 0.0, []

            today = datetime.now().date()

            # Filter today's completed orders
            todays_orders = []
            for order in orders:
                try:
                    order_timestamp = order.get("order_timestamp", "")
                    if isinstance(order_timestamp, str):
                        order_date = datetime.strptime(order_timestamp[:10], "%Y-%m-%d").date()
                    else:
                        order_date = order_timestamp.date()

                    if (
                        order_date == today
                        and order["status"] == "COMPLETE"
                        and order["quantity"] == order["filled_quantity"]
                    ):
                        todays_orders.append(order)
                except Exception:
                    continue

            if not todays_orders:
                return 0.0, []

            # Get current open positions to avoid double counting
            current_positions = self.fetch_current_positions()
            if current_positions is None:
                current_positions = []

            current_position_keys = set()
            for pos in current_positions:
                key = f"{pos['tradingsymbol']}_{pos['product']}"
                current_position_keys.add(key)

            # Calculate realized P&L for closed positions only
            total_realized_pnl = 0.0
            closed_trades = []

            # Group orders by symbol and product
            symbol_trades = {}
            for order in todays_orders:
                key = f"{order['tradingsymbol']}_{order['product']}"

                if key not in symbol_trades:
                    symbol_trades[key] = {
                        "tradingsymbol": order["tradingsymbol"],
                        "product": order["product"],
                        "orders": [],
                    }

                symbol_trades[key]["orders"].append(
                    {
                        "transaction_type": order["transaction_type"],
                        "quantity": order["filled_quantity"],
                        "price": order["average_price"],
                        "value": order["filled_quantity"] * order["average_price"],
                    }
                )

            for key, trades in symbol_trades.items():
                if key in current_position_keys:
                    continue  # Skip open positions

                # Calculate P&L for closed position
                total_buy_value = sum(o["value"] for o in trades["orders"] if o["transaction_type"] == "BUY")
                total_sell_value = sum(o["value"] for o in trades["orders"] if o["transaction_type"] == "SELL")

                net_quantity = sum(o["quantity"] for o in trades["orders"] if o["transaction_type"] == "BUY") - sum(
                    o["quantity"] for o in trades["orders"] if o["transaction_type"] == "SELL"
                )

                if net_quantity == 0:  # Fully closed position
                    realized_pnl = total_sell_value - total_buy_value
                    total_realized_pnl += realized_pnl
                    closed_trades.append({"tradingsymbol": trades["tradingsymbol"], "total_pnl": realized_pnl})

            return total_realized_pnl, closed_trades

        except Exception as e:
            self.logger.exception(f"Error calculating realized P&L: {e}")
            return 0.0, []

    def log_mtm_status(self, total_mtm: float, position_details: list[dict]):
        """Log MTM status with enhanced tracking"""
        position_count = len(position_details)
        threshold_status = "BREACH" if total_mtm <= self.mtm_threshold else "SAFE"

        # Store in MTM history
        try:
            with self.db_lock:
                details_json = json.dumps(
                    {
                        "positions": [
                            {
                                "symbol": detail["tradingsymbol"],
                                "quantity": detail["quantity"],
                                "current_price": detail["current_price"],
                                "pnl": detail["total_pnl"],
                            }
                            for detail in position_details
                        ]
                    }
                )

                self.mtm_cursor.execute(
                    """
                    INSERT INTO mtm_history
                    (total_mtm, position_count, threshold_status, auto_square_off_enabled, details)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (total_mtm, position_count, threshold_status, int(self.auto_square_off), details_json),
                )

                self.mtm_conn.commit()

        except Exception as e:
            self.logger.warning(f"Error storing MTM history (non-critical): {e}")

        # Log current status
        self.logger.info(f"MTM: ₹{total_mtm:.2f} | Positions: {position_count} | Threshold: ₹{self.mtm_threshold}")

    def check_mtm_threshold(self, total_mtm: float) -> bool:
        """Check if MTM threshold is breached"""
        if total_mtm <= self.mtm_threshold:
            self.logger.critical(f"MTM THRESHOLD BREACHED! Current: ₹{total_mtm:.2f}, Threshold: ₹{self.mtm_threshold}")
            return True
        return False

    def monitor_mtm_enhanced(self):
        """Enhanced MTM monitoring with trading discipline"""
        self.logger.info("Starting Enhanced MTM monitoring with Trading Discipline...")
        self.logger.info(f"MTM loss threshold: ₹{self.mtm_threshold}")
        self.logger.info(f"Daily max profit target: ₹{self.daily_max_profit_target}")
        self.logger.info(f"Monitor interval: {self.monitor_interval} seconds")
        self.logger.info("🎯 TRADING DISCIPLINE MODE - Will block trading after daily target!")

        consecutive_errors = 0
        max_consecutive_errors = 5

        while True:
            try:
                consecutive_errors = 0

                # Check for daily reset
                self.check_daily_reset()

                # Calculate current MTM
                total_mtm, position_details = self.calculate_total_mtm(include_realized=True)

                # Update daily max MTM tracking
                target_reached_now = self.update_daily_max_mtm(total_mtm)

                # Log current status with discipline info
                self.log_mtm_status_with_discipline(total_mtm, position_details)

                # Check for immediate square-off conditions
                should_square_off = False
                square_off_reason = ""

                # 1. Check loss threshold
                if total_mtm <= self.mtm_threshold:
                    should_square_off = True
                    square_off_reason = "LOSS_PROTECTION"
                    self.logger.critical(
                        f"🚨 LOSS THRESHOLD BREACHED! Current: ₹{total_mtm:.2f}, Threshold: ₹{self.mtm_threshold}"
                    )

                # 2. Check if daily max profit target was just reached
                elif target_reached_now:
                    should_square_off = True
                    square_off_reason = "DAILY_TARGET_REACHED"

                # 3. Check if we have positions while in discipline mode
                elif self.daily_max_profit_reached and position_details:
                    should_square_off = True
                    square_off_reason = "DISCIPLINE_MODE_ACTIVE"
                    self.logger.critical("🚫 DISCIPLINE MODE: Squaring off positions (daily target already reached)")

                # Execute square-off if needed
                if should_square_off and self.auto_square_off and position_details:
                    if square_off_reason == "LOSS_PROTECTION":
                        self.logger.critical("🚨 EXECUTING LOSS PROTECTION SQUARE-OFF 🚨")
                    elif square_off_reason == "DAILY_TARGET_REACHED":
                        self.logger.critical("🎯 EXECUTING DAILY TARGET SQUARE-OFF 🎯")
                    else:  # DISCIPLINE_MODE_ACTIVE
                        self.logger.critical("🚫 EXECUTING DISCIPLINE MODE SQUARE-OFF 🚫")

                    self.logger.critical(f"   Current MTM: ₹{total_mtm:.2f}")
                    self.logger.critical(f"   Daily Max MTM: ₹{self.daily_max_mtm:.2f}")
                    self.logger.critical(f"   Positions: {len(position_details)}")

                    # Execute square-off
                    square_off_result = self.enhanced_square_off_all_positions()

                    # Wait and verify
                    time.sleep(10)
                    self.verify_no_positions_remaining()
                    final_mtm, _final_positions = self.calculate_total_mtm(include_realized=True)

                    # Log results
                    self.logger.critical("=" * 80)
                    if square_off_reason == "LOSS_PROTECTION":
                        self.logger.critical("🛡️ LOSS PROTECTION COMPLETED")
                    elif square_off_reason == "DAILY_TARGET_REACHED":
                        self.logger.critical("🎯 DAILY TARGET SQUARE-OFF COMPLETED")
                    else:
                        self.logger.critical("🚫 DISCIPLINE MODE SQUARE-OFF COMPLETED")

                    self.logger.critical(f"⚡ Final MTM: ₹{final_mtm:.2f}")
                    self.logger.critical(
                        f"⚡ Positions squared: {square_off_result.get('total_success', 0)}/{square_off_result.get('total_positions', 0)}"
                    )

                    if square_off_reason in ["DAILY_TARGET_REACHED", "DISCIPLINE_MODE_ACTIVE"]:
                        self.logger.critical(
                            "🚫 TRADING DISCIPLINE ACTIVE: Any new positions will be immediately squared off!"
                        )

                    self.logger.critical("=" * 80)

                # Sleep for next check
                time.sleep(self.monitor_interval)

            except KeyboardInterrupt:
                self.logger.info("Enhanced MTM monitoring stopped by user")
                break
            except Exception as e:
                consecutive_errors += 1
                self.logger.exception(f"💥 Error in enhanced MTM monitoring: {e}")

                if consecutive_errors >= max_consecutive_errors:
                    self.logger.critical("🚨 Too many consecutive errors. Stopping monitor.")
                    break

                error_delay = min(self.monitor_interval * (2 ** (consecutive_errors - 1)), 60)
                time.sleep(error_delay)

    def log_mtm_status_with_discipline(self, total_mtm: float, position_details: list[dict]):
        """Enhanced logging with discipline mode status"""
        position_count = len(position_details)

        # Standard logging
        self.logger.info(
            f"MTM: ₹{total_mtm:.2f} | Positions: {position_count} | "
            f"Daily Max: ₹{self.daily_max_mtm:.2f} | Target: ₹{self.daily_max_profit_target} | "
            f"Discipline: {'🚫 ACTIVE' if self.daily_max_profit_reached else '✅ INACTIVE'}"
        )

        # Store in database (existing logic)
        try:
            with self.db_lock:
                threshold_status = "SAFE"
                if total_mtm <= self.mtm_threshold:
                    threshold_status = "LOSS_BREACH"
                elif self.daily_max_profit_reached:
                    threshold_status = "DISCIPLINE_ACTIVE"

                details_json = json.dumps(
                    {
                        "positions": [
                            {
                                "symbol": detail["tradingsymbol"],
                                "quantity": detail["quantity"],
                                "current_price": detail["current_price"],
                                "pnl": detail["total_pnl"],
                            }
                            for detail in position_details
                        ],
                        "daily_max_mtm": self.daily_max_mtm,
                        "daily_max_profit_reached": self.daily_max_profit_reached,
                        "trading_date": self.current_trading_date.isoformat(),
                    }
                )

                self.mtm_cursor.execute(
                    """
                                        INSERT INTO mtm_history
                                            (total_mtm, position_count, threshold_status, auto_square_off_enabled, details)
                                        VALUES (?, ?, ?, ?, ?)
                                        """,
                    (total_mtm, position_count, threshold_status, int(self.auto_square_off), details_json),
                )

                self.mtm_conn.commit()

        except Exception as e:
            self.logger.warning(f"Error storing MTM history: {e}")

    def cleanup(self):
        """Enhanced cleanup with comprehensive resource management"""
        try:
            self.logger.info("Starting enhanced cleanup...")

            # Shutdown thread pool (fix for Python version compatibility)
            if hasattr(self, "executor"):
                self.logger.info("Shutting down thread pool...")
                try:
                    self.executor.shutdown(wait=True)
                except TypeError:
                    # Older Python versions don't support timeout parameter
                    self.executor.shutdown(wait=True)

            # Close database connections
            if hasattr(self, "mtm_conn"):
                self.logger.info("Closing MTM database connection...")
                self.mtm_conn.close()

            if hasattr(self, "ltp_conn"):
                self.logger.info("Closing LTP database connection...")
                self.ltp_conn.close()

            # Clear any remaining state
            if hasattr(self, "order_retry_count"):
                self.order_retry_count.clear()

            self.logger.info("Enhanced MTM monitor cleanup completed successfully")

        except Exception as e:
            self.logger.exception(f"Error during cleanup: {e}")

    def get_system_status(self) -> dict:
        """Get comprehensive system status for monitoring"""
        try:
            # Calculate current MTM
            total_mtm, position_details = self.calculate_total_mtm(include_realized=True)

            # Get recent square-off history
            recent_square_offs = []
            try:
                with self.db_lock:
                    self.mtm_cursor.execute("""
                        SELECT timestamp, trigger_mtm, total_positions, status, phase
                        FROM square_off_history
                        ORDER BY timestamp DESC
                        LIMIT 5
                    """)

                    for row in self.mtm_cursor.fetchall():
                        recent_square_offs.append(
                            {
                                "timestamp": row[0],
                                "trigger_mtm": row[1],
                                "total_positions": row[2],
                                "status": row[3],
                                "phase": row[4],
                            }
                        )
            except Exception:
                pass

            # Get recent orders
            recent_orders = []
            try:
                with self.db_lock:
                    self.mtm_cursor.execute("""
                        SELECT order_id, tradingsymbol, transaction_type, quantity, status, created_at
                        FROM order_tracking
                        ORDER BY created_at DESC
                        LIMIT 10
                    """)

                    for row in self.mtm_cursor.fetchall():
                        recent_orders.append(
                            {
                                "order_id": row[0],
                                "symbol": row[1],
                                "transaction_type": row[2],
                                "quantity": row[3],
                                "status": row[4],
                                "created_at": row[5],
                            }
                        )
            except Exception:
                pass

            return {
                "timestamp": datetime.now().isoformat(),
                "system_health": {
                    "mtm_monitor_running": True,
                    "square_off_in_progress": self.square_off_in_progress,
                    "auto_square_off_enabled": self.auto_square_off,
                },
                "mtm_data": {
                    "current_mtm": total_mtm,
                    "threshold": self.mtm_threshold,
                    "threshold_status": "BREACH" if total_mtm <= self.mtm_threshold else "SAFE",
                    "position_count": len(position_details),
                    "positions": [
                        {
                            "symbol": pos["tradingsymbol"],
                            "quantity": pos["quantity"],
                            "pnl": pos["total_pnl"],
                            "current_price": pos["current_price"],
                        }
                        for pos in position_details
                    ],
                },
                "configuration": {
                    "monitor_interval": self.monitor_interval,
                    "api_timeout": self.api_timeout,
                    "order_placement_timeout": self.order_placement_timeout,
                    "order_verification_timeout": self.order_verification_timeout,
                    "max_order_retries": self.max_order_retries,
                },
                "recent_activity": {"square_offs": recent_square_offs, "orders": recent_orders},
            }

        except Exception as e:
            return {
                "timestamp": datetime.now().isoformat(),
                "error": str(e),
                "system_health": {"mtm_monitor_running": True, "error_occurred": True},
            }


def main():
    """Main function with enhanced error handling"""
    monitor = None

    try:
        # Show enhanced startup info
        print("🚀 Enhanced Zerodha MTM Monitor Starting...")
        print("=" * 60)
        print("🔧 BULLETPROOF EXECUTION MODE")
        print("=" * 60)

        # Initialize monitor
        monitor = EnhancedMTMMonitor()

        print(f"📊 MTM Threshold: ₹{monitor.mtm_threshold}")
        print(f"⏱️  Monitor Interval: {monitor.monitor_interval} seconds")
        print(f"🔄 Auto Square-off: {'ENABLED' if monitor.auto_square_off else 'DISABLED'}")
        print(f"⏰ API Timeout: {monitor.api_timeout} seconds")
        print(f"⏰ Order Timeout: {monitor.order_placement_timeout} seconds")
        print("=" * 60)

        # Enhanced features info
        print("🛡️  BULLETPROOF FEATURES:")
        print("   ✅ Timeout protection for all API calls")
        print("   ✅ Comprehensive error handling and retry logic")
        print("   ✅ Non-blocking order placement with verification")
        print("   ✅ Prioritized square-off (SELL positions first)")
        print("   ✅ Order execution tracking and verification")
        print("   ✅ Fallback mechanisms for failed operations")
        print("   ✅ Detailed logging throughout execution flow")
        print("   ✅ Thread pool for timeout management")
        print("   ✅ Graceful shutdown handling")
        print("=" * 60)

        # Test API connectivity before starting
        print("🔍 Testing API connectivity...")
        try:
            profile, error = monitor.safe_api_call(monitor.kite.profile)
            if error:
                print(f"❌ API connectivity test failed: {error}")
                return
            print(f"✅ API connectivity test passed: {profile['user_name']}")
        except Exception as e:
            print(f"❌ API connectivity test error: {e}")
            return

        print("🎯 All systems ready. Starting enhanced monitoring...")
        print("=" * 60)

        # Start enhanced monitoring
        monitor.monitor_mtm_enhanced()

    except KeyboardInterrupt:
        print("\n🛑 Shutting down Enhanced MTM monitor...")
    except Exception as e:
        print(f"❌ Critical Error: {e}")
        traceback.print_exc()
    finally:
        if monitor:
            monitor.cleanup()
        print("🏁 Enhanced MTM Monitor shutdown complete.")


if __name__ == "__main__":
    main()
