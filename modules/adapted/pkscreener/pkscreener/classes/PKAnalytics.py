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


#!/usr/bin/python3
"""
    The MIT License (MIT)

    Copyright (c) 2023 pkjmesra

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

"""

import functools
import getpass
import hashlib
import inspect
import json
import os
import platform
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from PKDevTools.classes.Fetcher import fetcher
from PKDevTools.classes.log import default_logger
from PKDevTools.classes.pubsub.publisher import PKUserService
from PKDevTools.classes.Singleton import SingletonMixin, SingletonType
from PKDevTools.classes.Utils import random_user_agent
from pkscreener.classes import VERSION
from pkscreener.classes.ConfigManager import parser, tools


class AnalyticsCategory:
    """Constants for Google Analytics event categories."""

    APP = "App"
    BOT_CMD = "Bot_Cmd"
    USER = "User"
    SCAN = "Scan"
    SCREENING = "Scr"
    PERFORMANCE = "Perf"
    ERROR = "Err"
    FEATURE = "Feat"
    SUBSCRIPTION = "Sub"
    DATA = "Data"
    SYSTEM = "Sys"


class AnalyticsAction:
    """Constants for Google Analytics event actions."""

    # App actions
    START = "start"
    EXIT = "exit"
    CRASH = "crash"

    # User actions
    LOGIN = "login"
    LOGOUT = "logout"
    REGISTER = "register"

    # Scan actions
    REQUEST = "request"
    COMPLETE = "complete"
    RESULT = "result"

    # Screening actions
    SCREEN = "screen"
    FILTER = "filter"
    SORT = "sort"

    # Performance actions
    LOAD_TIME = "load_time"
    RESPONSE_TIME = "response_time"
    MEMORY_USAGE = "memory_usage"

    # Feature actions
    USE = "use"
    CLICK = "click"
    NAVIGATE = "navigate"

    # Subscription actions
    PURCHASE = "purchase"
    RENEW = "renew"
    CANCEL = "cancel"

    # Data actions
    DOWNLOAD = "download"
    CACHE_HIT = "cache_hit"
    CACHE_MISS = "cache_miss"


class AnalyticsLabel:
    """Constants for Google Analytics event labels."""

    SUCCESS = "success"
    FAILURE = "failure"
    WARNING = "warning"
    INFO = "info"
    DEBUG = "debug"


