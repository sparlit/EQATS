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


def test_update_trade_status_single_open_order():
    mock_mt5 = MagicMock()
    mock_mt5.__author__ = "MetaTrader 5 Ltd."
    mock_mt5.__version__ = "5.0.45"
    mock_mt5.ORDER_TYPE_SELL_LIMIT = 1
    mock_mt5.ORDER_TYPE_SELL = 2
    mock_mt5.ORDER_TYPE_BUY_LIMIT = 0
    mock_mt5.ORDER_TYPE_BUY = 3
    mock_mt5.ORDER_TYPE_OTHER = 99

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
        from outputs.trader_mt5 import update_trade_status, App

        App.config = {"symbol": "BTCUSD"}

        # Sell Limit Order
        order_sell_limit = MagicMock(type=mock_mt5.ORDER_TYPE_SELL_LIMIT)
        mock_mt5.orders_get.return_value = (order_sell_limit,)
        asyncio.run(update_trade_status())
        assert App.status == "SELLING"

        # Sell Market Order
        order_sell = MagicMock(type=mock_mt5.ORDER_TYPE_SELL)
        mock_mt5.orders_get.return_value = (order_sell,)
        asyncio.run(update_trade_status())
        assert App.status == "SELLING"

        # Buy Limit Order
        order_buy_limit = MagicMock(type=mock_mt5.ORDER_TYPE_BUY_LIMIT)
        mock_mt5.orders_get.return_value = (order_buy_limit,)
        asyncio.run(update_trade_status())
        assert App.status == "BUYING"

        # Buy Market Order
        order_buy = MagicMock(type=mock_mt5.ORDER_TYPE_BUY)
        mock_mt5.orders_get.return_value = (order_buy,)
        asyncio.run(update_trade_status())
        assert App.status == "BUYING"

        # Invalid Order Type
        order_invalid = MagicMock(type=99)
        mock_mt5.orders_get.return_value = (order_invalid,)
        res = asyncio.run(update_trade_status())
        assert res is None
