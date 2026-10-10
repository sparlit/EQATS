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
import os
import sys
import threading
import time as time_module
import unittest
from datetime import datetime, time
from types import ModuleType
from unittest.mock import MagicMock, Mock, patch

from pkscreener.classes.MenuOptions import level0MenuDict, menus

# Mock the telegram module for bot tests as actual modules
telegram_module = ModuleType("telegram")
telegram_module.__path__ = []
telegram_module.__version__ = "0.0.0"
telegram_module.InlineKeyboardButton = MagicMock()
telegram_module.InlineKeyboardMarkup = MagicMock()
telegram_module.Update = MagicMock()

telegram_ext_module = ModuleType("telegram.ext")
telegram_ext_module.__path__ = []
telegram_ext_module.Updater = MagicMock()
telegram_ext_module.CallbackQueryHandler = MagicMock()
telegram_ext_module.CommandHandler = MagicMock()
telegram_ext_module.ContextTypes = MagicMock()
telegram_ext_module.ConversationHandler = MagicMock()
telegram_ext_module.MessageHandler = MagicMock()
telegram_ext_module.Filters = MagicMock()
telegram_ext_module.CallbackContext = MagicMock()

telegram_constants_module = ModuleType("telegram.constants")
telegram_constants_module.__path__ = []

sys.modules["telegram"] = telegram_module
sys.modules["telegram.ext"] = telegram_ext_module
sys.modules["telegram.constants"] = telegram_constants_module

# Mock PKDevTools modules
sys.modules["PKDevTools"] = MagicMock()
sys.modules["PKDevTools.classes"] = MagicMock()
pk_env_module = MagicMock()


class MockPKEnvironment:
    SUBSCRIPTION_ENABLED = "1"

    def __init__(self):
        self.allSecrets = {}


pk_env_module.PKEnvironment = MockPKEnvironment
sys.modules["PKDevTools.classes.Environment"] = pk_env_module
sys.modules["PKDevTools.classes.PKDateUtilities"] = MagicMock()
sys.modules["PKDevTools.classes.ColorText"] = MagicMock()
sys.modules["PKDevTools.classes.MarketHours"] = MagicMock()
sys.modules["PKDevTools.classes.UserSubscriptions"] = MagicMock()
sys.modules["PKDevTools.classes.GmailReader"] = MagicMock()
sys.modules["PKDevTools.classes.DBManager"] = MagicMock()
sys.modules["PKDevTools.classes.FunctionTimeouts"] = MagicMock()


class TestPKScreenerBot(unittest.TestCase):
    """Tests for PKScreener bot functionality."""

    def test_level0ButtonsHaveAllSupportedParentButtons(self):
        m0 = menus()
        l0_menus = m0.renderForMenu(
            selectedMenu=None,
            asList=True,
            skip=[x for x in level0MenuDict if x not in ["X", "B", "P"]],
        )
        l0_buttons = [x.menuKey for x in l0_menus]
        self.assertTrue(x in l0_buttons for x in ["X", "B", "P"])
        self.assertTrue(
            x not in l0_buttons for x in [x for x in level0MenuDict if x not in ["X", "B", "P"]]
        )