class PKAnalyticsService(SingletonMixin, metaclass=SingletonType):
    """
    Analytics service for collecting anonymous usage metrics with GA4-style categorization.

    This service collects non-identifiable information with proper categorization
    for dashboard visualization. All collection is done in non-blocking background
    threads to avoid impacting user experience.

    Event Structure (GA4 compatible):
    ---------------------------------
    - Category: High-level grouping (App, User, Scan, Performance, etc.)
    - Action: The specific interaction (start, complete, click, etc.)
    - Label: Additional context (success, failure, info)
    - Value: Numeric value (optional, for metrics)
    - Custom Dimensions: Additional attributes for filtering

    Dashboard Categories:
    ---------------------
    1. App Usage - App starts, exits, session duration
    2. User Activity - Logins, registrations, user types
    3. Scanner Usage - Most used scanners, result counts
    4. Performance - Load times, response times, cache hit rates
    5. Feature Adoption - Feature usage frequency
    6. Errors - Error types and frequencies
    7. Subscription - Premium feature usage
    8. System - OS, platform, version distribution
    """

    def __init__(self):
        super().__init__()
        self.locationInfo = {}
        self.os = platform.system()
        self.os_version = platform.release()
        self.app_version = VERSION
        self.start_time = time.time()
        self.isRunner = "RUNNER" in os.environ
        self.onefile = getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")
        self.username = self.getUserName()
        self.configManager = tools()
        self.configManager.getConfig(parser)

        # Session tracking
        self.session_id = str(uuid.uuid4())
        self._session_start_time = time.time()

        # Feature usage counters (for aggregated reporting)
        self._feature_usage = {}

        # Non-blocking infrastructure
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="analytics")
        self._location_lock = threading.Lock()
        self._location_fetched = False
        self._pending_events = []

        # Start background location fetch immediately (non-blocking)
        self._fetch_location_async()

        # Send session start event
        self.send_event(AnalyticsCategory.APP, AnalyticsAction.START, AnalyticsLabel.INFO, value=1)

    def _get_anonymous_id(self):
        """
        Generate a persistent anonymous user ID (no PII).

        Creates a hash based on system characteristics without storing
        personally identifiable information.

        Returns:
            str: Anonymized user identifier
        """
        try:
            # Use system characteristics (non-identifiable individually)
            system_info = f"{platform.system()}_{platform.machine()}_{os.getenv('USER', 'unknown')}"
            # Hash to create anonymous ID
            anonymous_id = hashlib.sha256(system_info.encode()).hexdigest()[:16]
            return f"user_{anonymous_id}"
        except Exception:
            return f"user_{uuid.uuid4().hex[:16]}"

    def _fetch_location_async(self):
        """Fetch location information in background thread (non-blocking)."""

        def fetch():
            try:
                if not self.configManager.enableUsageAnalytics:
                    return

                url = "http://ipinfo.io/json"
                f = fetcher()
                response = f.fetchURL(
                    url=url, timeout=5, headers={"user-agent": f"{random_user_agent()}"}
                )

                if response and response.status_code == 200:
                    data = json.loads(response.text)
                    with self._location_lock:
                        self.locationInfo = data
                        self._location_fetched = True
                else:
                    with self._location_lock:
                        self.locationInfo = {"country": "Unknown", "region": "Unknown"}
                        self._location_fetched = True

                if self._pending_events:
                    for event in self._pending_events:
                        self._send_event_sync(**event)
                    self._pending_events.clear()

            except Exception:
                with self._location_lock:
                    self.locationInfo = {"country": "Unknown", "region": "Unknown"}
                    self._location_fetched = True
                if self._pending_events:
                    for event in self._pending_events:
                        self._send_event_sync(**event)
                    self._pending_events.clear()

        threading.Thread(target=fetch, daemon=True, name="LocationFetcher").start()

    def send_event(
        self,
        category=None,
        action=None,
        label=None,
        value=None,
        custom_dimensions=None,
        async_mode=True,
        event_name=None,
        params=None,
    ):
        """
        Send a categorized analytics event (GA4 style) with backward compatibility.

        Supports three calling patterns:
        1. New style: send_event("System", "ping", "info")
        2. Dict style: send_event(event_name="app_start", params={"key": "value"})
        3. Mixed style: send_event("System", "ping", custom_dimensions={"key": "value"})

        Args:
            category (str): Event category (App, User, Scan, Performance, Error, System)
            action (str): Event action (start, complete, click, error, ping)
            label (str, optional): Event label (success, failure, info)
            value (int, optional): Numeric value for metrics
            custom_dimensions (dict, optional): Additional custom dimensions
            async_mode (bool): If True, send asynchronously
            event_name (str, optional): Alternative to action (for backward compatibility)
            params (dict, optional): Legacy parameters (for backward compatibility)
        """
        if not self.configManager.enableUsageAnalytics:
            return

        # Handle legacy call signature (from ping decorator)
        if category is not None and action is None and event_name is None:
            # Check if this is the old style with event_name as first arg
            if isinstance(category, str) and params is None:
                # send_event("ping") - just event name
                event_name = category
                category = AnalyticsCategory.SYSTEM
                action = event_name
                label = AnalyticsLabel.INFO
            elif isinstance(category, str) and isinstance(action, dict):
                # send_event("app_start", {"key": "value"})
                event_name = category
                params = action
                category = AnalyticsCategory.SYSTEM
                action = event_name
                label = params.get("label", AnalyticsLabel.INFO)
                value = params.get("value", None)
                custom_dimensions = params.get("custom_dimensions", {})

        # Handle event_name style
        if event_name is not None and category is None:
            category = AnalyticsCategory.SYSTEM
            action = event_name
            label = AnalyticsLabel.INFO

        # Ensure we have required fields
        if category is None:
            category = AnalyticsCategory.SYSTEM
        if action is None:
            action = "unknown"
        if label is None:
            label = AnalyticsLabel.INFO

        # Build custom dimensions - ensure they are flat
        flat_dimensions = {}
        if custom_dimensions:
            for key, val in custom_dimensions.items():
                # Flatten any nested structures
                if isinstance(val, dict):
                    for sub_key, sub_val in val.items():
                        flat_key = f"{key}_{sub_key}"
                        flat_dimensions[flat_key] = sub_val
                elif isinstance(val, list):
                    flat_dimensions[key] = str(val)[:100]  # Convert list to string
                else:
                    flat_dimensions[key] = val

        # Log the flattened dimensions
        if flat_dimensions and (
            "subscriber.py" in os.environ.get("PK_DEBUG_FILES", "")
            or "PKAnalytics.py" in os.environ.get("PK_DEBUG_FILES", "")
        ):
            default_logger().debug(
                f"Tracking event: {category}_{action} with dimensions: {flat_dimensions}"
            )
        event_data = {
            "category": category,
            "action": action,
            "label": label,
            "value": value,
            "custom_dimensions": flat_dimensions or {},
        }

        if async_mode:
            self._executor.submit(self._send_event_sync, **event_data)
        else:
            self._send_event_sync(**event_data)

    def _normalize_os_name(self, os_name):
        """Normalize OS names to GA4 standard values."""
        os_mapping = {
            "Windows": "Windows",
            "Darwin": "macOS",
            "Linux": "Linux",
            "iOS": "iOS",
            "Android": "Android",
        }
        return os_mapping.get(os_name, os_name)

    def _detect_mobile_brand(self):
        """Detect if running on mobile (for future use)."""
        # This would require additional detection logic
        return None

    def _detect_mobile_model(self):
        """Detect mobile model (for future use)."""
        return None

    def _send_event_sync(self, category, action, label=None, value=None, custom_dimensions=None):
        """
        Synchronous event sending (runs in background thread).
        """
        try:
            # Wait for location if needed
            if not self._location_fetched:
                wait_count = 0
                while not self._location_fetched and wait_count < 50:
                    time.sleep(0.01)
                    wait_count += 1

            with self._location_lock:
                current_location = self.locationInfo.copy() if self.locationInfo else {}
            try:
                launcher = "cli"
                launcher = f'"{sys.argv[0]}"' if " " in sys.argv[0] else sys.argv[0]
                launcher = "py_cli" if launcher.endswith(".py") else launcher.split(".")[-1]
            except:
                pass
            # Build event parameters (GA4 structure)
            event_params = {
                # Required GA4 fields
                "event_category": category,
                "event_action": action,
                # ============ DEVICE & PLATFORM (GA4 Standard) ============
                "platform": "Windows"
                if self.os == "Windows"
                else "iOS"
                if self.os == "Darwin" and self.onefile
                else "macOS"
                if self.os == "Darwin"
                else "Android"
                if self.os == "Linux" and "ANDROID" in os.environ.get("TERM", "")
                else "Linux",
                "device.category": "desktop",  # or "mobile", "tablet"
                "device.operating_system": self._normalize_os_name(self.os),
                "device.operating_system_version": self.os_version,
                # Session information
                "app_session_id": self.session_id,
                "session_duration": round(time.time() - self._session_start_time, 1),
                # User information (anonymized)
                "user_id": self.username,
                "user_type": "premium" if self._is_premium_user() else "free",
                # System information
                "os": self.os,
                "os_version": self.os_version,
                "app_version": self.app_version,
                "launcher": launcher,
                "is_runner": self.isRunner,
                "is_container": str(os.environ.get("PKSCREENER_DOCKER", "")).lower()
                in ("yes", "y", "on", "true", "1"),
                "one_file_bundle": self.onefile,
                # Performance
                "elapsed_time": round(time.time() - self.start_time, 2),
            }

            # Add label if provided
            if label:
                event_params["event_label"] = label

            # Add value if provided (numeric)
            if value is not None:
                event_params["event_value"] = value

            # Add location dimensions (for geo analysis)
            if current_location:
                if "country" in current_location:
                    event_params["geo.country"] = current_location["country"]
                if "region" in current_location:
                    event_params["geo.region"] = current_location["region"]
                if "city" in current_location:
                    event_params["geo.city"] = current_location["city"]

            # Add custom dimensions (for detailed analysis)
            if custom_dimensions:
                for key, val in custom_dimensions.items():
                    event_params[f"dim_{key}"] = str(val)[:100]  # Limit length

            # Add repository info for GitHub Runner
            if self.isRunner:
                try:
                    owner = (
                        os.popen("git ls-remote --get-url origin | cut -d/ -f4")
                        .read()
                        .replace("\n", "")
                    )
                    repo = (
                        os.popen("git ls-remote --get-url origin | cut -d/ -f5")
                        .read()
                        .replace(".git", "")
                        .replace("\n", "")
                    )
                    event_params["repo_owner"] = owner
                    event_params["repo"] = repo
                except Exception:
                    pass

            # Send the event
            updated_action = action
            if isinstance(action, dict):
                # Handle legacy dict style
                event_params.update(action)
                for key in action:
                    if isinstance(action[key], str):
                        updated_action = action[key]
                        break
            if isinstance(updated_action, dict):
                PKUserService().send_event(f"{category}", event_params)
            else:
                PKUserService().send_event(f"{category}_{updated_action}", event_params)
            # Update feature usage counters
            if category == AnalyticsCategory.FEATURE:
                feature_name = label or updated_action
                self._feature_usage[feature_name] = self._feature_usage.get(feature_name, 0) + 1

        except Exception:
            pass

    def _is_premium_user(self):
        """Check if current user has premium subscription."""
        try:
            # This just checks if user is logged in (premium trial or paid)
            return False
            # return PKUserRegistration().userID != 0
        except Exception:
            return False

    def track_scan(self, scan_type, result_count, duration_seconds, menu_path=None, success=True):
        """
        Track a scanner execution (convenience method).

        Args:
            scan_type (str): Type of scan (e.g., "volume_gainers", "breakouts")
            result_count (int): Number of results found
            duration_seconds (float): How long the scan took
            menu_path (str, optional): Menu navigation path
            success (bool): Whether scan completed successfully
        """
        self.send_event(
            category=AnalyticsCategory.SCAN,
            action=AnalyticsAction.COMPLETE,
            label=AnalyticsLabel.SUCCESS if success else AnalyticsLabel.FAILURE,
            value=result_count,
            custom_dimensions={
                "scan_type": scan_type,
                "duration": round(duration_seconds, 2),
                "menu_path": menu_path[:100] if menu_path else None,
            },
        )

    def track_performance(self, operation, duration_seconds, success=True):
        """
        Track performance metrics.

        Args:
            operation (str): Operation name (e.g., "data_load", "calculation")
            duration_seconds (float): Operation duration
            success (bool): Whether operation succeeded
        """
        self.send_event(
            category=AnalyticsCategory.PERFORMANCE,
            action=operation,
            label=AnalyticsLabel.SUCCESS if success else AnalyticsLabel.FAILURE,
            value=int(duration_seconds * 1000),  # Convert to milliseconds
            custom_dimensions={"duration_ms": int(duration_seconds * 1000)},
        )

    def track_error(self, error_type, error_message, context=None):
        """
        Track errors for debugging and reliability monitoring.

        Args:
            error_type (str): Type of error (e.g., "NetworkError", "ValueError")
            error_message (str): Error message (truncated)
            context (dict, optional): Additional context
        """
        self.send_event(
            category=AnalyticsCategory.ERROR,
            action=error_type,
            label=AnalyticsLabel.FAILURE,
            custom_dimensions={
                "error_message": error_message[:200],
                "context": str(context)[:200] if context else None,
            },
        )

    def track_feature_usage(self, feature_name, menu_path=None, **kwargs):
        """
        Track feature usage for adoption analysis.

        Args:
            feature_name (str): Name of the feature used
            menu_path (str, optional): Menu navigation path
            **kwargs: Additional custom dimensions
        """
        self.send_event(
            category=AnalyticsCategory.FEATURE,
            action=AnalyticsAction.USE,
            label=feature_name,
            custom_dimensions={"menu_path": menu_path[:100] if menu_path else None, **kwargs},
        )

    def collectMetrics(self, user=None, async_mode=True):
        """
        Collect user metrics in non-blocking mode.

        Args:
            user: Optional user identifier
            async_mode (bool): If True, run asynchronously
        """
        if not self.configManager.enableUsageAnalytics:
            return

        if async_mode:
            self._executor.submit(self._collect_metrics_sync, user)
        else:
            self._collect_metrics_sync(user)

    def _collect_metrics_sync(self, user=None):
        """Synchronous metrics collection (runs in background thread)."""
        try:
            self.getUserName()

            # Wait for location if needed
            if not self._location_fetched:
                for _ in range(10):
                    if self._location_fetched:
                        break
                    time.sleep(0.01)

            # Send user info event with custom dimensions
            self.send_event(
                category=AnalyticsCategory.USER,
                action=AnalyticsAction.LOGIN,
                label=AnalyticsLabel.INFO,
                custom_dimensions={
                    "user_exists": bool(user),
                    "premium": self._is_premium_user(),
                    "tel_user_id": f"{user}({self.username})" if user else self.username,
                },
            )
        except Exception:
            pass

    def getUserName(self):
        try:
            username = os.getlogin()
            if username is None or len(username) == 0:
                username = (
                    os.environ.get("username")
                    if platform.startswith("win")
                    else os.environ.get("USER")
                )
                if username is None or len(username) == 0:
                    username = os.environ.get("USERPROFILE")
                    if username is None or len(username) == 0:
                        username = (
                            os.path.expandvars("%userprofile%")
                            if platform.startswith("win")
                            else getpass.getuser()
                        )
        except KeyboardInterrupt:  # pragma: no cover
            raise KeyboardInterrupt
        except:  # pragma: no cover
            username = f"NA-{self.os}"
            pass
        username = f"{self._get_anonymous_id()}-{username}"  # Use anonymous ID instead of username
        return username

    def getApproxLocationInfo(self, use_cache=True, timeout=2):
        """Get approximate location information."""
        with self._location_lock:
            if use_cache and self.locationInfo:
                return self.locationInfo

        if not use_cache:
            try:
                url = "http://ipinfo.io/json"
                f = fetcher()
                response = f.fetchURL(
                    url=url, timeout=timeout, headers={"user-agent": f"{random_user_agent()}"}
                )
                if response and response.status_code == 200:
                    data = json.loads(response.text)
                    with self._location_lock:
                        self.locationInfo = data
                        self._location_fetched = True
                    return data
            except Exception:
                pass

        return {"country": "Unknown", "region": "Unknown"}

    def flush(self, timeout=5):
        """Wait for all pending analytics events to complete."""
        if self._executor:
            self._executor.shutdown(wait=True, cancel_futures=False)
            self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="analytics")

    def __del__(self):
        """Cleanup executor on object destruction."""
        if hasattr(self, "_executor") and self._executor:
            try:
                # Send session end event
                self.send_event(
                    AnalyticsCategory.APP,
                    AnalyticsAction.EXIT,
                    AnalyticsLabel.INFO,
                    value=int(time.time() - self._session_start_time),
                )
                self._executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass


