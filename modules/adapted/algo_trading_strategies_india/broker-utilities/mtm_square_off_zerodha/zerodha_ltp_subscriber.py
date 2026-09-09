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
Enhanced Zerodha Kite WebSocket LTP Subscriber - Fixed Stale LTP Issues
File: zerodha_ltp_subscriber.py

This script subscribes to live market data via Zerodha WebSocket API
and stores LTP data in unified SQLite database for MTM calculations.

Key Features:
- Keeps WebSocket subscriptions active throughout trading day
- No more stale LTP issues when re-entering positions
- Daily reset at market open
- Real-time monitoring and subscription management
"""

import json
import logging
import sqlite3
import struct
import time
from datetime import datetime
from threading import Lock, Thread
from typing import Dict, List, Optional

import yaml
from kiteconnect import KiteConnect, KiteTicker


class EnhancedZerodhaLTPSubscriber:
    """
    Enhanced LTP Subscriber that maintains WebSocket subscriptions
    throughout the trading day to prevent stale LTP issues.
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.setup_logging()
        self.load_config(config_path)
        self.setup_kite_client()
        self.setup_database()
        self.setup_websocket()

        # Thread safety
        self.db_lock = Lock()

        # Enhanced subscription management
        self.subscribed_tokens = set()
        self.daily_instruments = set()  # Keep tracking instruments all day
        self.current_date = time.strftime("%Y-%m-%d")

        # Performance optimization with faster batching
        self.batch_size = 50
        self.batch_data = []
        self.last_batch_time = time.time()

    def setup_logging(self):
        """Setup enhanced logging configuration"""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s",
            handlers=[logging.FileHandler("ltp_subscriber.log"), logging.StreamHandler()],
        )
        self.logger = logging.getLogger(__name__)

    def load_config(self, config_path: str):
        """Load configuration from YAML file"""
        try:
            with open(config_path) as file:
                self.config = yaml.safe_load(file)

            # Extract API credentials
            self.api_key = self.config["zerodha"]["api_key"]
            self.api_secret = self.config["zerodha"]["api_secret"]

            self.logger.info("Configuration loaded successfully")

        except Exception as e:
            self.logger.exception(f"Error loading config: {e}")
            raise

    def setup_kite_client(self):
        """Initialize Kite Connect client"""
        try:
            self.kite = KiteConnect(api_key=self.api_key)

            # Load access token from file
            access_token_path = "/home/ubuntu/utilities/kite_connect_data/tickjournal/key_files/access_token.txt"
            with open(access_token_path) as f:
                access_token = f.read().strip()

            self.kite.set_access_token(access_token)

            # Test connection
            profile = self.kite.profile()
            self.logger.info(f"Connected to Kite API. User: {profile['user_name']}")

        except Exception as e:
            self.logger.exception(f"Error setting up Kite client: {e}")
            raise

    def setup_websocket(self):
        """Initialize enhanced KiteTicker WebSocket client"""
        try:
            self.ticker = KiteTicker(api_key=self.api_key, access_token=self.kite.access_token)

            # Setup WebSocket callbacks
            self.ticker.on_ticks = self.on_ticks
            self.ticker.on_connect = self.on_connect
            self.ticker.on_close = self.on_close
            self.ticker.on_error = self.on_error
            self.ticker.on_reconnect = self.on_reconnect
            self.ticker.on_noreconnect = self.on_noreconnect

            self.logger.info("Enhanced WebSocket client initialized")

        except Exception as e:
            self.logger.exception(f"Error setting up WebSocket: {e}")
            raise

    def setup_database(self):
        """Setup unified SQLite database with WAL mode"""
        try:
            self.conn = sqlite3.connect("zerodha_trading.db", check_same_thread=False, timeout=30)
            self.cursor = self.conn.cursor()

            # Enable WAL mode for better concurrent access (creates .wal and .shm files)
            self.cursor.execute("PRAGMA journal_mode=WAL")
            self.cursor.execute("PRAGMA synchronous=NORMAL")
            self.cursor.execute("PRAGMA cache_size=10000")

            # Create unified LTP data table
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS ltp_data (
                    instrument_token INTEGER PRIMARY KEY,
                    tradingsymbol TEXT,
                    exchange TEXT,
                    last_price REAL NOT NULL,
                    last_quantity INTEGER DEFAULT 0,
                    volume INTEGER DEFAULT 0,
                    buy_quantity INTEGER DEFAULT 0,
                    sell_quantity INTEGER DEFAULT 0,
                    ohlc_open REAL DEFAULT 0,
                    ohlc_high REAL DEFAULT 0,
                    ohlc_low REAL DEFAULT 0,
                    ohlc_close REAL DEFAULT 0,
                    timestamp REAL NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create positions table for tracking current positions
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    instrument_token INTEGER PRIMARY KEY,
                    tradingsymbol TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    product TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    average_price REAL NOT NULL,
                    multiplier REAL DEFAULT 1.0,
                    buy_quantity INTEGER DEFAULT 0,
                    sell_quantity INTEGER DEFAULT 0,
                    buy_value REAL DEFAULT 0.0,
                    sell_value REAL DEFAULT 0.0,
                    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
                    is_subscribed INTEGER DEFAULT 0
                )
            """)

            # Create indexes for performance
            self.cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_ltp_timestamp ON ltp_data(timestamp DESC)
            """)
            self.cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_ltp_token ON ltp_data(instrument_token)
            """)
            self.cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_positions_subscribed ON positions(is_subscribed)
            """)

            self.conn.commit()
            self.logger.info("Enhanced database setup completed with WAL mode")

        except Exception as e:
            self.logger.exception(f"Error setting up database: {e}")
            raise

    def check_daily_reset(self):
        """Reset daily tracking at start of new trading day"""
        today = time.strftime("%Y-%m-%d")
        if today != self.current_date:
            self.logger.info(f"🌅 New trading day detected: {today}")
            self.logger.info(f"📊 Yesterday tracked {len(self.daily_instruments)} instruments")

            # Clear yesterday's instruments and subscriptions
            self.daily_instruments.clear()
            self.current_date = today

            # Unsubscribe from all (fresh start for new day)
            if self.subscribed_tokens:
                try:
                    self.ticker.unsubscribe(list(self.subscribed_tokens))
                    self.subscribed_tokens.clear()
                    self.logger.info("🔄 Cleared all subscriptions for new trading day")
                except Exception as e:
                    self.logger.warning(f"Error clearing subscriptions: {e}")

    def on_connect(self, ws, response):
        """Enhanced WebSocket connection callback"""
        self.logger.info("🔗 WebSocket connected successfully")
        self.logger.info(f"📡 Connection response: {response}")
        self.subscribe_to_positions()

    def on_close(self, ws, code, reason):
        """WebSocket close callback"""
        self.logger.warning(f"🔌 WebSocket closed: {code} - {reason}")

    def on_error(self, ws, code, reason):
        """WebSocket error callback"""
        self.logger.error(f"❌ WebSocket error: {code} - {reason}")

    def on_reconnect(self, ws, attempts_count):
        """WebSocket reconnect callback"""
        self.logger.info(f"🔄 WebSocket reconnecting (attempt {attempts_count})")

    def on_noreconnect(self, ws):
        """WebSocket no reconnect callback"""
        self.logger.error("🚫 WebSocket failed to reconnect")

    def on_ticks(self, ws, ticks):
        """
        Enhanced tick data handler with faster processing.
        Optimized for high-frequency data processing.
        """
        try:
            current_time = time.time()
            tick_count = len(ticks)

            for tick in ticks:
                # Get symbol info from database
                symbol_info = self.get_symbol_info(tick["instrument_token"])

                # Prepare data for batch insertion
                tick_data = (
                    tick["instrument_token"],
                    symbol_info.get("tradingsymbol", "UNKNOWN") if symbol_info else "UNKNOWN",
                    symbol_info.get("exchange", "UNKNOWN") if symbol_info else "UNKNOWN",
                    tick.get("last_price", 0.0),
                    tick.get("last_quantity", 0),
                    tick.get("volume", 0),
                    tick.get("buy_quantity", 0),
                    tick.get("sell_quantity", 0),
                    tick.get("ohlc", {}).get("open", 0.0),
                    tick.get("ohlc", {}).get("high", 0.0),
                    tick.get("ohlc", {}).get("low", 0.0),
                    tick.get("ohlc", {}).get("close", 0.0),
                    current_time,
                )

                self.batch_data.append(tick_data)

            # Enhanced batch flushing with faster timeout for scalping
            if (
                len(self.batch_data) >= self.batch_size or current_time - self.last_batch_time > 0.5
            ):  # Faster: 0.5 second timeout
                self.flush_batch_data()

            # Log tick activity every 100 ticks
            if tick_count > 0:
                self.logger.debug(f"📈 Processed {tick_count} ticks, batch size: {len(self.batch_data)}")

        except Exception as e:
            self.logger.exception(f"Error processing ticks: {e}")

    def get_symbol_info(self, instrument_token: int) -> dict | None:
        """Get symbol info from positions table with caching"""
        try:
            with self.db_lock:
                self.cursor.execute(
                    """
                    SELECT tradingsymbol, exchange
                    FROM positions
                    WHERE instrument_token = ?
                """,
                    (instrument_token,),
                )

                result = self.cursor.fetchone()
                if result:
                    return {"tradingsymbol": result[0], "exchange": result[1]}
                return None
        except Exception as e:
            self.logger.exception(f"Error getting symbol info for token {instrument_token}: {e}")
            return None

    def flush_batch_data(self):
        """Enhanced batch data flushing"""
        if not self.batch_data:
            return

        try:
            with self.db_lock:
                self.cursor.executemany(
                    """
                    INSERT OR REPLACE INTO ltp_data (
                        instrument_token, tradingsymbol, exchange, last_price,
                        last_quantity, volume, buy_quantity, sell_quantity,
                        ohlc_open, ohlc_high, ohlc_low, ohlc_close, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    self.batch_data,
                )

                self.conn.commit()

                batch_count = len(self.batch_data)
                self.logger.debug(f"💾 Flushed {batch_count} tick records to database")

                # Clear batch
                self.batch_data.clear()
                self.last_batch_time = time.time()

        except Exception as e:
            self.logger.exception(f"Error flushing batch data: {e}")

    def fetch_current_positions(self):
        """
        Fetch current positions from Kite API with retry logic.
        Only fetches 'net' positions as recommended by Zerodha.
        """
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    self.logger.debug(f"Position fetch attempt {attempt + 1}/{max_retries}")

                response = self.kite.positions()

                # Use 'net' positions as recommended by Zerodha forum
                net_positions = response.get("net", [])

                # Filter only positions with non-zero quantity
                open_positions = [pos for pos in net_positions if pos.get("quantity", 0) != 0]

                self.logger.info(f"📊 Found {len(open_positions)} open positions")
                return open_positions

            except Exception as e:
                self.logger.warning(f"Position fetch attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)  # Wait before retry
                    continue
                self.logger.exception(f"Failed to fetch positions after {max_retries} attempts")
                return []
        return None

    def update_positions_in_db(self, positions: list[dict]):
        """Update positions table with current open positions"""
        try:
            with self.db_lock:
                # Clear existing subscription flags
                self.cursor.execute("UPDATE positions SET is_subscribed = 0")

                position_data = []
                for pos in positions:
                    position_data.append(
                        (
                            pos["instrument_token"],
                            pos["tradingsymbol"],
                            pos["exchange"],
                            pos["product"],
                            pos["quantity"],
                            pos["average_price"],
                            pos.get("multiplier", 1.0),
                            pos.get("buy_quantity", 0),
                            pos.get("sell_quantity", 0),
                            pos.get("buy_value", 0.0),
                            pos.get("sell_value", 0.0),
                        )
                    )

                # Insert/update current positions
                if position_data:
                    self.cursor.executemany(
                        """
                        INSERT OR REPLACE INTO positions (
                            instrument_token, tradingsymbol, exchange,
                            product, quantity, average_price, multiplier,
                            buy_quantity, sell_quantity, buy_value, sell_value, is_subscribed
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                        position_data,
                    )

                self.conn.commit()
                self.logger.info(f"💾 Updated {len(position_data)} positions in database")

        except Exception as e:
            self.logger.exception(f"Error updating positions in database: {e}")

    def subscribe_to_positions(self):
        """
        ENHANCED: Keep WebSocket subscriptions active throughout trading day.
        This fixes the stale LTP issue by not unsubscribing when positions are closed.
        """
        try:
            # Check for daily reset first
            self.check_daily_reset()

            # Fetch current positions
            current_positions = self.fetch_current_positions()

            if current_positions:
                # Update positions in database
                self.update_positions_in_db(current_positions)

                # Add current position instruments to daily tracking
                current_tokens = {pos["instrument_token"] for pos in current_positions}
                self.daily_instruments.update(current_tokens)

                self.logger.info("📈 Current positions:")
                for pos in current_positions:
                    self.logger.info(f"   {pos['tradingsymbol']} | Qty: {pos['quantity']} | Product: {pos['product']}")
            else:
                self.logger.info("📊 No current positions")

            # KEY ENHANCEMENT: Subscribe to ALL instruments traded today (not just current positions)
            if self.daily_instruments:
                # Find new instruments to subscribe to
                new_tokens = list(self.daily_instruments - self.subscribed_tokens)

                if new_tokens:
                    self.ticker.subscribe(new_tokens)
                    self.ticker.set_mode(self.ticker.MODE_FULL, new_tokens)
                    self.subscribed_tokens.update(new_tokens)

                    self.logger.info(f"🔔 Subscribed to {len(new_tokens)} new instruments")

                self.logger.info(f"📡 Total active WebSocket subscriptions: {len(self.subscribed_tokens)} instruments")

                # Log what we're tracking
                self.log_subscribed_instruments()
            else:
                self.logger.info("📊 No instruments to track yet today")

        except Exception as e:
            self.logger.exception(f"Error in enhanced subscription management: {e}")

    def log_subscribed_instruments(self):
        """Log currently subscribed instruments for debugging"""
        try:
            with self.db_lock:
                if self.daily_instruments:
                    placeholders = ",".join("?" * len(self.daily_instruments))
                    self.cursor.execute(
                        f"""
                        SELECT tradingsymbol, exchange
                        FROM positions
                        WHERE instrument_token IN ({placeholders})
                    """,
                        list(self.daily_instruments),
                    )

                    instruments = [f"{row[0]} ({row[1]})" for row in self.cursor.fetchall()]
                    if instruments:
                        self.logger.info(f"📊 Tracking instruments: {', '.join(instruments)}")
        except Exception as e:
            self.logger.debug(f"Error logging subscribed instruments: {e}")

    def get_ltp(self, instrument_token: int) -> float | None:
        """Get latest LTP for an instrument token with freshness check"""
        try:
            with self.db_lock:
                self.cursor.execute(
                    """
                    SELECT last_price, timestamp, tradingsymbol
                    FROM ltp_data
                    WHERE instrument_token = ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                """,
                    (instrument_token,),
                )

                result = self.cursor.fetchone()
                if result:
                    price, timestamp, symbol = result
                    data_age = time.time() - timestamp

                    # Enhanced freshness check for options (stricter)
                    freshness_limit = 5 if any(x in symbol for x in ["SENSEX", "NIFTY", "BANKNIFTY"]) else 10

                    if data_age <= freshness_limit:
                        return price
                    self.logger.warning(f"⚠️ LTP data for {symbol} is {data_age:.1f}s old")
                    return price  # Still return stale data rather than None

                return None

        except Exception as e:
            self.logger.exception(f"Error getting LTP for token {instrument_token}: {e}")
            return None

    def monitor_and_update_subscriptions(self):
        """
        Enhanced monitoring - check frequently for new positions and subscribe immediately.
        Runs in a separate thread.
        """
        # Faster checking intervals for active trading
        check_interval = self.config.get("websocket", {}).get("position_check_interval", 2)  # 2 seconds
        error_retry_interval = self.config.get("websocket", {}).get("error_retry_interval", 15)  # 15 seconds

        self.logger.info(f"🔄 Enhanced position monitoring started (checking every {check_interval}s)")

        while True:
            try:
                time.sleep(check_interval)

                current_positions = self.fetch_current_positions()

                if current_positions:
                    current_tokens = {pos["instrument_token"] for pos in current_positions}

                    # Check if we have new instruments to track
                    new_instruments = current_tokens - self.daily_instruments

                    if new_instruments:
                        self.logger.info(
                            f"🆕 Detected {len(new_instruments)} new instruments, updating subscriptions..."
                        )
                        self.subscribe_to_positions()

            except Exception as e:
                self.logger.exception(f"Error in enhanced subscription monitor: {e}")
                time.sleep(error_retry_interval)

    def get_realtime_status(self) -> dict:
        """Get comprehensive real-time status of WebSocket subscriptions"""
        try:
            current_time = time.time()

            with self.db_lock:
                # Get subscription status
                status = {
                    "subscribed_instruments": len(self.subscribed_tokens),
                    "daily_instruments": len(self.daily_instruments),
                    "current_date": self.current_date,
                    "batch_pending": len(self.batch_data),
                }

                # Get LTP freshness data
                if self.subscribed_tokens:
                    placeholders = ",".join("?" * len(self.subscribed_tokens))
                    self.cursor.execute(
                        f"""
                        SELECT instrument_token, tradingsymbol, last_price, timestamp,
                               ({current_time} - timestamp) as age_seconds
                        FROM ltp_data
                        WHERE instrument_token IN ({placeholders})
                        ORDER BY timestamp DESC
                    """,
                        list(self.subscribed_tokens),
                    )

                    results = self.cursor.fetchall()

                    if results:
                        fresh_count = sum(1 for r in results if r[4] <= 10)  # Fresh if < 10s old
                        stale_count = len(results) - fresh_count

                        status.update(
                            {
                                "fresh_ltp_count": fresh_count,
                                "stale_ltp_count": stale_count,
                                "oldest_ltp_age": max([r[4] for r in results]),
                                "newest_ltp_age": min([r[4] for r in results]),
                            }
                        )
                    else:
                        status.update(
                            {"fresh_ltp_count": 0, "stale_ltp_count": 0, "oldest_ltp_age": 0, "newest_ltp_age": 0}
                        )
                else:
                    status.update(
                        {"fresh_ltp_count": 0, "stale_ltp_count": 0, "oldest_ltp_age": 0, "newest_ltp_age": 0}
                    )

                return status

        except Exception as e:
            return {"error": str(e)}

    def get_subscription_status(self) -> dict:
        """Get current subscription status for monitoring"""
        try:
            status = self.get_realtime_status()

            with self.db_lock:
                self.cursor.execute("""
                    SELECT COUNT(*) as total_positions,
                           SUM(CASE WHEN is_subscribed = 1 THEN 1 ELSE 0 END) as current_positions
                    FROM positions
                """)
                result = self.cursor.fetchone()

                self.cursor.execute("""
                    SELECT COUNT(*) as total_ltp_records,
                           MAX(timestamp) as last_update
                    FROM ltp_data
                """)
                ltp_result = self.cursor.fetchone()

                status.update(
                    {
                        "total_positions_in_db": result[0] if result else 0,
                        "current_positions": result[1] if result else 0,
                        "total_ltp_records": ltp_result[0] if ltp_result else 0,
                        "last_ltp_update": ltp_result[1] if ltp_result else None,
                    }
                )

                return status

        except Exception as e:
            self.logger.exception(f"Error getting subscription status: {e}")
            return {"error": str(e)}

    def start(self):
        """Start the enhanced LTP subscriber"""
        try:
            self.logger.info("🚀 Starting Enhanced Zerodha LTP Subscriber...")
            self.logger.info(f"📅 Trading date: {self.current_date}")

            # Start enhanced subscription monitor in background thread
            monitor_thread = Thread(target=self.monitor_and_update_subscriptions, daemon=True)
            monitor_thread.start()
            self.logger.info("🔄 Enhanced subscription monitor started")

            # Start WebSocket connection (blocking call)
            self.logger.info("📡 Starting WebSocket connection...")
            self.ticker.connect(threaded=False)

        except KeyboardInterrupt:
            self.logger.info("⏹️ Stopping Enhanced LTP subscriber...")
            self.stop()
        except Exception as e:
            self.logger.exception(f"Error starting Enhanced LTP subscriber: {e}")
            raise

    def stop(self):
        """Stop the LTP subscriber and cleanup"""
        try:
            self.logger.info("🛑 Stopping Enhanced LTP subscriber...")

            # Flush any remaining batch data
            self.flush_batch_data()

            # Close WebSocket connection
            if hasattr(self, "ticker"):
                self.ticker.close()
                self.logger.info("📡 WebSocket connection closed")

            # Close database connection
            if hasattr(self, "conn"):
                self.conn.close()
                self.logger.info("💾 Database connection closed")

            self.logger.info("✅ Enhanced LTP subscriber stopped successfully")

        except Exception as e:
            self.logger.exception(f"Error stopping LTP subscriber: {e}")


def main():
    """Main function"""
    subscriber = EnhancedZerodhaLTPSubscriber()

    try:
        subscriber.start()
    except KeyboardInterrupt:
        print("\n⏹️ Shutting down...")
    finally:
        subscriber.stop()


if __name__ == "__main__":
    main()
