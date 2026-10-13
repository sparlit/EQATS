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
import os
import unittest
from unittest.mock import MagicMock, patch

from PKDevTools.classes.OutputControls import OutputControls
from pkscreener.classes.PKDemoHandler import PKDemoHandler
from pkscreener.classes.PKPremiumHandler import PKPremiumHandler
from pkscreener.classes.PKUserRegistration import PKUserRegistration, ValidationResult


class TestPKPremiumHandler(unittest.TestCase):
    def setUp(self):
        """Set up mock menu objects for testing."""
        self.mock_menu = MagicMock()
        self.mock_menu.isPremium = False
        self.mock_menu.menuText = "Test Menu"

    @patch.object(
        PKUserRegistration, "validateToken", return_value=(True, ValidationResult.Success)
    )
    @patch.dict(os.environ, {"RUNNER": "True"})
    def test_hasPremium_runner_mode(self, mock_validateToken):
        """Test hasPremium() with RUNNER mode enabled."""
        result = PKPremiumHandler.hasPremium(self.mock_menu)
        self.assertTrue(result, "RUNNER mode should allow premium access.")

    @patch.object(
        PKUserRegistration, "validateToken", return_value=(False, ValidationResult.BadOTP)
    )
    def test_hasPremium_no_premium(self, mock_validateToken):
        """Test hasPremium() when the user does not have premium access."""
        result = PKPremiumHandler.hasPremium(self.mock_menu)
        self.assertTrue(result, "Non-premium users should pass for a non-premium menu.")

    @patch("pkscreener.classes.ConsoleUtility.PKConsoleTools.clearScreen")
    @patch.object(
        PKUserRegistration, "validateToken", return_value=(False, ValidationResult.BadOTP)
    )
    @patch.object(PKUserRegistration, "login", return_value=ValidationResult.Success)
    def test_showPremiumDemoOptions_login_attempt(
        self, mock_login, mock_validateToken, mock_clearScreen
    ):
        """Test showPremiumDemoOptions() when user needs to log in."""
        result = PKPremiumHandler.showPremiumDemoOptions(self.mock_menu)
        self.assertEqual(result, ValidationResult.Success, "User should log in successfully.")

    @patch("pkscreener.classes.ConsoleUtility.PKConsoleTools.clearScreen")
    @patch.object(
        PKUserRegistration, "validateToken", return_value=(False, ValidationResult.BadUserID)
    )
    @patch.object(OutputControls, "printOutput")
    @patch("builtins.input", return_value="1")  # Simulate user choosing the demo option
    @patch.object(PKDemoHandler, "demoForMenu")
    @patch("sys.exit")  # Prevent exit from stopping tests
    def test_showPremiumDemoOptions_demo(
        self,
        mock_exit,
        mock_demo,
        mock_input,
        mock_printOutput,
        mock_validateToken,
        mock_clearScreen,
    ):
        """Test showPremiumDemoOptions() when user selects demo option."""
        PKPremiumHandler.showPremiumDemoOptions(self.mock_menu)
        mock_demo.assert_called_once()
        mock_exit.assert_called_once()

    @patch("pkscreener.classes.ConsoleUtility.PKConsoleTools.clearScreen")
    @patch.object(
        PKUserRegistration, "validateToken", return_value=(False, ValidationResult.BadUserID)
    )
    @patch.object(OutputControls, "printOutput")
    @patch("builtins.input", return_value="2")  # Simulate user choosing subscription option
    @patch("sys.exit")  # Prevent exit from stopping tests
    def test_showPremiumDemoOptions_subscription(
        self, mock_exit, mock_input, mock_printOutput, mock_validateToken, mock_clearScreen
    ):
        """Test showPremiumDemoOptions() when user selects subscription details."""
        PKPremiumHandler.showPremiumDemoOptions(self.mock_menu)
        mock_printOutput.assert_called()
        mock_exit.assert_called_once()