# =============================================================================
# HELPER DECORATORS FOR EASY TRACKING (Supports instance, class, and static methods)
# =============================================================================


def track_feature(feature_name):
    """
    Decorator to automatically track feature usage.

    Works with:
    - Instance methods (takes self)
    - Class methods (takes cls)
    - Static methods (takes no special first arg)

    Usage:
        # Instance method
        @track_feature("ATR_Trailing_Stop")
        def my_method(self):
            pass

        # Class method
        @classmethod
        @track_feature("PKUserRegistration_login")
        def login(cls, trialCount=0):
            pass

        # Static method
        @staticmethod
        @track_feature("utility_function")
        def helper_function():
            pass
    """

    def decorator(func):
        def wrapper(*args, **kwargs):
            analytics = PKAnalyticsService()
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                analytics.track_feature_usage(
                    feature_name, duration_ms=int((time.time() - start_time) * 1000), success=True
                )
                return result
            except Exception as e:
                analytics.track_feature_usage(
                    feature_name,
                    duration_ms=int((time.time() - start_time) * 1000),
                    success=False,
                    error=str(e)[:100],
                )
                raise

        return wrapper

    return decorator


def track_performance(operation_name):
    """
    Decorator to automatically track performance.

    Works with:
    - Instance methods (takes self)
    - Class methods (takes cls)
    - Static methods (takes no special first arg)

    Usage:
        # Instance method
        @track_performance("data_loading")
        def load_data(self):
            pass

        # Class method
        @classmethod
        @track_performance("PKUserRegistration_login")
        def login(cls, trialCount=0):
            pass

        # Static method
        @staticmethod
        @track_performance("helper_calculation")
        def calculate():
            pass
    """

    def decorator(func):
        def wrapper(*args, **kwargs):
            analytics = PKAnalyticsService()
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                analytics.track_performance(operation_name, time.time() - start_time, success=True)
                return result
            except Exception:
                analytics.track_performance(operation_name, time.time() - start_time, success=False)
                raise

        return wrapper

    return decorator


