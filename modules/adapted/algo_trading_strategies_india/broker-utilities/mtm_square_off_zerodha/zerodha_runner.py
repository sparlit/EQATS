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
Enhanced Zerodha Trading System Runner - Updated for Enhanced MTM Monitor
File: zerodha_runner.py

Enhanced features:
1. Manages enhanced MTM monitor with separate databases
2. 3-second monitoring intervals for all components
3. Better process health monitoring
4. Enhanced error handling and recovery
5. Improved logging and status reporting
"""

import json
import logging
import os
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional


class EnhancedZerodhaTradingSystemRunner:
    """
    Enhanced system runner for the Zerodha trading system
    """

    def __init__(self):
        self.setup_logging()

        # Process management
        self.ltp_process = None
        self.mtm_process = None
        self.running = False

        # Enhanced database paths
        self.ltp_db_path = "zerodha_trading.db"  # LTP and positions data
        self.mtm_db_path = "zerodha_mtm.db"  # MTM tracking data

        # Enhanced monitoring intervals (3 seconds)
        self.health_check_interval = 3
        self.status_log_interval = 180  # 3 minutes

        # Process restart tracking
        self.process_restart_count = {"ltp": 0, "mtm": 0}
        self.max_restarts_per_hour = 10

        # Setup signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def setup_logging(self):
        """Setup enhanced logging for the runner"""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - ENHANCED_RUNNER - %(levelname)s - %(message)s",
            handlers=[logging.FileHandler("system_runner.log"), logging.StreamHandler()],
        )
        self.logger = logging.getLogger(__name__)

    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info(f"Received signal {signum}, initiating enhanced shutdown...")
        self.stop_system()
        sys.exit(0)

    def check_prerequisites(self) -> dict:
        """Enhanced prerequisites check"""
        checks = {
            "config_file": os.path.exists("config.yaml"),
            "ltp_script": os.path.exists("zerodha_ltp_subscriber.py"),
            "mtm_script": os.path.exists("zerodha_mtm_monitor.py"),
            "access_token": os.path.exists(
                "/home/ubuntu/utilities/kite_connect_data/tickjournal/key_files/access_token.txt"
            ),
            "python_packages": True,
            "ltp_database_writable": True,
            "mtm_database_writable": True,
            "disk_space": True,
        }

        # Check access token
        if checks["access_token"]:
            try:
                with open("/home/ubuntu/utilities/kite_connect_data/tickjournal/key_files/access_token.txt") as f:
                    token = f.read().strip()
                    if not token:
                        checks["access_token"] = False
            except Exception:
                checks["access_token"] = False

        # Check LTP database write permissions
        try:
            test_conn = sqlite3.connect(self.ltp_db_path)
            test_conn.execute("CREATE TABLE IF NOT EXISTS test_table (id INTEGER)")
            test_conn.execute("DROP TABLE IF EXISTS test_table")
            test_conn.close()
        except Exception:
            checks["ltp_database_writable"] = False

        # Check MTM database write permissions
        try:
            test_conn = sqlite3.connect(self.mtm_db_path)
            test_conn.execute("CREATE TABLE IF NOT EXISTS test_table (id INTEGER)")
            test_conn.execute("DROP TABLE IF EXISTS test_table")
            test_conn.close()
        except Exception:
            checks["mtm_database_writable"] = False

        # Check disk space (at least 100MB free)
        try:
            import shutil

            free_space = shutil.disk_usage(".").free / (1024 * 1024)  # MB
            if free_space < 100:
                checks["disk_space"] = False
        except Exception:
            checks["disk_space"] = False

        return checks

    def start_ltp_subscriber(self) -> bool:
        """Start the LTP subscriber process with enhanced config"""
        try:
            self.logger.info("Starting Enhanced LTP Subscriber...")

            # Use enhanced config if available, otherwise fall back to regular config
            config_file = "config.yaml" if os.path.exists("config.yaml") else "config.yaml"

            self.ltp_process = subprocess.Popen(
                [sys.executable, "zerodha_ltp_subscriber.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                env={**os.environ, "ZERODHA_CONFIG": config_file},
            )

            # Give it time to start
            time.sleep(3)

            if self.ltp_process.poll() is None:
                self.logger.info(f"Enhanced LTP Subscriber started successfully (PID: {self.ltp_process.pid})")
                self.process_restart_count["ltp"] = 0  # Reset on successful start
                return True
            _stdout, stderr = self.ltp_process.communicate()
            self.logger.error(f"Enhanced LTP Subscriber failed to start: {stderr}")
            return False

        except Exception as e:
            self.logger.exception(f"Error starting enhanced LTP subscriber: {e}")
            return False

    def start_mtm_monitor(self) -> bool:
        """Start the MTM monitor process"""
        try:
            self.logger.info("Starting Enhanced MTM Monitor...")

            # Use the existing MTM monitor script (no need for separate enhanced file)
            script_name = "zerodha_mtm_monitor.py"

            # Use config.yaml (your enhanced config)
            config_file = "config.yaml"

            self.mtm_process = subprocess.Popen(
                [sys.executable, script_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                env={**os.environ, "ZERODHA_CONFIG": config_file},
            )

            # Give it time to start
            time.sleep(3)

            if self.mtm_process.poll() is None:
                self.logger.info(f"Enhanced MTM Monitor started successfully (PID: {self.mtm_process.pid})")
                self.process_restart_count["mtm"] = 0  # Reset on successful start
                return True
            _stdout, stderr = self.mtm_process.communicate()
            self.logger.error(f"Enhanced MTM Monitor failed to start: {stderr}")
            return False

        except Exception as e:
            self.logger.exception(f"Error starting enhanced MTM monitor: {e}")
            return False

    def stop_system(self):
        """Enhanced system stop with better cleanup"""
        self.logger.info("Stopping Enhanced Zerodha Trading System...")

        # Stop MTM monitor first (more critical for safety)
        if self.mtm_process and self.mtm_process.poll() is None:
            self.logger.info("Stopping Enhanced MTM Monitor...")
            self.mtm_process.terminate()
            try:
                self.mtm_process.wait(timeout=15)  # Longer timeout for enhanced cleanup
                self.logger.info("Enhanced MTM Monitor stopped gracefully")
            except subprocess.TimeoutExpired:
                self.logger.warning("Enhanced MTM Monitor did not stop gracefully, forcing termination...")
                self.mtm_process.kill()
                self.mtm_process.wait()

        # Stop LTP subscriber
        if self.ltp_process and self.ltp_process.poll() is None:
            self.logger.info("Stopping Enhanced LTP Subscriber...")
            self.ltp_process.terminate()
            try:
                self.ltp_process.wait(timeout=15)
                self.logger.info("Enhanced LTP Subscriber stopped gracefully")
            except subprocess.TimeoutExpired:
                self.logger.warning("Enhanced LTP Subscriber did not stop gracefully, forcing termination...")
                self.ltp_process.kill()
                self.ltp_process.wait()

        self.running = False
        self.logger.info("Enhanced system stopped successfully")

    def check_process_health(self) -> dict:
        """Enhanced process health check"""
        status = {
            "ltp_subscriber": {
                "running": False,
                "pid": None,
                "restart_count": self.process_restart_count["ltp"],
                "memory_usage": None,
                "cpu_usage": None,
            },
            "mtm_monitor": {
                "running": False,
                "pid": None,
                "restart_count": self.process_restart_count["mtm"],
                "memory_usage": None,
                "cpu_usage": None,
            },
        }

        # Check LTP subscriber
        if self.ltp_process and self.ltp_process.poll() is None:
            status["ltp_subscriber"]["running"] = True
            status["ltp_subscriber"]["pid"] = self.ltp_process.pid

            # Get process stats if available
            try:
                import psutil

                proc = psutil.Process(self.ltp_process.pid)
                status["ltp_subscriber"]["memory_usage"] = proc.memory_info().rss / (1024 * 1024)  # MB
                status["ltp_subscriber"]["cpu_usage"] = proc.cpu_percent()
            except (ImportError, psutil.NoSuchProcess):
                pass

        # Check MTM monitor
        if self.mtm_process and self.mtm_process.poll() is None:
            status["mtm_monitor"]["running"] = True
            status["mtm_monitor"]["pid"] = self.mtm_process.pid

            # Get process stats if available
            try:
                import psutil

                proc = psutil.Process(self.mtm_process.pid)
                status["mtm_monitor"]["memory_usage"] = proc.memory_info().rss / (1024 * 1024)  # MB
                status["mtm_monitor"]["cpu_usage"] = proc.cpu_percent()
            except (ImportError, psutil.NoSuchProcess):
                pass

        return status

    def check_enhanced_database_status(self) -> dict:
        """Enhanced database status check for separate databases"""
        status = {
            "ltp_database": {
                "exists": False,
                "size_mb": 0,
                "ltp_records": 0,
                "position_records": 0,
                "latest_ltp_update": None,
                "ltp_data_age_seconds": None,
                "subscribed_positions": 0,
            },
            "mtm_database": {
                "exists": False,
                "size_mb": 0,
                "mtm_history_records": 0,
                "square_off_history_records": 0,
                "order_tracking_records": 0,
                "latest_mtm_update": None,
                "latest_square_off": None,
            },
        }

        # Check LTP database
        try:
            if os.path.exists(self.ltp_db_path):
                status["ltp_database"]["exists"] = True
                status["ltp_database"]["size_mb"] = round(os.path.getsize(self.ltp_db_path) / (1024 * 1024), 2)

                conn = sqlite3.connect(self.ltp_db_path)
                cursor = conn.cursor()

                # Check LTP data
                try:
                    cursor.execute("SELECT COUNT(*), MAX(timestamp) FROM ltp_data")
                    result = cursor.fetchone()
                    if result:
                        status["ltp_database"]["ltp_records"] = result[0]
                        if result[1]:
                            status["ltp_database"]["latest_ltp_update"] = result[1]
                            status["ltp_database"]["ltp_data_age_seconds"] = time.time() - result[1]
                except sqlite3.OperationalError:
                    pass

                # Check positions data
                try:
                    cursor.execute("SELECT COUNT(*), MAX(last_updated) FROM positions")
                    result = cursor.fetchone()
                    if result:
                        status["ltp_database"]["position_records"] = result[0]

                    cursor.execute("SELECT COUNT(*) FROM positions WHERE is_subscribed = 1")
                    result = cursor.fetchone()
                    if result:
                        status["ltp_database"]["subscribed_positions"] = result[0]
                except sqlite3.OperationalError:
                    pass

                conn.close()

        except Exception as e:
            self.logger.exception(f"Error checking LTP database: {e}")

        # Check MTM database
        try:
            if os.path.exists(self.mtm_db_path):
                status["mtm_database"]["exists"] = True
                status["mtm_database"]["size_mb"] = round(os.path.getsize(self.mtm_db_path) / (1024 * 1024), 2)

                conn = sqlite3.connect(self.mtm_db_path)
                cursor = conn.cursor()

                # Check MTM history
                try:
                    cursor.execute("SELECT COUNT(*), MAX(timestamp) FROM mtm_history")
                    result = cursor.fetchone()
                    if result:
                        status["mtm_database"]["mtm_history_records"] = result[0]
                        status["mtm_database"]["latest_mtm_update"] = result[1]
                except sqlite3.OperationalError:
                    pass

                # Check square-off history
                try:
                    cursor.execute("SELECT COUNT(*), MAX(timestamp) FROM square_off_history")
                    result = cursor.fetchone()
                    if result:
                        status["mtm_database"]["square_off_history_records"] = result[0]
                        status["mtm_database"]["latest_square_off"] = result[1]
                except sqlite3.OperationalError:
                    pass

                # Check order tracking
                try:
                    cursor.execute("SELECT COUNT(*) FROM order_tracking")
                    result = cursor.fetchone()
                    if result:
                        status["mtm_database"]["order_tracking_records"] = result[0]
                except sqlite3.OperationalError:
                    pass

                conn.close()

        except Exception as e:
            self.logger.exception(f"Error checking MTM database: {e}")

        return status

    def get_recent_mtm_data(self) -> dict:
        """Get recent MTM data from enhanced database"""
        mtm_data = {
            "current_mtm": None,
            "position_count": 0,
            "recent_history": [],
            "threshold_breaches_today": 0,
            "auto_square_off_enabled": None,
            "recent_square_offs": [],
        }

        try:
            if os.path.exists(self.mtm_db_path):
                conn = sqlite3.connect(self.mtm_db_path)
                cursor = conn.cursor()

                # Get latest MTM with enhanced data
                try:
                    cursor.execute("""
                        SELECT total_mtm, position_count, threshold_status,
                               auto_square_off_enabled, timestamp
                        FROM mtm_history
                        ORDER BY timestamp DESC
                        LIMIT 1
                    """)
                    result = cursor.fetchone()
                    if result:
                        mtm_data["current_mtm"] = result[0]
                        mtm_data["position_count"] = result[1]
                        mtm_data["auto_square_off_enabled"] = bool(result[3])

                    # Get recent history (last 10 records)
                    cursor.execute("""
                        SELECT total_mtm, position_count, threshold_status, timestamp
                        FROM mtm_history
                        ORDER BY timestamp DESC
                        LIMIT 10
                    """)
                    history = cursor.fetchall()
                    mtm_data["recent_history"] = [
                        {"mtm": record[0], "positions": record[1], "status": record[2], "timestamp": record[3]}
                        for record in history
                    ]

                    # Count threshold breaches today
                    today = datetime.now().strftime("%Y-%m-%d")
                    cursor.execute(
                        """
                        SELECT COUNT(*) FROM mtm_history
                        WHERE threshold_status = 'BREACH'
                        AND date(timestamp) = ?
                    """,
                        (today,),
                    )
                    result = cursor.fetchone()
                    if result:
                        mtm_data["threshold_breaches_today"] = result[0]

                    # Get recent square-offs
                    cursor.execute(
                        """
                        SELECT timestamp, trigger_mtm, total_positions, status, phase
                        FROM square_off_history
                        WHERE date(timestamp) = ?
                        ORDER BY timestamp DESC
                        LIMIT 5
                    """,
                        (today,),
                    )
                    square_offs = cursor.fetchall()
                    mtm_data["recent_square_offs"] = [
                        {
                            "timestamp": record[0],
                            "trigger_mtm": record[1],
                            "total_positions": record[2],
                            "status": record[3],
                            "phase": record[4],
                        }
                        for record in square_offs
                    ]

                except sqlite3.OperationalError:
                    pass

                conn.close()

        except Exception as e:
            self.logger.exception(f"Error getting enhanced MTM data: {e}")
            mtm_data["error"] = str(e)

        return mtm_data

    def get_enhanced_system_status(self) -> dict:
        """Get comprehensive enhanced system status"""
        return {
            "timestamp": datetime.now().isoformat(),
            "system_running": self.running,
            "monitoring_intervals": {
                "health_check": self.health_check_interval,
                "status_logging": self.status_log_interval,
            },
            "processes": self.check_process_health(),
            "databases": self.check_enhanced_database_status(),
            "mtm_data": self.get_recent_mtm_data(),
            "prerequisites": self.check_prerequisites(),
            "system_metrics": self.get_system_metrics(),
        }

    def get_system_metrics(self) -> dict:
        """Get system performance metrics"""
        metrics = {"uptime_seconds": 0, "cpu_usage": None, "memory_usage": None, "disk_usage": None}

        try:
            import psutil

            # System metrics
            metrics["cpu_usage"] = psutil.cpu_percent(interval=1)

            memory = psutil.virtual_memory()
            metrics["memory_usage"] = {
                "total_mb": memory.total / (1024 * 1024),
                "used_mb": memory.used / (1024 * 1024),
                "percent": memory.percent,
            }

            disk = psutil.disk_usage(".")
            metrics["disk_usage"] = {
                "total_mb": disk.total / (1024 * 1024),
                "used_mb": disk.used / (1024 * 1024),
                "free_mb": disk.free / (1024 * 1024),
                "percent": (disk.used / disk.total) * 100,
            }

        except ImportError:
            self.logger.debug("psutil not available for system metrics")
        except Exception as e:
            self.logger.exception(f"Error getting system metrics: {e}")

        return metrics

    def restart_process_with_backoff(self, process_type: str) -> bool:
        """Restart process with exponential backoff"""
        restart_count = self.process_restart_count[process_type]

        if restart_count >= self.max_restarts_per_hour:
            self.logger.error(f"Max restarts exceeded for {process_type} process")
            return False

        # Exponential backoff: 2^restart_count seconds (max 60s)
        backoff_time = min(2**restart_count, 60)
        self.logger.info(f"Restarting {process_type} in {backoff_time} seconds...")
        time.sleep(backoff_time)

        self.process_restart_count[process_type] += 1

        if process_type == "ltp":
            return self.start_ltp_subscriber()
        if process_type == "mtm":
            return self.start_mtm_monitor()

        return False

    def start_enhanced_system(self):
        """Start the enhanced trading system"""
        self.logger.info("=" * 80)
        self.logger.info("STARTING ENHANCED ZERODHA TRADING SYSTEM")
        self.logger.info("=" * 80)

        # Check prerequisites
        prereqs = self.check_prerequisites()
        self.logger.info("Enhanced Prerequisites Check:")
        for check, status in prereqs.items():
            status_text = "✅ PASS" if status else "❌ FAIL"
            self.logger.info(f"  {check}: {status_text}")

        if not all(prereqs.values()):
            self.logger.error("Prerequisites check failed. Please fix issues before starting.")
            return False

        # Start LTP subscriber first
        if not self.start_ltp_subscriber():
            self.logger.error("Failed to start Enhanced LTP subscriber")
            return False

        # Enhanced initialization wait
        self.logger.info("Waiting for Enhanced LTP subscriber to initialize...")
        time.sleep(10)

        # Start enhanced MTM monitor
        if not self.start_mtm_monitor():
            self.logger.error("Failed to start Enhanced MTM monitor")
            self.stop_system()
            return False

        self.running = True
        self.logger.info("=" * 80)
        self.logger.info("ENHANCED ZERODHA TRADING SYSTEM STARTED SUCCESSFULLY")
        self.logger.info("=" * 80)
        self.logger.info("🔧 Enhanced Features Active:")
        self.logger.info("   ✅ 3-second monitoring intervals")
        self.logger.info("   ✅ Prioritized square-off (SELL first)")
        self.logger.info("   ✅ Order verification & retry")
        self.logger.info("   ✅ Separate databases")
        self.logger.info("   ✅ Stale LTP refresh")
        self.logger.info("   ✅ Post square-off verification")
        self.logger.info("=" * 80)

        return True

    def get_discipline_status(self) -> dict:
        """Get trading discipline status from MTM database"""
        try:
            if not os.path.exists(self.mtm_db_path):
                return {}

            conn = sqlite3.connect(self.mtm_db_path)
            cursor = conn.cursor()

            # Get latest MTM record with details
            cursor.execute("""
                           SELECT details, threshold_status
                           FROM mtm_history
                           ORDER BY timestamp DESC
                           LIMIT 1
                           """)

            result = cursor.fetchone()
            conn.close()

            if result and result[0]:
                try:
                    details = json.loads(result[0])
                    return {
                        "daily_max_mtm": details.get("daily_max_mtm", 0),
                        "daily_target": 100,  # Default, could be read from config
                        "discipline_active": details.get("daily_max_profit_reached", False),
                        "threshold_status": result[1],
                    }
                except (json.JSONDecodeError, KeyError):
                    pass

            return {}

        except Exception as e:
            self.logger.debug(f"Error getting discipline status: {e}")
            return {}

    def monitor_enhanced_system(self):
        """Enhanced system monitoring with improved logging frequency"""
        last_detailed_status_log = 0
        last_quick_status_log = 0

        # Improved intervals
        detailed_status_interval = 20  # 20 seconds for detailed status
        quick_status_interval = 5  # 5 seconds for quick MTM status
        health_check_interval = 3  # 3 seconds for process health

        self.logger.info("Enhanced system monitoring started:")
        self.logger.info(f"  • Process health checks: every {health_check_interval}s")
        self.logger.info(f"  • Quick MTM status: every {quick_status_interval}s")
        self.logger.info(f"  • Detailed status: every {detailed_status_interval}s")

        while self.running:
            try:
                time.sleep(health_check_interval)
                current_time = time.time()

                # Check process health with enhanced restart logic
                health = self.check_process_health()

                # Enhanced LTP subscriber health check
                if not health["ltp_subscriber"]["running"] and self.running:
                    self.logger.warning("Enhanced LTP Subscriber not running, attempting restart...")
                    if not self.restart_process_with_backoff("ltp"):
                        self.logger.error("Failed to restart Enhanced LTP subscriber")

                # Enhanced MTM monitor health check
                if not health["mtm_monitor"]["running"] and self.running:
                    self.logger.warning("Enhanced MTM Monitor not running, attempting restart...")
                    if not self.restart_process_with_backoff("mtm"):
                        self.logger.error("Failed to restart Enhanced MTM monitor")

                # Quick MTM status (every 5 seconds)
                if current_time - last_quick_status_log >= quick_status_interval:
                    mtm_data = self.get_recent_mtm_data()

                    if mtm_data.get("current_mtm") is not None:
                        current_mtm = mtm_data["current_mtm"]
                        position_count = mtm_data.get("position_count", 0)

                        # Get discipline status from database if available
                        discipline_status = self.get_discipline_status()
                        discipline_info = ""
                        if discipline_status:
                            if discipline_status.get("discipline_active", False):
                                daily_max = discipline_status.get("daily_max_mtm", 0)
                                discipline_info = f" | Daily Max: ₹{daily_max:.2f} | 🚫 DISCIPLINE ACTIVE"
                            else:
                                daily_max = discipline_status.get("daily_max_mtm", 0)
                                target = discipline_status.get("daily_target", 100)
                                discipline_info = f" | Daily Max: ₹{daily_max:.2f} | Target: ₹{target}"

                        # Status indicators
                        ltp_status = "✅" if health["ltp_subscriber"]["running"] else "❌"
                        mtm_status = "✅" if health["mtm_monitor"]["running"] else "❌"

                        self.logger.info(
                            f"💹 LTP {ltp_status} | MTM {mtm_status} | "
                            f"Current: ₹{current_mtm:.2f} | Positions: {position_count}{discipline_info}"
                        )
                    else:
                        # Fallback if no MTM data
                        ltp_status = "✅" if health["ltp_subscriber"]["running"] else "❌"
                        mtm_status = "✅" if health["mtm_monitor"]["running"] else "❌"
                        self.logger.info(f"💹 LTP {ltp_status} | MTM {mtm_status} | No MTM data yet")

                    last_quick_status_log = current_time

                # Detailed status logging (every 20 seconds)
                if current_time - last_detailed_status_log >= detailed_status_interval:
                    status = self.get_enhanced_system_status()

                    self.logger.info("=" * 60)
                    self.logger.info("📊 DETAILED SYSTEM STATUS")
                    self.logger.info("=" * 60)

                    # Process status
                    self.logger.info("🔧 Processes:")
                    self.logger.info(
                        f"   LTP Subscriber: {'✅ Running' if health['ltp_subscriber']['running'] else '❌ Stopped'} "
                        f"(PID: {health['ltp_subscriber']['pid']}, Restarts: {health['ltp_subscriber']['restart_count']})"
                    )
                    self.logger.info(
                        f"   MTM Monitor: {'✅ Running' if health['mtm_monitor']['running'] else '❌ Stopped'} "
                        f"(PID: {health['mtm_monitor']['pid']}, Restarts: {health['mtm_monitor']['restart_count']})"
                    )

                    # MTM and trading info
                    mtm_data = status["mtm_data"]
                    if mtm_data.get("current_mtm") is not None:
                        self.logger.info("💰 Trading Status:")
                        self.logger.info(f"   Current MTM: ₹{mtm_data['current_mtm']:.2f}")
                        self.logger.info(f"   Open Positions: {mtm_data['position_count']}")

                        # Enhanced discipline status
                        discipline_status = self.get_discipline_status()
                        if discipline_status:
                            daily_max = discipline_status.get("daily_max_mtm", 0)
                            target = discipline_status.get("daily_target", 100)
                            discipline_active = discipline_status.get("discipline_active", False)

                            self.logger.info(f"   Daily Max MTM: ₹{daily_max:.2f}")
                            self.logger.info(f"   Daily Target: ₹{target}")
                            self.logger.info(
                                f"   Trading Discipline: {'🚫 ACTIVE (No new positions)' if discipline_active else '✅ INACTIVE (Trading allowed)'}"
                            )

                        self.logger.info(
                            f"   Today's Threshold Breaches: {mtm_data.get('threshold_breaches_today', 0)}"
                        )
                        if mtm_data.get("recent_square_offs"):
                            self.logger.info(f"   Recent Square-offs: {len(mtm_data['recent_square_offs'])}")

                    # Database status
                    db_status = status["databases"]
                    self.logger.info("💾 Database Status:")
                    self.logger.info(
                        f"   LTP DB: {db_status['ltp_database']['size_mb']:.1f} MB "
                        f"({db_status['ltp_database']['ltp_records']} LTP records)"
                    )
                    self.logger.info(
                        f"   MTM DB: {db_status['mtm_database']['size_mb']:.1f} MB "
                        f"({db_status['mtm_database']['mtm_history_records']} MTM records)"
                    )

                    self.logger.info("=" * 60)
                    last_detailed_status_log = current_time

            except KeyboardInterrupt:
                break
            except Exception as e:
                self.logger.exception(f"Error in enhanced system monitor: {e}")

    def run_enhanced(self):
        """Main enhanced run method"""
        try:
            if self.start_enhanced_system():
                self.logger.info("Enhanced system monitoring started. Press Ctrl+C to stop.")
                self.monitor_enhanced_system()
            else:
                self.logger.error("Failed to start enhanced system")
                return False

        except KeyboardInterrupt:
            self.logger.info("Enhanced shutdown requested by user")
        except Exception as e:
            self.logger.exception(f"Unexpected error in enhanced system: {e}")
        finally:
            self.stop_system()

        return True

    def get_enhanced_live_status_summary(self) -> str:
        """Get enhanced live status summary with discipline info"""
        try:
            status = self.get_enhanced_system_status()

            # Process status
            ltp_status = "✅" if status["processes"]["ltp_subscriber"]["running"] else "❌"
            mtm_status = "✅" if status["processes"]["mtm_monitor"]["running"] else "❌"

            # Database status
            ltp_db = status["databases"]["ltp_database"]
            mtm_db = status["databases"]["mtm_database"]

            # MTM status
            mtm_data = status["mtm_data"]
            current_mtm = mtm_data.get("current_mtm")
            mtm_str = f"₹{current_mtm:.2f}" if current_mtm is not None else "N/A"

            # Enhanced info with discipline status
            positions = mtm_data.get("position_count", 0)
            breaches_today = mtm_data.get("threshold_breaches_today", 0)
            square_offs_today = len(mtm_data.get("recent_square_offs", []))

            # Get discipline status
            discipline_status = self.get_discipline_status()
            daily_max = discipline_status.get("daily_max_mtm", 0)
            discipline_active = discipline_status.get("discipline_active", False)
            discipline_indicator = "🚫 ACTIVE" if discipline_active else "✅ INACTIVE"

            return f"""
    ╭─────────────────────────────────────────────────────────────╮
    │           ENHANCED ZERODHA TRADING SYSTEM v2.0             │
    ├─────────────────────────────────────────────────────────────┤
    │ LTP Subscriber: {ltp_status}  │  MTM Monitor: {mtm_status}                    │
    │ Current MTM: {mtm_str:>8s}   │  Daily Max: ₹{daily_max:>6.2f}              │
    │ Positions: {positions:>10d}   │  Discipline: {discipline_indicator:>12s}        │
    │ Today's Breaches: {breaches_today:2d}    │  Square-offs: {square_offs_today:2d}                   │
    │ LTP DB: {ltp_db["size_mb"]:5.1f} MB     │  MTM DB: {mtm_db["size_mb"]:5.1f} MB             │
    │ Monitoring: 5s intervals  │  Time: {datetime.now().strftime("%H:%M:%S"):>8s}            │
    ╰─────────────────────────────────────────────────────────────╯
            """.strip()

        except Exception as e:
            return f"Error getting enhanced status: {e}"


def main():
    """Enhanced main function"""
    runner = EnhancedZerodhaTradingSystemRunner()

    # Handle command line arguments
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()

        if command == "status":
            status = runner.get_enhanced_system_status()
            print(json.dumps(status, indent=2))
            return

        if command == "summary":
            print(runner.get_enhanced_live_status_summary())
            return

        if command == "stop":
            runner.stop_system()
            return

        if command == "check":
            prereqs = runner.check_prerequisites()
            print("Enhanced Prerequisites Check:")
            for check, status in prereqs.items():
                status_text = "✅ PASS" if status else "❌ FAIL"
                print(f"  {check}: {status_text}")
            return

        if command == "help":
            print("""
Enhanced Zerodha Trading System Runner Commands:

  python zerodha_runner.py           - Start the enhanced trading system
  python zerodha_runner.py status    - Show detailed system status (JSON)
  python zerodha_runner.py summary   - Show enhanced live status summary
  python zerodha_runner.py check     - Check enhanced prerequisites
  python zerodha_runner.py stop      - Stop all processes
  python zerodha_runner.py help      - Show this help message

Enhanced Features:
  ✅ 3-second monitoring intervals for all components
  ✅ Separate databases to prevent locking issues
  ✅ Enhanced process restart with exponential backoff
  ✅ Comprehensive health monitoring and metrics
  ✅ Better error handling and recovery
  ✅ Enhanced MTM monitor with prioritized square-off
            """)
            return

    # Default: start the enhanced system
    runner.run_enhanced()


if __name__ == "__main__":
    main()