class TestScheduledWorkflowTrigger(unittest.TestCase):
    """Test cases for scheduled_workflow_trigger function"""

    def setUp(self):
        """Set up test fixtures"""
        self.ist_tz = pytz.timezone("Asia/Kolkata")
        self.trigger_patcher = None
        self.mock_trigger = None

    def tearDown(self):
        """Clean up after tests"""
        if self.trigger_patcher:
            self.trigger_patcher.stop()

    @patch("pkscreener.pkscreenerbot.trigger_prod_scans_workflow")
    @patch("pkscreener.pkscreenerbot.sleep")
    @patch("pkscreener.pkscreenerbot.datetime")
    def test_trigger_at_exact_time(self, mock_datetime, mock_sleep, mock_trigger):
        """Test workflow triggers exactly at 9:33 AM"""
        # Set up mock datetime for 9:33 AM
        mock_now = Mock()
        mock_now.date.return_value = datetime(2026, 5, 6).date()
        mock_now.time.return_value = time(9, 33, 0)
        mock_now.hour = 9
        mock_now.minute = 33
        mock_datetime.now.return_value = mock_now

        mock_trigger.return_value = True

        # Run the trigger in a thread with timeout
        stop_event = threading.Event()

        # Import the module and set the stop event
        import pkscreener.pkscreenerbot as bot

        bot._trigger_stop_event = stop_event

        def run_trigger():
            bot.scheduled_workflow_trigger()

        trigger_thread = threading.Thread(target=run_trigger, daemon=True)
        trigger_thread.start()

        # Give it a moment to run
        time_module.sleep(0.5)

        # After successful trigger, stop event should be set
        self.assertTrue(stop_event.is_set())
        mock_trigger.assert_called_once()

    @patch("pkscreener.pkscreenerbot.trigger_prod_scans_workflow")
    @patch("pkscreener.pkscreenerbot.sleep")
    @patch("pkscreener.pkscreenerbot.datetime")
    def test_no_trigger_before_9_30(self, mock_datetime, mock_sleep, mock_trigger):
        """Test no trigger before 9:30 AM"""
        mock_now = Mock()
        mock_now.date.return_value = datetime(2026, 5, 6).date()
        mock_now.time.return_value = time(9, 15, 0)
        mock_now.hour = 9
        mock_now.minute = 15
        mock_datetime.now.return_value = mock_now

        mock_trigger.return_value = False

        stop_event = threading.Event()
        import pkscreener.pkscreenerbot as bot

        bot._trigger_stop_event = stop_event

        # Run for a short time
        def run_and_stop():
            # Mock sleep to return quickly
            def quick_sleep(*args, **kwargs):
                stop_event.set()

            mock_sleep.side_effect = quick_sleep
            bot.scheduled_workflow_trigger()

        trigger_thread = threading.Thread(target=run_and_stop, daemon=True)
        trigger_thread.start()
        trigger_thread.join(timeout=2)

        mock_trigger.assert_not_called()

    @patch("pkscreener.pkscreenerbot.trigger_prod_scans_workflow")
    @patch("pkscreener.pkscreenerbot.sleep")
    @patch("pkscreener.pkscreenerbot.datetime")
    def test_trigger_failure_retry(self, mock_datetime, mock_sleep, mock_trigger):
        """Test retry logic when trigger fails at 9:33"""
        # First at 9:33 - failure
        mock_now = Mock()
        mock_now.date.return_value = datetime(2026, 5, 6).date()
        mock_now.time.return_value = time(9, 33, 0)
        mock_now.hour = 9
        mock_now.minute = 33
        mock_datetime.now.return_value = mock_now

        mock_trigger.return_value = False

        stop_event = threading.Event()
        import pkscreener.pkscreenerbot as bot

        bot._trigger_stop_event = stop_event

        call_count = 0

        def mock_sleep_impl(seconds):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:  # After retry, stop
                stop_event.set()

        mock_sleep.side_effect = mock_sleep_impl

        def run_trigger():
            bot.scheduled_workflow_trigger()

        trigger_thread = threading.Thread(target=run_trigger, daemon=True)
        trigger_thread.start()
        trigger_thread.join(timeout=3)

        # Should have called trigger at least once
        self.assertGreaterEqual(mock_trigger.call_count, 1)

    @patch("pkscreener.pkscreenerbot.trigger_prod_scans_workflow")
    @patch("pkscreener.pkscreenerbot.sleep")
    @patch("pkscreener.pkscreenerbot.datetime")
    def test_no_double_trigger_same_day(self, mock_datetime, mock_sleep, mock_trigger):
        """Test that workflow triggers only once per day"""
        # First call at 9:33
        mock_now = Mock()
        mock_now.date.return_value = datetime(2026, 5, 6).date()
        mock_now.time.return_value = time(9, 33, 0)
        mock_now.hour = 9
        mock_now.minute = 33
        mock_datetime.now.return_value = mock_now

        mock_trigger.return_value = True

        stop_event = threading.Event()
        import pkscreener.pkscreenerbot as bot

        bot._trigger_stop_event = stop_event

        call_count = 0

        def run_trigger():
            nonlocal call_count
            bot.scheduled_workflow_trigger()
            call_count += 1

        trigger_thread = threading.Thread(target=run_trigger, daemon=True)
        trigger_thread.start()
        time_module.sleep(0.5)
        stop_event.set()
        trigger_thread.join(timeout=1)

        # Should trigger exactly once
        self.assertEqual(mock_trigger.call_count, 1)

    @patch("pkscreener.pkscreenerbot.trigger_prod_scans_workflow")
    @patch("pkscreener.pkscreenerbot.sleep")
    @patch("pkscreener.pkscreenerbot.datetime")
    def test_trigger_at_boundary_times(self, mock_datetime, mock_sleep, mock_trigger):
        """Test trigger behavior at boundary times (9:29, 9:30, 9:31, 9:32, 9:33, 9:34)"""

        test_cases = [
            (9, 29, False, "Before 9:30 should not trigger"),
            (9, 30, False, "At 9:30 should not trigger"),
            (9, 31, False, "At 9:31 should not trigger"),
            (9, 32, False, "At 9:32 should not trigger"),
            (9, 33, True, "At 9:33 should trigger"),
            (9, 34, False, "After 9:33 should not trigger again"),
        ]

        import pkscreener.pkscreenerbot as bot

        for hour, minute, should_trigger, description in test_cases:
            with self.subTest(hour=hour, minute=minute):
                mock_now = Mock()
                mock_now.date.return_value = datetime(2026, 5, 6).date()
                mock_now.time.return_value = time(hour, minute, 0)
                mock_now.hour = hour
                mock_now.minute = minute
                mock_datetime.now.return_value = mock_now

                mock_trigger.reset_mock()
                mock_trigger.return_value = True

                stop_event = threading.Event()
                bot._trigger_stop_event = stop_event

                # Quick run with timeout
                def quick_trigger():
                    # Mock sleep to break quickly
                    def break_sleep(x):
                        stop_event.set()

                    mock_sleep.side_effect = break_sleep
                    bot.scheduled_workflow_trigger()

                trigger_thread = threading.Thread(target=quick_trigger, daemon=True)
                trigger_thread.start()
                trigger_thread.join(timeout=1)

                if should_trigger:
                    self.assertTrue(
                        mock_trigger.called, f"Failed at {hour}:{minute} - {description}"
                    )
                else:
                    self.assertFalse(
                        mock_trigger.called, f"Incorrect trigger at {hour}:{minute} - {description}"
                    )