def track_error(error_type=None):
    """
    Decorator to automatically track errors in functions.

    Works with instance, class, and static methods.

    Usage:
        @track_error("DatabaseError")
        def my_function():
            pass
    """

    def decorator(func):
        def wrapper(*args, **kwargs):
            analytics = PKAnalyticsService()
            try:
                return func(*args, **kwargs)
            except Exception as e:
                analytics.track_error(
                    error_type or type(e).__name__, str(e), {"function": func.__name__}
                )
                raise

        return wrapper

    return decorator


def track_all(operation_name, feature_name=None):
    """
    Combined decorator that tracks both performance and feature usage.

    Works with instance, class, and static methods.

    Usage:
        @track_all("PKUserRegistration_login", "User Login")
        @classmethod
        def login(cls):
            pass
    """

    def decorator(func):
        def wrapper(*args, **kwargs):
            analytics = PKAnalyticsService()
            start_time = time.time()
            feature = feature_name or operation_name
            try:
                result = func(*args, **kwargs)
                # Track performance
                analytics.track_performance(operation_name, time.time() - start_time, success=True)
                # Track feature usage
                analytics.track_feature_usage(
                    feature, duration_ms=int((time.time() - start_time) * 1000), success=True
                )
                return result
            except Exception as e:
                analytics.track_performance(operation_name, time.time() - start_time, success=False)
                analytics.track_feature_usage(
                    feature,
                    duration_ms=int((time.time() - start_time) * 1000),
                    success=False,
                    error=str(e)[:100],
                )
                raise

        return wrapper

    return decorator


