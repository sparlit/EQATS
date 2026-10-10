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
import unittest
from unittest.mock import MagicMock, patch

# Import the class to be tested
from pkscreener.classes.PKDemoHandler import PKDemoHandler


class TestPKDemoHandler(unittest.TestCase):
    @patch("PKDevTools.classes.OutputControls.OutputControls.printOutput")
    @patch("builtins.input", return_value="")  # Mock user input
    @patch("sys.exit")  # Prevent exit from stopping tests
    def test_demoForMenu_default(self, mock_exit, mock_input, mock_printOutput):
        """Test default case for menu key"""
        mock_menu = MagicMock()
        mock_menu.menuKey = "P_1_1"

        PKDemoHandler.demoForMenu(mock_menu)

        mock_printOutput.assert_called_once()
        output_text = mock_printOutput.call_args[0][0]
        self.assertIn("https://asciinema.org/a/b31Tp78QLSzZcxcxCzH7Rljog", output_text)
        mock_exit.assert_called_once()

    @patch("PKDevTools.classes.OutputControls.OutputControls.printOutput")
    @patch("builtins.input", return_value="")
    @patch("sys.exit")
    def test_demoForMenu_find_stock(self, mock_exit, mock_input, mock_printOutput):
        """Test case for 'F' menu key (Find a stock in scanners)"""
        mock_menu = MagicMock()
        mock_menu.menuKey = "F"

        PKDemoHandler.demoForMenu(mock_menu)

        mock_printOutput.assert_called_once()
        output_text = mock_printOutput.call_args[0][0]
        self.assertIn("https://asciinema.org/a/7TA8H8pq94YmTqsrVvtLCpPel", output_text)
        mock_exit.assert_called_once()

    @patch("PKDevTools.classes.OutputControls.OutputControls.printOutput")
    @patch("builtins.input", return_value="")
    @patch("sys.exit")
    def test_demoForMenu_market_scan(self, mock_exit, mock_input, mock_printOutput):
        """Test case for 'M' menu key"""
        mock_menu = MagicMock()
        mock_menu.menuKey = "M"

        PKDemoHandler.demoForMenu(mock_menu)

        mock_printOutput.assert_called_once()
        output_text = mock_printOutput.call_args[0][0]
        self.assertIn("https://asciinema.org/a/NKBXhxc2iWbpxcll35JqwfpuQ", output_text)
        mock_exit.assert_called_once()