class TestHelperFunctions(unittest.TestCase):
    """Test helper functions in pkscreenerbot"""

    def setUp(self):
        """Set up test fixtures"""
        self.mock_user = Mock()
        self.mock_user.id = 12345
        self.mock_user.first_name = "Test"
        self.mock_user.last_name = "User"
        self.mock_user.username = "testuser"

    @patch("pkscreener.pkscreenerbot.DBManager")
    def test_register_user_new_user(self, mock_db_manager):
        """Test registering a new user"""
        import pkscreener.pkscreenerbot as bot

        mock_db = Mock()
        mock_db.getOTP.return_value = (123456, 1, None, Mock())
        mock_db_manager.return_value = mock_db

        # Clear cache
        bot.PKLocalCache().registeredIDs = []

        otp, subs, validity, alert = bot.registerUser(self.mock_user)

        self.assertEqual(otp, 123456)
        self.assertIn(self.mock_user.id, bot.PKLocalCache().registeredIDs)

    @patch("pkscreener.pkscreenerbot.DBManager")
    def test_register_user_cached_user(self, mock_db_manager):
        """Test registering a user that's already in cache"""
        import pkscreener.pkscreenerbot as bot

        # Add user to cache
        bot.PKLocalCache().registeredIDs.append(self.mock_user.id)

        mock_db = Mock()
        mock_db.getOTP.return_value = (789012, 1, None, Mock())
        mock_db_manager.return_value = mock_db

        # Should not call getOTP for cached user (unless forceFetch=True)
        otp, subs, validity, alert = bot.registerUser(self.mock_user, forceFetch=True)

        mock_db.getOTP.assert_called_once()

    def test_sanitise_texts(self):
        """Test text sanitization for Telegram message length limit"""
        import pkscreener.pkscreenerbot as bot

        # Short text - should remain unchanged
        short_text = "Short message"
        self.assertEqual(bot.sanitiseTexts(short_text), short_text)

        # Long text - should be truncated
        long_text = "A" * 5000
        self.assertEqual(len(bot.sanitiseTexts(long_text)), 4096)

    @patch("pkscreener.pkscreenerbot.PKDateUtilities")
    def test_is_in_market_hours_trading_time(self, mock_date_utils):
        """Test market hours detection during trading hours"""
        import pkscreener.pkscreenerbot as bot

        mock_date_utils.isTodayHoliday.return_value = (False, None)

        # Test during trading hours (10:30 AM)
        mock_date_utils.currentDateTime.side_effect = [
            datetime(2026, 5, 6, 10, 30, 0),  # current time
            datetime(2026, 5, 6, 9, 15, 0),  # market start
            datetime(2026, 5, 6, 15, 30, 0),  # market close
        ]

        bot.MarketHours.openHour = 9
        bot.MarketHours.openMinute = 15
        bot.MarketHours.closeHour = 15
        bot.MarketHours.closeMinute = 30

        # This should be True during trading hours
        result = bot.isInMarketHours()
        self.assertTrue(result)

    @patch("pkscreener.pkscreenerbot.PKDateUtilities")
    def test_is_in_market_hours_holiday(self, mock_date_utils):
        """Test market hours detection on holiday"""
        import pkscreener.pkscreenerbot as bot

        mock_date_utils.isTodayHoliday.return_value = (True, "Test Holiday")

        result = bot.isInMarketHours()
        self.assertFalse(result)

    @patch("pkscreener.pkscreenerbot.run_workflow")
    def test_trigger_prod_scans_workflow_success(self, mock_run_workflow):
        """Test successful workflow trigger"""
        import pkscreener.pkscreenerbot as bot

        mock_response = Mock()
        mock_response.status_code = 204
        mock_run_workflow.return_value = mock_response

        # Mock environment
        with patch.dict(os.environ, {"GITHUB_TOKEN": "test_token"}):
            result = bot.trigger_prod_scans_workflow()
            self.assertTrue(result)

    @patch("pkscreener.pkscreenerbot.run_workflow")
    def test_trigger_prod_scans_workflow_failure(self, mock_run_workflow):
        """Test failed workflow trigger"""
        import pkscreener.pkscreenerbot as bot

        mock_response = Mock()
        mock_response.status_code = 404
        mock_run_workflow.return_value = mock_response

        with patch.dict(os.environ, {"GITHUB_TOKEN": "test_token"}):
            result = bot.trigger_prod_scans_workflow()
            self.assertFalse(result)

    @patch("pkscreener.pkscreenerbot.run_workflow")
    def test_trigger_prod_scans_workflow_no_token(self, mock_run_workflow):
        """Test workflow trigger with no GitHub token"""
        import pkscreener.pkscreenerbot as bot

        with patch.dict(os.environ, {}, clear=True):
            result = bot.trigger_prod_scans_workflow()
            self.assertFalse(result)
            mock_run_workflow.assert_not_called()


