"""Tests for MT5Connector methods verifying proper interaction with self.mt5."""

from unittest.mock import MagicMock

import pytest

import connector


class TestMT5ConnectorOptimization:
    @pytest.fixture
    def mt5_connector(self):
        conn = connector.MT5Connector(demo_only=True)
        conn.mt5 = MagicMock()
        return conn

    def test_get_history_with_connected_mt5(self, mt5_connector):
        mt5_connector.mt5.TIMEFRAME_M1 = 1
        mt5_connector.mt5.copy_rates_from_pos.return_value = [
            {"open": 1.12, "high": 1.15, "low": 1.10, "close": 1.14}
        ]
        history = mt5_connector.get_history("EURUSD", 1)
        assert len(history) == 1
        assert history[0]["open"] == 1.12
        assert history[0]["close"] == 1.14
        mt5_connector.mt5.copy_rates_from_pos.assert_called_once_with("EURUSD", 1, 0, 1)

    def test_get_history_without_mt5(self):
        conn = connector.MT5Connector(demo_only=True)
        conn.mt5 = None
        history = conn.get_history("EURUSD", 3)
        assert len(history) == 3
        assert history[0]["open"] == 1.1

    def test_get_historical_ticks_with_connected_mt5(self, mt5_connector):
        mt5_connector.mt5.COPY_TICKS_ALL = 1
        tick_mock = MagicMock()
        tick_mock.bid = 1.1234
        tick_mock.ask = 1.1236
        tick_mock.volume = 50
        mt5_connector.mt5.copy_ticks_from.return_value = [tick_mock]

        ticks = mt5_connector.get_historical_ticks("EURUSD", count=1)
        assert len(ticks) == 1
        assert ticks[0]["bid"] == 1.1234
        assert ticks[0]["ask"] == 1.1236
        assert ticks[0]["volume"] == 50
        mt5_connector.mt5.copy_ticks_from.assert_called_once()

    def test_get_open_orders_with_connected_mt5(self, mt5_connector):
        mt5_connector.mt5.POSITION_TYPE_BUY = 0
        pos_mock = MagicMock()
        pos_mock.magic = 998822
        pos_mock.type = 0
        pos_mock.ticket = 12345
        pos_mock.symbol = "EURUSD"
        pos_mock.price_open = 1.1200
        pos_mock.sl = 1.1150
        pos_mock.tp = 1.1300
        pos_mock.volume = 0.5
        pos_mock.profit = 25.0
        mt5_connector.mt5.positions_get.return_value = [pos_mock]

        orders = mt5_connector.get_open_orders()
        assert len(orders) == 1
        assert orders[0]["ticket"] == "12345"
        assert orders[0]["direction"] == "BUY"
        assert orders[0]["profit"] == 25.0

    def test_close_order_with_connected_mt5(self, mt5_connector):
        mt5_connector.mt5.TRADE_RETCODE_DONE = 10009
        mt5_connector.mt5.ORDER_TYPE_SELL = 1
        mt5_connector.mt5.TRADE_ACTION_DEAL = 1
        mt5_connector.mt5.ORDER_TIME_GTC = 0
        mt5_connector.mt5.ORDER_FILLING_IOC = 1

        mt5_connector.get_open_orders = MagicMock(return_value=[
            {
                "ticket": "999",
                "symbol": "EURUSD",
                "lot_size": 1.0,
                "direction": "BUY",
                "open_price": 1.1000,
            }
        ])
        mt5_connector.get_current_price = MagicMock(return_value={"bid": 1.1050, "ask": 1.1052})
        order_res = MagicMock()
        order_res.retcode = 10009
        order_res.price = 1.1050
        mt5_connector.mt5.order_send.return_value = order_res

        result = mt5_connector.close_order(ticket="999", reason="TEST_CLOSE")
        assert result["success"] is True
        assert result["price"] == 1.1050
        assert pytest.approx(result["profit"], rel=1e-5) == 500.0
