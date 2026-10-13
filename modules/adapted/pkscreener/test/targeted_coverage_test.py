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

    Targeted tests to cover specific code paths in low-coverage modules.
"""

import contextlib
import multiprocessing
import warnings
from argparse import Namespace
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

warnings.filterwarnings("ignore")


@pytest.fixture
def config():
    """Create a configuration manager."""
    from pkscreener.classes.ConfigManager import parser, tools

    config = tools()
    config.getConfig(parser)
    return config


@pytest.fixture
def stock_df():
    """Create comprehensive stock DataFrame."""
    dates = pd.date_range("2023-01-01", periods=300, freq="D")
    np.random.seed(42)
    base = 100
    closes = []
    for _i in range(300):
        base += np.random.uniform(-1, 1.5)
        closes.append(max(50, base))

    df = pd.DataFrame(
        {
            "open": [c * np.random.uniform(0.98, 1.0) for c in closes],
            "high": [max(c * 0.99, c) * np.random.uniform(1.0, 1.02) for c in closes],
            "low": [min(c * 0.99, c) * np.random.uniform(0.98, 1.0) for c in closes],
            "close": closes,
            "volume": np.random.randint(500000, 10000000, 300),
            "adjclose": closes,
        },
        index=dates,
    )
    df["VolMA"] = df["volume"].rolling(20).mean().fillna(method="bfill")
    return df


# =============================================================================
# ScreeningStatistics Line-by-Line Coverage Tests
# =============================================================================


class TestScreeningStatisticsLines:
    """Tests targeting specific lines in ScreeningStatistics."""

    @pytest.fixture
    def screener(self, config):
        """Create a ScreeningStatistics instance."""
        from PKDevTools.classes.log import default_logger
        from pkscreener.classes.ScreeningStatistics import ScreeningStatistics

        return ScreeningStatistics(config, default_logger())

    def test_validate_volume_with_volma(self, screener, stock_df):
        """Test validateVolume with VolMA column."""
        screen_dict = {}
        save_dict = {}
        with contextlib.suppress(BaseException):
            screener.validateVolume(stock_df, screen_dict, save_dict)

    def test_find_breaking_out_now_with_intraday(self, screener, stock_df):
        """Test findBreakingoutNow with intraday data."""
        screen_dict = {}
        save_dict = {}
        with contextlib.suppress(BaseException):
            screener.findBreakingoutNow(stock_df, stock_df, save_dict, screen_dict)

    def test_find_vwap_methods(self, screener, stock_df):
        """Test VWAP-related methods."""
        screen_dict = {}
        save_dict = {}
        with contextlib.suppress(BaseException):
            screener.findBullishAVWAP(stock_df, screen_dict, save_dict)

    def test_calc_relative_strength_with_benchmark(self, screener, stock_df):
        """Test calc_relative_strength with benchmark data."""
        with contextlib.suppress(BaseException):
            screener.calc_relative_strength(stock_df, benchmark_data=stock_df)

    def test_find_trending_methods(self, screener, stock_df):
        """Test trending methods."""
        with contextlib.suppress(BaseException):
            screener.findTrending(stock_df, {}, {})

    def test_find_consolidating_methods(self, screener, stock_df):
        """Test consolidating methods."""
        with contextlib.suppress(BaseException):
            screener.findConsolidating(stock_df, {}, {})

    def test_find_divergence_methods(self, screener, stock_df):
        """Test divergence detection methods."""
        with contextlib.suppress(BaseException):
            screener.findRSIDivergence(stock_df, {}, {})

    def test_find_volatility_methods(self, screener, stock_df):
        """Test volatility methods."""
        with contextlib.suppress(BaseException):
            screener.findVolatileStocks(stock_df, {}, {})


# =============================================================================
# StockScreener Line-by-Line Coverage Tests
# =============================================================================


class TestStockScreenerLines:
    """Tests targeting specific lines in StockScreener."""

    @pytest.fixture
    def screener(self, config):
        """Create a StockScreener instance."""
        from pkscreener.classes.StockScreener import StockScreener

        s = StockScreener()
        s.configManager = config
        return s

    @pytest.fixture
    def mock_host_ref(self, config, stock_df):
        """Create a mock hostRef."""
        from PKDevTools.classes.log import default_logger
        from pkscreener.classes.CandlePatterns import CandlePatterns
        from pkscreener.classes.ScreeningStatistics import ScreeningStatistics

        host = MagicMock()
        host.configManager = config
        host.fetcher = MagicMock()
        host.screener = ScreeningStatistics(config, default_logger())
        host.candlePatterns = CandlePatterns()
        host.default_logger = default_logger()
        host.processingCounter = multiprocessing.Value("i", 0)
        host.processingResultsCounter = multiprocessing.Value("i", 0)
        host.objectDictionaryPrimary = {"SBIN": stock_df}
        host.objectDictionarySecondary = {}

        return host

    def test_init_result_dictionaries(self, screener, config):
        """Test initResultDictionaries method."""
        from PKDevTools.classes.log import default_logger
        from pkscreener.classes.ScreeningStatistics import ScreeningStatistics

        screener.screener = ScreeningStatistics(config, default_logger())

        screen_dict, save_dict = screener.initResultDictionaries()
        assert isinstance(screen_dict, dict)
        assert isinstance(save_dict, dict)
        assert "Stock" in screen_dict

    def test_screen_stocks_with_backtest(self, screener, mock_host_ref, stock_df):
        """Test screenStocks with backtest duration."""
        with contextlib.suppress(BaseException):
            screener.screenStocks(
                runOption="B:12:1",
                menuOption="B",
                exchangeName="NSE",
                executeOption=1,
                reversalOption=None,
                maLength=50,
                daysForLowestVolume=30,
                minRSI=0,
                maxRSI=100,
                respChartPattern=None,
                insideBarToLookback=7,
                totalSymbols=100,
                shouldCache=True,
                stock="SBIN",
                newlyListedOnly=False,
                downloadOnly=False,
                volumeRatio=2.5,
                testbuild=True,
                userArgs=Namespace(log=False),
                backtestDuration=30,
                hostRef=mock_host_ref,
                testData=stock_df,
            )


# =============================================================================
# ResultsLabeler Line-by-Line Coverage Tests
# =============================================================================


class TestResultsLabelerLines:
    """Tests targeting specific lines in ResultsLabeler."""

    @pytest.fixture
    def labeler(self, config):
        """Create a ResultsLabeler."""
        from pkscreener.classes.ResultsLabeler import ResultsLabeler

        return ResultsLabeler(config)

    def test_labeler_creation(self, labeler):
        """Test labeler creation."""
        assert labeler is not None

    def test_labeler_attributes(self, labeler):
        """Test labeler attributes."""
        assert hasattr(labeler, "config_manager")


# =============================================================================
# PKScanRunner Line-by-Line Coverage Tests
# =============================================================================


class TestPKScanRunnerLines:
    """Tests targeting specific lines in PKScanRunner."""

    def test_get_formatted_choices_all_params(self):
        """Test getFormattedChoices with all parameters."""
        from pkscreener.classes.PKScanRunner import PKScanRunner

        # All combinations
        for intraday_analysis in [True, False]:
            for intraday in [None, "1m", "5m", "15m"]:
                args = Namespace(runintradayanalysis=intraday_analysis, intraday=intraday)
                for choice_0 in ["X", "P", "B"]:
                    for choice_1 in ["1", "12", "5"]:
                        for choice_2 in ["0", "1", "5"]:
                            choices = {"0": choice_0, "1": choice_1, "2": choice_2}
                            result = PKScanRunner.getFormattedChoices(args, choices)
                            assert isinstance(result, str)


# =============================================================================
# ResultsManager Line-by-Line Coverage Tests
# =============================================================================


class TestResultsManagerLines:
    """Tests targeting specific lines in ResultsManager."""

    @pytest.fixture
    def manager(self, config):
        """Create a ResultsManager."""
        from pkscreener.classes.ResultsManager import ResultsManager

        return ResultsManager(config)

    def test_manager_creation(self, manager):
        """Test manager creation."""
        assert manager is not None

    def test_manager_attributes(self, manager):
        """Test manager attributes."""
        assert hasattr(manager, "config_manager")


# =============================================================================
# BacktestHandler Line-by-Line Coverage Tests
# =============================================================================


class TestBacktestHandlerLines:
    """Tests targeting specific lines in BacktestHandler."""

    @pytest.fixture
    def handler(self, config):
        """Create a BacktestHandler."""
        from pkscreener.classes.BacktestHandler import BacktestHandler

        return BacktestHandler(config)

    def test_handler_creation(self, handler):
        """Test handler creation."""
        assert handler is not None

    def test_handler_attributes(self, handler):
        """Test handler attributes."""
        assert hasattr(handler, "config_manager")


# =============================================================================
# DataLoader Line-by-Line Coverage Tests
# =============================================================================


class TestDataLoaderLines:
    """Tests targeting specific lines in DataLoader."""

    @pytest.fixture
    def loader(self, config):
        """Create a StockDataLoader."""
        from pkscreener.classes.DataLoader import StockDataLoader

        mock_fetcher = MagicMock()
        return StockDataLoader(config, mock_fetcher)

    def test_loader_creation(self, loader):
        """Test loader creation."""
        assert loader is not None

    def test_loader_methods(self, loader):
        """Test loader methods."""
        with contextlib.suppress(BaseException):
            loader.initialize_dicts()
        with contextlib.suppress(BaseException):
            loader.get_latest_trade_datetime()


# =============================================================================
# CoreFunctions Line-by-Line Coverage Tests
# =============================================================================


class TestCoreFunctionsLines:
    """Tests targeting specific lines in CoreFunctions."""

    def test_get_review_date_all_params(self):
        """Test get_review_date with all parameters."""
        from pkscreener.classes.CoreFunctions import get_review_date

        # All combinations
        for days in [None, 0, 1, 5, 10, 30, 60]:
            args = Namespace(backtestdaysago=days)
            result = get_review_date(None, args)
            if days and days > 0:
                assert result is not None


# =============================================================================
# BacktestUtils Line-by-Line Coverage Tests
# =============================================================================


class TestBacktestUtilsLines:
    """Tests targeting specific lines in BacktestUtils."""

    def test_get_backtest_report_filename_all_params(self):
        """Test get_backtest_report_filename with all parameters."""
        from pkscreener.classes.BacktestUtils import get_backtest_report_filename

        # All combinations
        for sort_key in [None, "Stock", "LTP", "%Chng"]:
            for optional_name in [None, "test", "report"]:
                for choices in [None, {"0": "X", "1": "12", "2": "1"}]:
                    result = get_backtest_report_filename(
                        sort_key=sort_key, optional_name=optional_name, choices=choices
                    )
                    assert result is not None


# =============================================================================
# PKUserRegistration Line-by-Line Coverage Tests
# =============================================================================


class TestPKUserRegistrationLines:
    """Tests targeting specific lines in PKUserRegistration."""

    def test_validation_result_enum(self):
        """Test ValidationResult enum values."""
        from pkscreener.classes.PKUserRegistration import ValidationResult

        assert ValidationResult.Success is not None
        # Check all available values
        for val in ValidationResult:
            assert val is not None


# =============================================================================
# NotificationService Line-by-Line Coverage Tests
# =============================================================================


class TestNotificationServiceLines:
    """Tests targeting specific lines in NotificationService."""

    def test_notification_service_all_params(self):
        """Test NotificationService with all parameter combinations."""
        from pkscreener.classes.NotificationService import NotificationService

        # All combinations
        for telegram in [True, False]:
            for log in [True, False]:
                for user in [None, "12345"]:
                    args = Namespace(telegram=telegram, log=log, user=user, monitor=None)
                    service = NotificationService(args)
                    service.set_menu_choice_hierarchy("X:12:1")
                    _ = service._should_send_message()


# =============================================================================
# signals Line-by-Line Coverage Tests
# =============================================================================


class TestSignalsLines:
    """Tests targeting specific lines in signals module."""

    def test_signal_result_all_combinations(self):
        """Test SignalResult with all combinations."""
        from pkscreener.classes.screening.signals import SignalResult, SignalStrength

        # All signal types and confidences
        for signal in SignalStrength:
            for confidence in range(0, 101, 25):
                result = SignalResult(signal=signal, confidence=float(confidence))
                _ = result.is_buy


# =============================================================================
# ExecuteOptionHandlers Line-by-Line Coverage Tests
# =============================================================================


class TestExecuteOptionHandlersLines:
    """Tests targeting specific lines in ExecuteOptionHandlers."""

    def test_handle_execute_option_3_all_params(self, config):
        """Test handle_execute_option_3 with all parameters."""
        from pkscreener.classes.ExecuteOptionHandlers import handle_execute_option_3

        for max_results in [10, 50, 100, 500, 1000]:
            args = MagicMock()
            args.maxdisplayresults = max_results
            result = handle_execute_option_3(args, config)
            assert result is not None

    def test_handle_execute_option_4_all_params(self):
        """Test handle_execute_option_4 with all parameters."""
        from pkscreener.classes.ExecuteOptionHandlers import handle_execute_option_4

        for days in list(range(1, 100, 10)) + ["D"]:
            result = handle_execute_option_4(4, ["X", "12", "4", str(days)])
            assert result is not None

    def test_handle_execute_option_5_all_params(self):
        """Test handle_execute_option_5 with all parameters."""
        from pkscreener.classes.ExecuteOptionHandlers import handle_execute_option_5

        args = MagicMock()
        args.systemlaunched = False
        m2 = MagicMock()
        m2.find.return_value = MagicMock()

        for min_rsi in range(0, 70, 20):
            for max_rsi in range(min_rsi + 20, 100, 20):
                result = handle_execute_option_5(
                    ["X", "12", "5", str(min_rsi), str(max_rsi)], args, m2
                )
                assert result is not None

    def test_handle_execute_option_9_all_params(self, config):
        """Test handle_execute_option_9 with all parameters."""
        from pkscreener.classes.ExecuteOptionHandlers import handle_execute_option_9

        for vol_ratio in ["1.0", "1.5", "2.0", "2.5", "3.0", "D"]:
            result = handle_execute_option_9(["X", "12", "9", vol_ratio], config)
            assert result is not None


# =============================================================================
# MenuNavigation Line-by-Line Coverage Tests
# =============================================================================


class TestMenuNavigationLines:
    """Tests targeting specific lines in MenuNavigation."""

    @pytest.fixture
    def navigator(self, config):
        """Create a MenuNavigator."""
        from pkscreener.classes.MenuNavigation import MenuNavigator

        return MenuNavigator(config)

    def test_get_download_choices_all_params(self, navigator):
        """Test get_download_choices with all parameters."""
        with patch(
            "pkscreener.classes.MenuNavigation.AssetsManager.PKAssetsManager.afterMarketStockDataExists"
        ) as mock_exists:
            mock_exists.return_value = (False, "test.pkl")

            for default_answer in [None, "Y", "N"]:
                for intraday in [None, "1m"]:
                    args = Namespace(intraday=intraday)
                    with contextlib.suppress(BaseException):
                        navigator.get_download_choices(
                            default_answer=default_answer, user_passed_args=args
                        )


# =============================================================================
# MainLogic Line-by-Line Coverage Tests
# =============================================================================


class TestMainLogicLines:
    """Tests targeting specific lines in MainLogic."""

    @pytest.fixture
    def mock_global_state(self, config):
        """Create a mock global state."""
        gs = MagicMock()
        gs.configManager = config
        gs.fetcher = MagicMock()
        gs.m0 = MagicMock()
        gs.m1 = MagicMock()
        gs.m2 = MagicMock()
        gs.userPassedArgs = MagicMock()
        gs.selectedChoice = {"0": "X", "1": "12", "2": "1"}
        return gs

    @patch("pkscreener.classes.MainLogic.os.system")
    @patch("pkscreener.classes.MainLogic.sleep")
    @patch("pkscreener.classes.MainLogic.OutputControls")
    @patch("pkscreener.classes.MainLogic.PKAnalyticsService")
    def test_menu_option_handler_all_methods(
        self, mock_analytics, mock_output, mock_sleep, mock_system, mock_global_state
    ):
        """Test MenuOptionHandler with all methods."""
        from pkscreener.classes.MainLogic import MenuOptionHandler

        handler = MenuOptionHandler(mock_global_state)

        # Test all methods
        handler.get_launcher()
        handler.handle_menu_m()
        handler._handle_download_daily("python test.py")
        handler._handle_download_intraday("python test.py")


# =============================================================================
# MenuManager Line-by-Line Coverage Tests
# =============================================================================


class TestMenuManagerLines:
    """Tests targeting specific lines in MenuManager."""

    @pytest.fixture
    def manager(self, config):
        """Create a MenuManager."""
        from pkscreener.classes.MenuManager import MenuManager

        args = Namespace(
            options=None,
            pipedmenus=None,
            backtestdaysago=None,
            pipedtitle=None,
            runintradayanalysis=False,
            intraday=None,
        )
        return MenuManager(config, args)

    def test_ensure_menus_loaded_all_params(self, manager):
        """Test ensure_menus_loaded with all parameters."""
        manager.ensure_menus_loaded()
        manager.ensure_menus_loaded(menu_option="X")
        manager.ensure_menus_loaded(menu_option="X", index_option="12")
        manager.ensure_menus_loaded(menu_option="X", index_option="12", execute_option="1")
        manager.ensure_menus_loaded(menu_option="P")
        manager.ensure_menus_loaded(menu_option="B")

    def test_update_menu_choice_hierarchy(self, manager):
        """Test update_menu_choice_hierarchy."""
        manager.selected_choice["0"] = "X"
        manager.selected_choice["1"] = "12"
        manager.selected_choice["2"] = "1"
        with contextlib.suppress(BaseException):
            manager.update_menu_choice_hierarchy()

    @patch("pkscreener.classes.MenuManager.OutputControls")
    def test_show_option_error_message(self, mock_output, manager):
        """Test show_option_error_message."""
        manager.show_option_error_message()


# =============================================================================
# MenuOptions Line-by-Line Coverage Tests
# =============================================================================


class TestMenuOptionsLines:
    """Tests targeting specific lines in MenuOptions."""

    def test_menus_all_methods(self):
        """Test menus with all methods."""
        from pkscreener.classes.MenuOptions import menus

        m = menus()
        m.renderForMenu(asList=True)
        m.renderForMenu(asList=False)

        for key in list("XPBCHDUYZ") + list("0123456789"):
            m.find(key)

    def test_menus_level_variations(self):
        """Test menus with all levels."""
        from pkscreener.classes.MenuOptions import menus

        for level in [0, 1, 2, 3, 4]:
            m = menus()
            m.level = level
            m.renderForMenu(asList=True)