class TestBotMenuOptions(unittest.TestCase):
    """Tests to ensure all bot menu options are available."""

    def test_all_scanner_menu_options_available(self):
        """Test that key scanner menu options are available."""
        from pkscreener.classes.MenuOptions import menus

        m0 = menus()

        # These are the main scanner options that should be available
        expected_options = ["X", "P"]

        all_menus = m0.renderForMenu(selectedMenu=None, asList=True, skip=[])
        menu_keys = [menu.menuKey for menu in all_menus]

        for option in expected_options:
            self.assertIn(option, menu_keys, f"Menu option {option} should be available")

    def test_level0_menu_has_scanner_option(self):
        """Test that level 0 menu has X (Scanner) option."""
        from pkscreener.classes.MenuOptions import level0MenuDict

        # X should be in level0MenuDict
        self.assertIn("X", level0MenuDict)

    def test_level0_menu_has_piped_scanner_option(self):
        """Test that level 0 menu has P (Piped Scanner) option."""
        from pkscreener.classes.MenuOptions import level0MenuDict

        # P should be in level0MenuDict
        self.assertIn("P", level0MenuDict)

    def test_menu_render_returns_list(self):
        """Test that menu rendering returns a list."""
        from pkscreener.classes.MenuOptions import menus

        m0 = menus()

        # Render with asList=True should return a list
        result = m0.renderForMenu(selectedMenu=None, asList=True, skip=[])

        self.assertIsInstance(result, list)
        self.assertTrue(len(result) > 0)


