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

import unittest
from unittest.mock import MagicMock, patch

from pkscreener.classes.ConsoleMenuUtility import PKConsoleMenuTools


class TestPKConsoleMenuTools(unittest.TestCase):
    @patch("builtins.input", side_effect=["55", "68"])
    @patch("pkscreener.classes.ConsoleUtility.PKConsoleTools.clearScreen")
    def test_prompt_rsi_values_success(self, mock_clear, mock_input):
        min_rsi, max_rsi = PKConsoleMenuTools.promptRSIValues()
        self.assertEqual(min_rsi, 55)
        self.assertEqual(max_rsi, 68)
        mock_clear.assert_called_once()

    @patch("builtins.input", side_effect=["invalid", "150"])
    @patch("pkscreener.classes.ConsoleUtility.PKConsoleTools.clearScreen")
    @patch("PKDevTools.classes.log.emptylogger.debug")
    def test_prompt_rsi_values_invalid(self, mock_logger, mock_clear, mock_input):
        min_rsi, max_rsi = PKConsoleMenuTools.promptRSIValues()
        self.assertEqual(min_rsi, 0)
        self.assertEqual(max_rsi, 0)
        mock_logger.assert_called()
        mock_clear.assert_called_once()

    @patch("builtins.input", side_effect=["110", "300"])
    @patch("pkscreener.classes.ConsoleUtility.PKConsoleTools.clearScreen")
    def test_prompt_cci_values_success(self, mock_clear, mock_input):
        min_cci, max_cci = PKConsoleMenuTools.promptCCIValues()
        self.assertEqual(min_cci, 110)
        self.assertEqual(max_cci, 300)
        mock_clear.assert_called_once()

    @patch("builtins.input", side_effect=["invalid", "50"])
    @patch("pkscreener.classes.ConsoleUtility.PKConsoleTools.clearScreen")
    @patch("PKDevTools.classes.log.emptylogger.debug")
    def test_prompt_cci_values_invalid(self, mock_logger, mock_clear, mock_input):
        min_cci, max_cci = PKConsoleMenuTools.promptCCIValues()
        self.assertEqual(min_cci, -100)
        self.assertEqual(max_cci, 100)
        mock_logger.assert_called()
        mock_clear.assert_called_once()

    @patch("builtins.input", side_effect=["2.5"])
    @patch("pkscreener.classes.ConsoleUtility.PKConsoleTools.clearScreen")
    def test_prompt_volume_multiplier_success(self, mock_clear, mock_input):
        volume_ratio = PKConsoleMenuTools.promptVolumeMultiplier()
        self.assertEqual(volume_ratio, 2.5)
        mock_clear.assert_called_once()

    @patch("builtins.input", side_effect=["invalid"])
    @patch("pkscreener.classes.ConsoleUtility.PKConsoleTools.clearScreen")
    @patch("PKDevTools.classes.log.emptylogger.debug")
    def test_prompt_volume_multiplier_invalid(self, mock_logger, mock_clear, mock_input):
        volume_ratio = PKConsoleMenuTools.promptVolumeMultiplier()
        self.assertEqual(volume_ratio, 2)
        mock_logger.assert_called()
        mock_clear.assert_called_once()

    @patch("pkscreener.classes.MenuOptions.menus.renderForMenu")
    @patch("pkscreener.classes.ConsoleUtility.PKConsoleTools.clearScreen")
    def test_prompt_menus(self, mock_clear, mock_render):
        menu = MagicMock()
        PKConsoleMenuTools.promptMenus(menu)
        mock_render.assert_called_once_with(menu)
        mock_clear.assert_called_once()

    @patch("builtins.input", side_effect=["1"])
    @patch("pkscreener.classes.ConsoleUtility.PKConsoleTools.clearScreen")
    def test_prompt_sub_menu_options_success(self, mock_clear, mock_input):
        resp = PKConsoleMenuTools.promptSubMenuOptions()
        self.assertEqual(resp, 1)
        mock_clear.assert_called_once()

    @patch("builtins.input", side_effect=["invalid"])
    @patch("pkscreener.classes.ConsoleUtility.PKConsoleTools.clearScreen")
    @patch("PKDevTools.classes.log.emptylogger.debug")
    @patch("PKDevTools.classes.OutputControls.OutputControls.takeUserInput")
    def test_prompt_sub_menu_options_invalid(
        self, mock_user_input, mock_logger, mock_clear, mock_input
    ):
        resp = PKConsoleMenuTools.promptSubMenuOptions()
        self.assertIsNone(resp)
        mock_logger.assert_called()
        mock_user_input.assert_called()
        mock_clear.assert_called_once()

    @patch("builtins.input", side_effect=["3", "0.8"])
    @patch("pkscreener.classes.ConsoleUtility.PKConsoleTools.clearScreen")
    def test_prompt_chart_patterns_success(self, mock_clear, mock_input):
        resp, extra = PKConsoleMenuTools.promptChartPatterns()
        self.assertEqual(resp, 3)
        self.assertEqual(extra, 0.008)  # 0.8 / 100
        mock_clear.assert_called_once()

    @patch("builtins.input", side_effect=["invalid"])
    @patch("pkscreener.classes.ConsoleUtility.PKConsoleTools.clearScreen")
    @patch("PKDevTools.classes.log.emptylogger.debug")
    @patch("PKDevTools.classes.OutputControls.OutputControls.takeUserInput")
    def test_prompt_chart_patterns_invalid(
        self, mock_user_input, mock_logger, mock_clear, mock_input
    ):
        resp, extra = PKConsoleMenuTools.promptChartPatterns()
        self.assertIsNone(resp)
        self.assertIsNone(extra)
        mock_logger.assert_called()
        mock_user_input.assert_called()
        mock_clear.assert_called_once()
