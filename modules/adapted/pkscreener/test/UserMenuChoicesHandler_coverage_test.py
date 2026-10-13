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

    Tests for UserMenuChoicesHandler.py to achieve 90%+ coverage.
"""

import warnings
from argparse import Namespace
from unittest.mock import patch

import pytest

warnings.filterwarnings("ignore")


class TestUserMenuChoicesHandlerCoverage:
    """Comprehensive tests for UserMenuChoicesHandler."""

    def test_config_manager_exists(self):
        """Test configManager class attribute exists."""
        from pkscreener.classes.UserMenuChoicesHandler import UserMenuChoicesHandler

        assert hasattr(UserMenuChoicesHandler, "configManager")
        assert UserMenuChoicesHandler.configManager is not None

    @patch(
        "pkscreener.classes.UserMenuChoicesHandler.AssetsManager.PKAssetsManager.afterMarketStockDataExists"
    )
    def test_get_download_choices_no_exists(self, mock_exists):
        """Test getDownloadChoices when cache doesn't exist."""
        import pkscreener.classes.UserMenuChoicesHandler as module
        from pkscreener.classes.UserMenuChoicesHandler import UserMenuChoicesHandler

        mock_exists.return_value = (False, "cache.pkl")
        module.userPassedArgs = Namespace(intraday=None)

        result = UserMenuChoicesHandler.getDownloadChoices()

        assert result[0] == "X"
        assert result[1] == 12
        assert result[2] == 0

    @patch(
        "pkscreener.classes.UserMenuChoicesHandler.AssetsManager.PKAssetsManager.afterMarketStockDataExists"
    )
    @patch(
        "pkscreener.classes.UserMenuChoicesHandler.AssetsManager.PKAssetsManager.promptFileExists"
    )
    def test_get_download_choices_exists_replace_yes(self, mock_prompt, mock_exists):
        """Test getDownloadChoices when cache exists and user replaces."""
        import pkscreener.classes.UserMenuChoicesHandler as module
        from pkscreener.classes.UserMenuChoicesHandler import UserMenuChoicesHandler

        mock_exists.return_value = (True, "cache.pkl")
        mock_prompt.return_value = "Y"
        module.userPassedArgs = Namespace(intraday=None)

        with patch.object(UserMenuChoicesHandler.configManager, "deleteFileWithPattern"):
            result = UserMenuChoicesHandler.getDownloadChoices()

            assert result[0] == "X"

    @patch(
        "pkscreener.classes.UserMenuChoicesHandler.AssetsManager.PKAssetsManager.afterMarketStockDataExists"
    )
    @patch(
        "pkscreener.classes.UserMenuChoicesHandler.AssetsManager.PKAssetsManager.promptFileExists"
    )
    def test_get_download_choices_exists_replace_no(self, mock_prompt, mock_exists):
        """Test getDownloadChoices when user doesn't replace."""
        import pkscreener.classes.UserMenuChoicesHandler as module
        from pkscreener.classes.UserMenuChoicesHandler import UserMenuChoicesHandler

        mock_exists.return_value = (True, "cache.pkl")
        mock_prompt.return_value = "N"
        module.userPassedArgs = Namespace(intraday=None)

        with patch("PKDevTools.classes.OutputControls.OutputControls.printOutput"):
            with pytest.raises(SystemExit):
                UserMenuChoicesHandler.getDownloadChoices()

    @patch(
        "pkscreener.classes.UserMenuChoicesHandler.AssetsManager.PKAssetsManager.afterMarketStockDataExists"
    )
    def test_get_download_choices_intraday(self, mock_exists):
        """Test getDownloadChoices with intraday mode."""
        import pkscreener.classes.UserMenuChoicesHandler as module
        from pkscreener.classes.UserMenuChoicesHandler import UserMenuChoicesHandler

        mock_exists.return_value = (False, "intraday_cache.pkl")
        module.userPassedArgs = Namespace(intraday=True)

        result = UserMenuChoicesHandler.getDownloadChoices()

        assert result[0] == "X"

    def test_get_top_level_menu_choices_none_options(self):
        """Test getTopLevelMenuChoices with None options."""
        import pkscreener.classes.UserMenuChoicesHandler as module
        from pkscreener.classes.UserMenuChoicesHandler import UserMenuChoicesHandler

        module.selectedChoice = {}
        module.userPassedArgs = Namespace(intraday=None)

        options, menu, index, execute = UserMenuChoicesHandler.getTopLevelMenuChoices(
            None, False, False
        )

        assert options == []
        assert menu is None

    def test_get_top_level_menu_choices_with_options(self):
        """Test getTopLevelMenuChoices with options string."""
        import pkscreener.classes.UserMenuChoicesHandler as module
        from pkscreener.classes.UserMenuChoicesHandler import UserMenuChoicesHandler

        module.selectedChoice = {}
        module.userPassedArgs = Namespace(intraday=None)

        options, menu, index, execute = UserMenuChoicesHandler.getTopLevelMenuChoices(
            "X:12:1", False, False
        )

        assert options == ["X", "12", "1"]
        assert menu == "X"
        assert index == "12"
        assert execute == "1"

    def test_get_top_level_menu_choices_test_build(self):
        """Test getTopLevelMenuChoices in test build mode."""
        import pkscreener.classes.UserMenuChoicesHandler as module
        from pkscreener.classes.UserMenuChoicesHandler import UserMenuChoicesHandler

        module.selectedChoice = {}
        module.userPassedArgs = Namespace(intraday=None)

        options, menu, index, execute = UserMenuChoicesHandler.getTopLevelMenuChoices(
            "X:12:1", True, False
        )

        assert menu == "X"

    @patch("pkscreener.classes.UserMenuChoicesHandler.UserMenuChoicesHandler.getDownloadChoices")
    @patch(
        "pkscreener.classes.UserMenuChoicesHandler.AssetsManager.PKAssetsManager.afterMarketStockDataExists"
    )
    @patch("pkscreener.classes.UserMenuChoicesHandler.Utility.tools.set_github_output")
    def test_get_top_level_menu_choices_download_only(
        self, mock_github, mock_exists, mock_download
    ):
        """Test getTopLevelMenuChoices in download only mode."""
        import pkscreener.classes.UserMenuChoicesHandler as module
        from pkscreener.classes.UserMenuChoicesHandler import UserMenuChoicesHandler

        mock_download.return_value = ("X", 12, 0, {"0": "X"})
        mock_exists.return_value = (False, "cache.pkl")
        module.selectedChoice = {}
        module.userPassedArgs = Namespace(intraday=None)

        options, menu, index, execute = UserMenuChoicesHandler.getTopLevelMenuChoices(
            None, False, True
        )

        assert menu == "X"

    def test_get_test_build_choices_with_menu(self):
        """Test getTestBuildChoices with menu option."""
        from pkscreener.classes.UserMenuChoicesHandler import UserMenuChoicesHandler

        result = UserMenuChoicesHandler.getTestBuildChoices(
            menuOption="X", indexOption=12, executeOption=1
        )

        assert result[0] == "X"
        assert result[1] == 12
        assert result[2] == 1

    def test_get_test_build_choices_defaults(self):
        """Test getTestBuildChoices with defaults."""
        from pkscreener.classes.UserMenuChoicesHandler import UserMenuChoicesHandler

        result = UserMenuChoicesHandler.getTestBuildChoices()

        assert result[0] == "X"
        assert result[1] == 1
        assert result[2] == 0

    def test_get_test_build_choices_partial(self):
        """Test getTestBuildChoices with partial options."""
        from pkscreener.classes.UserMenuChoicesHandler import UserMenuChoicesHandler

        result = UserMenuChoicesHandler.getTestBuildChoices(menuOption="Y")

        assert result[0] == "Y"
        assert result[1] == 1  # default
        assert result[2] == 0  # default

    @patch("builtins.input", return_value="")
    def test_handle_exit_request_z(self, mock_input):
        """Test handleExitRequest with Z option."""
        from pkscreener.classes.UserMenuChoicesHandler import UserMenuChoicesHandler

        with pytest.raises(SystemExit):
            UserMenuChoicesHandler.handleExitRequest("Z")

    def test_handle_exit_request_non_z(self):
        """Test handleExitRequest with non-Z option."""
        from pkscreener.classes.UserMenuChoicesHandler import UserMenuChoicesHandler

        # Should not exit
        UserMenuChoicesHandler.handleExitRequest("X")