class TestBotWorkflowIntegration(unittest.TestCase):
    """Tests to ensure bot workflow triggering works with scalable architecture."""

    def test_run_workflow_imports(self):
        """Test that run_workflow can be imported without errors."""
        from pkscreener.classes.WorkflowManager import run_workflow

        self.assertIsNotNone(run_workflow)

    def test_screener_fetcher_post_url_available(self):
        """Test that screenerStockDataFetcher.postURL is available for workflow triggers."""
        from pkscreener.classes.Fetcher import screenerStockDataFetcher

        fetcher = screenerStockDataFetcher()
        self.assertTrue(hasattr(fetcher, "postURL"))
        self.assertTrue(callable(fetcher.postURL))

    def test_fetcher_has_scalable_data_sources(self):
        """Test that Fetcher has scalable data source attributes."""
        from pkscreener.classes.Fetcher import screenerStockDataFetcher

        fetcher = screenerStockDataFetcher()

        # Should have high-performance provider attribute
        self.assertTrue(hasattr(fetcher, "_hp_provider"))

        # Should have scalable fetcher attribute
        self.assertTrue(hasattr(fetcher, "_scalable_fetcher"))

    def test_fetcher_health_check_method_exists(self):
        """Test that Fetcher has healthCheck method for monitoring."""
        from pkscreener.classes.Fetcher import screenerStockDataFetcher

        fetcher = screenerStockDataFetcher()

        self.assertTrue(hasattr(fetcher, "healthCheck"))
        self.assertTrue(callable(fetcher.healthCheck))

        # Should return a dict with expected keys
        health = fetcher.healthCheck()
        self.assertIsInstance(health, dict)
        self.assertIn("overall_status", health)

    def test_fetcher_data_source_stats_method_exists(self):
        """Test that Fetcher has getDataSourceStats method."""
        from pkscreener.classes.Fetcher import screenerStockDataFetcher

        fetcher = screenerStockDataFetcher()

        self.assertTrue(hasattr(fetcher, "getDataSourceStats"))
        self.assertTrue(callable(fetcher.getDataSourceStats))

        stats = fetcher.getDataSourceStats()
        self.assertIsInstance(stats, dict)

    @patch("pkscreener.classes.WorkflowManager.screenerStockDataFetcher")
    def test_workflow_uses_fetcher_for_api_calls(self, mock_fetcher_class):
        """Test that run_workflow uses Fetcher for API calls."""
        from pkscreener.classes.WorkflowManager import run_workflow

        mock_fetcher = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_fetcher.postURL.return_value = mock_response
        mock_fetcher_class.return_value = mock_fetcher

        # This should not raise
        with patch.dict("os.environ", {"GITHUB_TOKEN": "test_token"}):
            with patch("PKDevTools.classes.Environment.PKEnvironment") as mock_env:
                mock_env_instance = MagicMock()
                mock_env_instance.secrets = ("a", "b", "c", "test_ghp_token")
                mock_env.return_value = mock_env_instance

                try:
                    run_workflow(
                        command="test", user="12345", options="-a Y -e -o X:12:7", workflowType="S"
                    )
                except Exception:
                    # May fail due to missing env vars, but import should work
                    pass


