"""
Tests for Intelligent Trading Bot ML Feature Engineering Engine Integration Module
"""

from unittest.mock import AsyncMock, MagicMock, patch

from institutional_integrations.intelligent_trading_bot_engine import (
    MAGIC_NUMBER_INTELLIGENT_TRADING_BOT,
    IntelligentTradingBotBrokerAdapter,
    IntelligentTradingBotEngine,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
)


def test_feature_generation_and_ml_signal():
    engine = IntelligentTradingBotEngine(horizon_bars=60)
    assert engine.magic_number == MAGIC_NUMBER_INTELLIGENT_TRADING_BOT

    prices = [100.0, 101.0, 102.5, 101.8, 103.0, 104.2, 105.0]
    highs = [100.5, 101.5, 103.0, 102.2, 103.5, 104.8, 105.5]
    lows = [99.5, 100.2, 101.0, 101.0, 102.0, 103.5, 104.2]

    features = engine.compute_rolling_features(prices, highs, lows)
    assert features["ret_mean"] > 0.0
    assert features["volatility"] > 0.0
    assert features["high_ratio"] >= 0.0

    eval_res = engine.evaluate_ml_signal(features, close_price=105.02)
    assert eval_res["price"] == 105.00
    assert eval_res["prob_buy"] > 0.5
    assert eval_res["recommended_signal"] == "BUY"


def test_intelligent_trading_bot_broker_adapter():
    adapter = IntelligentTradingBotBrokerAdapter()
    assert IndianBrokerPluginRegistry.get_adapter_class("INTELLIGENT_TRADING_BOT") == IntelligentTradingBotBrokerAdapter

    req = SEBIOrderRequest(
        symbol="RELIANCE",
        quantity=10,
        price=2500.02,
        order_type="BUY",
        product="CNC",
        exchange="NSE",
        order_kind="LIMIT",
    )

    res_unauth = adapter.execute_order(req)
    assert not res_unauth.success

    adapter.connect()

    with patch("institutional_integrations.intelligent_trading_bot_engine.is_ist_market_open", return_value=True):
        res = adapter.execute_order(req)
        assert res.success
        assert res.status == "FILLED"
        assert res.price == 2500.00
        assert res.ticket.startswith("ITBOT-")


import asyncio
import os
import sys

# Add modules/adapted/intelligent-trading-bot to sys.path if necessary for common/service imports
adapt_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "modules", "adapted", "intelligent-trading-bot"))
if adapt_dir not in sys.path:
    sys.path.insert(0, adapt_dir)


def test_cancel_order_success_and_failure():
    mock_mt5 = MagicMock()
    mock_mt5.__author__ = "MetaTrader 5 Ltd."
    mock_mt5.__version__ = "5.0.45"
    mock_mt5.TRADE_ACTION_REMOVE = 1
    mock_mt5.TRADE_RETCODE_DONE = 10009
    mock_mt5.ORDER_STATE_CANCELED = "CANCELED"
    mock_mt5.last_error.return_value = (0, "Success")

    mock_modules = {
        "MetaTrader5": mock_mt5,
        "pytz": MagicMock(),
        "joblib": MagicMock(),
        "dateparser": MagicMock(),
        "apscheduler": MagicMock(),
        "apscheduler.triggers": MagicMock(),
        "apscheduler.triggers.cron": MagicMock(),
        "scipy": MagicMock(),
        "scipy.stats": MagicMock(),
        "sklearn": MagicMock(),
        "sklearn.metrics": MagicMock(),
    }

    with patch.dict(sys.modules, mock_modules):
        from outputs.trader_mt5 import cancel_order, App

        # Test 1: No active order
        App.order = {}
        res = asyncio.run(cancel_order())
        assert res is None

        # Test 2: Successful cancellation
        App.order = {"orderId": 12345}
        mock_result_done = MagicMock()
        mock_result_done.retcode = mock_mt5.TRADE_RETCODE_DONE
        mock_result_done._asdict.return_value = {"orderId": 12345, "state": "CANCELED"}

        with patch.object(mock_mt5, "order_send", return_value=mock_result_done):
            state = asyncio.run(cancel_order())
            assert state == "CANCELED"
            assert App.order["state"] == "CANCELED"

        # Test 3: Failed cancellation with status resync
        App.order = {"orderId": 67890}
        mock_result_fail = MagicMock()
        mock_result_fail.retcode = 10006  # TRADE_RETCODE_REJECT

        with patch.object(mock_mt5, "order_send", return_value=mock_result_fail), \
             patch("outputs.trader_mt5.update_trade_status", new_callable=AsyncMock) as mock_sync:
            res = asyncio.run(cancel_order())
            assert res is None
            mock_sync.assert_called_once()