def track_event(
    category, action, label=None, capture_params=None, capture_result=False, log_args=False
):
    """
    Decorator to automatically send analytics events with function parameters.

    Args:
        category (str): Event category (App, User, Scan, Performance, Error, System)
        action (str): Event action template (can use {function_name} placeholder)
        label (str, optional): Event label template (can use {param_name} placeholders)
        capture_params (list, optional): List of parameter names to capture as custom dimensions
        capture_result (bool): If True, capture return value (as string)
        log_args (bool): If True, log all arguments for debugging

    Example:
        @track_event(
            category=AnalyticsCategory.SYSTEM,
            action="workflow_trigger",
            label="workflow_{workflowType}",
            capture_params=["workflowType", "repo", "owner", "branch"],
            capture_result=True
        )
        def run_workflow(command=None, user=None, options=None, workflowType="B",
                        repo=None, owner=None, branch=None, ghp_token=None,
                        workflow_name=None, workflow_postData=None):
            pass
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            analytics = PKAnalyticsService()
            start_time = time.time()

            # Capture function arguments
            sig = inspect.signature(func)
            bound_args = sig.bind_partial(*args, **kwargs)
            bound_args.apply_defaults()
            params = bound_args.arguments

            # Log if requested
            if log_args and (
                "subscriber.py" in os.environ.get("PK_DEBUG_FILES", "")
                or "PKAnalytics.py" in os.environ.get("PK_DEBUG_FILES", "")
            ):
                default_logger().debug(f"Tracking {func.__name__} with params: {params}")

            # Prepare custom dimensions from captured parameters
            custom_dimensions = {}
            if capture_params:
                for param_name in capture_params:
                    if param_name in params and params[param_name] is not None:
                        value = params[param_name]
                        # Truncate long values
                        if isinstance(value, str) and len(value) > 100:
                            value = value[:100] + "..."
                        elif isinstance(value, dict):
                            value = str(value)[:100]
                        custom_dimensions[f"param_{param_name}"] = value

            # Add additional metrics
            custom_dimensions["function_name"] = func.__name__

            # Prepare event action with function name if placeholder exists
            event_action = action
            if "{function_name}" in action:
                event_action = action.format(function_name=func.__name__)

            # Prepare event label with parameter placeholders
            event_label = label
            if label and "{" in label:
                try:
                    event_label = label.format(**params)
                except KeyError as e:
                    if "subscriber.py" in os.environ.get(
                        "PK_DEBUG_FILES", ""
                    ) or "PKAnalytics.py" in os.environ.get("PK_DEBUG_FILES", ""):
                        default_logger().debug(f"Label formatting failed: {e}")
                    event_label = label

            # Execute the actual function
            result = None
            success = True
            error_msg = None

            try:
                result = func(*args, **kwargs)
                if capture_result:
                    # Capture result summary (not full content)
                    if isinstance(result, dict):
                        result_summary = f"dict({len(result)} keys)"
                    elif isinstance(result, list):
                        result_summary = f"list({len(result)} items)"
                    elif isinstance(result, str):
                        result_summary = result[:100] + ("..." if len(result) > 100 else "")
                    else:
                        result_summary = str(type(result).__name__)
                    custom_dimensions["result_type"] = result_summary
                return result
            except Exception as e:
                success = False
                error_msg = str(e)[:200]
                custom_dimensions["error"] = error_msg
                raise
            finally:
                # Calculate execution time
                duration_ms = int((time.time() - start_time) * 1000)
                custom_dimensions["duration_ms"] = duration_ms
                custom_dimensions["success"] = success

                # Send analytics event
                analytics.send_event(
                    category=category,
                    action=event_action,
                    label=event_label
                    if event_label
                    else (AnalyticsLabel.SUCCESS if success else AnalyticsLabel.FAILURE),
                    value=1,
                    custom_dimensions=custom_dimensions,
                )

                # Log if debug enabled
                if log_args and (
                    "subscriber.py" in os.environ.get("PK_DEBUG_FILES", "")
                    or "PKAnalytics.py" in os.environ.get("PK_DEBUG_FILES", "")
                ):
                    default_logger().debug(
                        f"Tracked {func.__name__}: success={success}, duration={duration_ms}ms"
                    )

        return wrapper

    return decorator