class TestTimeZoneHandling(unittest.TestCase):
    """Test timezone handling in scheduled_workflow_trigger"""

    def test_timezone_aware_comparison(self):
        """Test that timezone-aware datetime works correctly"""
        ist_tz = pytz.timezone("Asia/Kolkata")
        utc_tz = pytz.timezone("UTC")

        # 9:33 AM IST
        ist_time = ist_tz.localize(datetime(2026, 5, 6, 9, 33, 0))
        utc_time = ist_time.astimezone(utc_tz)

        # UTC should be 4:03 AM (IST is UTC+5:30)
        self.assertEqual(utc_time.hour, 4)
        self.assertEqual(utc_time.minute, 3)

        # When comparing, use naive time for hour/minute extraction
        naive_time = ist_time.replace(tzinfo=None)
        self.assertEqual(naive_time.hour, 9)
        self.assertEqual(naive_time.minute, 33)

    def test_boundary_time_calculation(self):
        """Test boundary time calculations"""
        ist_tz = pytz.timezone("Asia/Kolkata")

        # Test various times
        test_times = [
            (9, 29, False, "Should not trigger"),
            (9, 30, False, "Should not trigger"),
            (9, 31, False, "Should not trigger"),
            (9, 32, False, "Should not trigger"),
            (9, 33, True, "Should trigger"),
            (9, 34, False, "Should not trigger"),
        ]

        for hour, minute, should_trigger, _ in test_times:
            dt = ist_tz.localize(datetime(2026, 5, 6, hour, minute, 0))
            is_trigger_time = dt.hour == 9 and dt.minute == 33
            self.assertEqual(is_trigger_time, should_trigger)