def test_trader_mt5_order_filled_transitions():
    mock_mt5 = MagicMock()
    mock_mt5.__author__ = "MetaTrader 5 Ltd."
    mock_mt5.__version__ = "5.0.45"
    mock_mt5.ORDER_STATE_FILLED = 4
    mock_mt5.ORDER_STATE_PLACED = 1
    mock_mt5.ORDER_STATE_PARTIAL = 2
    mock_mt5.ORDER_STATE_REQUEST_CANCEL = 3
    mock_mt5.ORDER_STATE_REJECTED = 5
    mock_mt5.ORDER_STATE_EXPIRED = 6
    mock_mt5.ORDER_STATE_CANCELED = 7

    mock_modules = {
        "MetaTrader5": mock_mt5,
        "pytz": MagicMock(),
        "joblib": MagicMock(),
        "dateparser": MagicMock(),
        "apscheduler": MagicMock(),
        "apscheduler.triggers": MagicMock(),
        "apscheduler.triggers.cron": MagicMock(),
        "scipy": MagicMock(),
        "scipy.stats": MagicMock(),
        "sklearn": MagicMock(),
        "sklearn.metrics": MagicMock(),
    }

    with patch.dict(sys.modules, mock_modules):
        import pandas as pd
        from outputs.trader_mt5 import trader_mt5, App

        App.config = {
            "symbol": "BTCUSD",
            "freq": "1h",
            "mt5_account_id": None,
        }

        df = pd.DataFrame([{"close": 50000.0}])
        model = {"buy_signal_column": "buy", "sell_signal_column": "sell"}
        config = {"symbol": "BTCUSD", "freq": "1h"}
        model_store = MagicMock()

        with patch("outputs.trader_mt5.pandas_get_interval", return_value=("2025-01-01 00:00:00", "2025-01-01 01:00:00")), \
             patch("outputs.trader_mt5.now_timestamp", return_value=1700000000), \
             patch("outputs.trader_mt5.get_signal", return_value={"side": "NONE", "close_price": 50000.0, "close_time": 1700000000}), \
             patch("outputs.trader_mt5.update_order_status", new_callable=AsyncMock, return_value=4), \
             patch("outputs.trader_mt5.update_account_balance", new_callable=AsyncMock):

            # Test SELLING -> SOLD transition on FILLED
            App.status = "SELLING"
            App.order = {"orderId": 101, "status": 4}
            asyncio.run(trader_mt5(df, model, config, model_store))
            assert App.status == "SOLD"

            # Test BUYING -> BOUGHT transition on FILLED
            App.status = "BUYING"
            App.order = {"orderId": 102, "status": 4}
            asyncio.run(trader_mt5(df, model, config, model_store))
            assert App.status == "BOUGHT"


def test_analyzer_feature_and_signal_generation():
    import pandas as pd
    from common.analyzer import Analyzer

    config = {
        "symbol": "BTCUSDT",
        "freq": "1min",
        "time_column": "timestamp",
        "predict_length": 10,
        "features_horizon": 5,
        "data_sources": [{"folder": "BTCUSDT", "column_prefix": ""}],
        "train_features": ["close"],
        "feature_sets": [
            {
                "generator": "itbstats",
                "config": {"columns": "close", "functions": ["mean"], "windows": [5]},
                "feature_prefix": "feat",
            }
        ],
        "train_feature_sets": [],
        "signal_sets": [
            {
                "generator": "threshold_rule",
                "config": {
                    "columns": "close",
                    "names": ["buy_sig", "sell_sig"],
                    "parameters": {"buy_signal_threshold": 100.0, "sell_signal_threshold": 50.0},
                },
            }
        ],
    }

    model_store = MagicMock()
    analyzer = Analyzer(config, model_store)

    dt_index = pd.date_range("2025-01-01 00:00:00", periods=20, freq="1min", tz="UTC")
    df_raw = pd.DataFrame(
        {
            "timestamp": dt_index,
            "open": 100.0,
            "high": 105.0,
            "low": 95.0,
            "close": 102.0,
            "volume": 1000.0,
        }
    )

    analyzer.append_data({"BTCUSDT": df_raw})
    assert len(analyzer.df) == 20
    assert analyzer.dirty_records != 0

    analyzer.analyze()

    assert analyzer.dirty_records == 0
    assert "buy_sig" in analyzer.df.columns
    assert "sell_sig" in analyzer.df.columns
    assert bool(analyzer.df["buy_sig"].iloc[-1]) is True
    assert bool(analyzer.df["sell_sig"].iloc[-1]) is False
