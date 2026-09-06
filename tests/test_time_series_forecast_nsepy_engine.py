"""
Tests for Time Series Forecast NSEPy Engine Integration Module
"""

import pytest
from unittest.mock import patch

from institutional_integrations.time_series_forecast_nsepy_engine import (
    TimeSeriesForecastNSEPyEngine,
    TimeSeriesForecastNSEPyBrokerAdapter,
    round_tick_005,
    MAGIC_NUMBER_TIME_SERIES_FORECAST_NSEPY,
)
from institutional_integrations.sebi_broker_adapter import (
    SEBIOrderRequest,
    IndianBrokerPluginRegistry,
)


def test_time_series_forecasting():
    engine = TimeSeriesForecastNSEPyEngine(ar_lags=3)
    assert engine.magic_number == MAGIC_NUMBER_TIME_SERIES_FORECAST_NSEPY

    prices = [100.0, 102.0, 104.0, 106.0]
    res = engine.forecast_next_close(prices)
    assert res["latest_price"] == 106.00
    assert res["forecast_price"] > 0.0
    assert "signal" in res


def test_time_series_forecast_nsepy_broker_adapter():
    adapter = TimeSeriesForecastNSEPyBrokerAdapter()
    assert IndianBrokerPluginRegistry.get_adapter_class("TIME_SERIES_FORECAST_NSEPY") == TimeSeriesForecastNSEPyBrokerAdapter

    req = SEBIOrderRequest(
        symbol="TCS",
        quantity=10,
        price=4100.02,
        order_type="BUY",
        product="CNC",
        exchange="NSE",
        order_kind="LIMIT",
    )

    res_unauth = adapter.execute_order(req)
    assert not res_unauth.success

    adapter.connect()

    with patch("institutional_integrations.time_series_forecast_nsepy_engine.is_ist_market_open", return_value=True):
        res = adapter.execute_order(req)
        assert res.success
        assert res.status == "FILLED"
        assert res.price == 4100.00
        assert res.ticket.startswith("TSF-")