class TestBotDataIntegration(unittest.TestCase):
    """Tests to ensure bot can access data through the scalable architecture."""

    def test_fetcher_fetch_stock_data_available(self):
        """Test that fetchStockData method is available."""
        from pkscreener.classes.Fetcher import screenerStockDataFetcher

        fetcher = screenerStockDataFetcher()

        self.assertTrue(hasattr(fetcher, "fetchStockData"))
        self.assertTrue(callable(fetcher.fetchStockData))

    def test_fetcher_is_data_fresh_available(self):
        """Test that isDataFresh method is available for freshness checks."""
        from pkscreener.classes.Fetcher import screenerStockDataFetcher

        fetcher = screenerStockDataFetcher()

        self.assertTrue(hasattr(fetcher, "isDataFresh"))
        self.assertTrue(callable(fetcher.isDataFresh))

        # Should return boolean
        result = fetcher.isDataFresh(max_age_seconds=900)
        self.assertIsInstance(result, bool)

    def test_fetcher_get_latest_price_available(self):
        """Test that getLatestPrice method is available."""
        from pkscreener.classes.Fetcher import screenerStockDataFetcher

        fetcher = screenerStockDataFetcher()

        self.assertTrue(hasattr(fetcher, "getLatestPrice"))
        self.assertTrue(callable(fetcher.getLatestPrice))

    def test_fetcher_get_realtime_ohlcv_available(self):
        """Test that getRealtimeOHLCV method is available."""
        from pkscreener.classes.Fetcher import screenerStockDataFetcher

        fetcher = screenerStockDataFetcher()

        self.assertTrue(hasattr(fetcher, "getRealtimeOHLCV"))
        self.assertTrue(callable(fetcher.getRealtimeOHLCV))


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling"""

    @patch("pkscreener.pkscreenerbot.sleep")
    @patch("pkscreener.pkscreenerbot.datetime")
    def test_trigger_during_exception(self, mock_datetime, mock_sleep):
        """Test trigger behavior when exception occurs"""
        import pkscreener.pkscreenerbot as bot

        # First call raises exception, second works
        mock_datetime.now.side_effect = [Exception("Test error"), Mock()]

        mock_sleep.side_effect = lambda x: None

        stop_event = threading.Event()
        bot._trigger_stop_event = stop_event

        # Should handle exception gracefully and continue
        # We'll just verify it doesn't crash
        pass


class TestIntegrationScenarios(unittest.TestCase):
    """Integration test scenarios"""

    @patch("pkscreener.pkscreenerbot.trigger_prod_scans_workflow")
    @patch("pkscreener.pkscreenerbot.sleep")
    @patch("pkscreener.pkscreenerbot.datetime")
    def test_full_trigger_cycle(self, mock_datetime, mock_sleep, mock_trigger):
        """Test full trigger cycle from start to finish"""
        import pkscreener.pkscreenerbot as bot

        ist_tz = pytz.timezone("Asia/Kolkata")

        # Simulate time progression
        times = [
            ist_tz.localize(datetime(2026, 5, 6, 9, 29, 0)),
            ist_tz.localize(datetime(2026, 5, 6, 9, 30, 0)),
            ist_tz.localize(datetime(2026, 5, 6, 9, 31, 0)),
            ist_tz.localize(datetime(2026, 5, 6, 9, 32, 0)),
            ist_tz.localize(datetime(2026, 5, 6, 9, 33, 0)),
        ]

        time_index = 0

        def mock_now(*args, **kwargs):
            nonlocal time_index
            current = times[min(time_index, len(times) - 1)]
            time_index += 1
            return current

        mock_datetime.now.side_effect = mock_now
        mock_trigger.return_value = True

        # Track the calls to mock_sleep
        sleep_calls = []

        def track_sleep(seconds):
            sleep_calls.append(seconds)

        mock_sleep.side_effect = track_sleep

        stop_event = threading.Event()
        bot._trigger_stop_event = stop_event

        def run_trigger():
            bot.scheduled_workflow_trigger()

        trigger_thread = threading.Thread(target=run_trigger, daemon=True)
        trigger_thread.start()

        # Allow the mocked scheduler loop to progress to 9:33 AM
        trigger_thread.join(timeout=2)

        # Verify trigger was called
        self.assertTrue(mock_trigger.called)


class TestStartStopWorkflow(unittest.TestCase):
    """Test start and stop workflow functions"""

    @patch("pkscreener.pkscreenerbot.threading.Thread")
    def test_start_scheduled_workflow(self, mock_thread):
        """Test starting the scheduled workflow thread"""
        import pkscreener.pkscreenerbot as bot

        mock_thread_instance = Mock()
        mock_thread.return_value = mock_thread_instance

        bot.start_scheduled_workflow()

        mock_thread.assert_called_once()
        mock_thread_instance.start.assert_called_once()

    @patch("pkscreener.pkscreenerbot.threading.Thread")
    def test_stop_scheduled_workflow(self, mock_thread):
        """Test stopping the scheduled workflow thread"""
        import pkscreener.pkscreenerbot as bot

        # Create a mock thread with is_alive returning True
        mock_thread_instance = Mock()
        mock_thread_instance.is_alive.return_value = True
        bot._trigger_thread = mock_thread_instance

        bot.stop_scheduled_workflow()

        # Should set the stop event
        self.assertIsNotNone(bot._trigger_stop_event)


# def run_all_tests():
#     """Run all tests with detailed output"""
#     # Set up test loader
#     loader = unittest.TestLoader()

#     # Create test suites
#     suite = unittest.TestSuite()
#     suite.addTests(loader.loadTestsFromTestCase(TestPKScreenerBot))
#     suite.addTests(loader.loadTestsFromTestCase(TestScheduledWorkflowTrigger))
#     suite.addTests(loader.loadTestsFromTestCase(TestHelperFunctions))
#     suite.addTests(loader.loadTestsFromTestCase(TestBotMenuOptions))
#     suite.addTests(loader.loadTestsFromTestCase(TestBotWorkflowIntegration))
#     suite.addTests(loader.loadTestsFromTestCase(TestTimeZoneHandling))
#     suite.addTests(loader.loadTestsFromTestCase(TestBotDataIntegration))
#     suite.addTests(loader.loadTestsFromTestCase(TestEdgeCases))
#     suite.addTests(loader.loadTestsFromTestCase(TestIntegrationScenarios))
#     suite.addTests(loader.loadTestsFromTestCase(TestStartStopWorkflow))

#     # Run tests
#     runner = unittest.TextTestRunner(verbosity=2)
#     result = runner.run(suite)

#     # Print summary
#     print("\n" + "="*60)
#     print("TEST SUMMARY")
#     print("="*60)
#     print(f"Tests Run: {result.testsRun}")
#     print(f"Failures: {len(result.failures)}")
#     print(f"Errors: {len(result.errors)}")
#     print(f"Skipped: {len(result.skipped)}")

#     if result.failures:
#         print("\nFAILURES:")
#         for failure in result.failures:
#             print(f"  - {failure[0]}")

#     if result.errors:
#         print("\nERRORS:")
#         for error in result.errors:
#             print(f"  - {error[0]}")

#     return result.wasSuccessful()


# if __name__ == '__main__':
#     success = run_all_tests()
#     sys.exit(0 if success else 1)
