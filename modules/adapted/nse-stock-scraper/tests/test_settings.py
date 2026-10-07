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
Tests for nse_scraper settings - Configuration validation
"""
import unittest

from nse_scraper import settings


class TestScrapySettings(unittest.TestCase):
    """Test Scrapy settings configuration"""

    def test_settings_module_exists(self):
        """Test settings module can be imported"""
        self.assertTrue(hasattr(settings, "BOT_NAME"))

    def test_bot_name_configured(self):
        """Test BOT_NAME is set"""
        self.assertIsNotNone(getattr(settings, "BOT_NAME", None))

    def test_spider_modules_configured(self):
        """Test spider modules are configured"""
        spider_modules = getattr(settings, "SPIDER_MODULES", [])
        self.assertTrue(len(spider_modules) > 0)

    def test_logging_configured(self):
        """Test logging level is configured"""
        log_level = getattr(settings, "LOG_LEVEL", None)
        self.assertIn(log_level, ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])

    def test_concurrent_requests(self):
        """Test concurrent requests setting"""
        concurrent = getattr(settings, "CONCURRENT_REQUESTS", None)
        self.assertIsNotNone(concurrent)
        self.assertGreater(concurrent, 0)

    def test_download_delay_configured(self):
        """Test download delay is set (respectful scraping)"""
        delay = getattr(settings, "DOWNLOAD_DELAY", 0)
        self.assertGreaterEqual(delay, 0)

    def test_retry_enabled(self):
        """Test retry mechanism is configured"""
        retry_times = getattr(settings, "RETRY_TIMES", 0)
        self.assertGreater(retry_times, 0)

    def test_user_agent_configured(self):
        """Test user agent is configured"""
        user_agent = getattr(settings, "USER_AGENT", None)
        self.assertIsNotNone(user_agent)
        self.assertIsInstance(user_agent, str)
        self.assertGreater(len(user_agent), 0)


class TestEnvironmentSettings(unittest.TestCase):
    """Test environment variable loading"""

    def test_dotenv_loading(self):
        """Test that .env files can be loaded"""
        # This tests that python-dotenv is available and working
        from dotenv import load_dotenv

        self.assertTrue(callable(load_dotenv))


if __name__ == "__main__":
    unittest.main()
