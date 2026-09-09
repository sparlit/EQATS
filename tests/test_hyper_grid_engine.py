"""
Unit tests for Hyper Grid Trading Engine (Repo 099 Adaptation)
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import pytest

from src.institutional_integrations.hyper_grid_engine import (
    HyperGridEngine,
    HyperGridConfig,
    HyperGridBrokerAdapter,
    round_tick_005,
    is_ist_market_open,
    MAGIC_NUMBER,
)
from src.institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
)


def test_round_tick_005():
    assert round_tick_005(100.02) == 100.00
    assert round_tick_005(100.03) == 100.05
    assert round_tick_005(100.076) == 100.10
    assert round_tick_005(-5.0) == 0.0


def test_is_ist_market_open():
    # Wednesday 10:30 AM IST -> 05:00 UTC
    wed_market = datetime(2025, 3, 5, 5, 0, tzinfo=timezone.utc)
    assert is_ist_market_open(wed_market) is True

    # Sunday 10:30 AM IST -> 05:00 UTC
    sun = datetime(2025, 3, 2, 5, 0, tzinfo=timezone.utc)
    assert is_ist_market_open(sun) is False


def test_hyper_grid_engine_arithmetic():
    config = HyperGridConfig(
        symbol="RELIANCE",
        lower_bound=100.0,
        upper_bound=200.0,
        num_grids=5,
        quantity_per_grid=2,
        geometric=False,
    )
    engine = HyperGridEngine(config)
    assert engine.magic_number == MAGIC_NUMBER
    assert len(engine.grid_levels) == 5

    # Prices should be 100, 125, 150, 175, 200
    prices = [lvl.price for lvl in engine.grid_levels]
    assert prices == [100.0, 125.0, 150.0, 175.0, 200.0]

    # Mid index is 2 -> levels 0, 1 are BUY, 2, 3, 4 are SELL
    types = [lvl.order_type for lvl in engine.grid_levels]
    assert types == ["BUY", "BUY", "SELL", "SELL", "SELL"]


def test_hyper_grid_engine_market_update():
    config = HyperGridConfig(
        symbol="TATAMOTORS",
        lower_bound=100.0,
        upper_bound=200.0,
        num_grids=5,
        quantity_per_grid=1,
    )
    engine = HyperGridEngine(config)

    # Market drops to 95 -> BUY levels at <= 95 trigger
    triggered = engine.update_market_price(95.0)
    assert len(triggered) == 2  # 100 and 125 level BUY orders
    assert all(lvl.status == "FILLED" for lvl in triggered)

    summary = engine.get_summary(current_price=110.0)
    assert summary.symbol == "TATAMOTORS"
    assert summary.filled_buy_levels == 2
    assert summary.active_levels == 3


def test_hyper_grid_broker_adapter_registration():
    cls = IndianBrokerPluginRegistry.get_adapter_class("HYPER_GRID")
    assert cls is HyperGridBrokerAdapter

    adapter = cls(api_key="test", api_secret="test")
    assert adapter.connect() is True
    assert adapter.is_connected() is True

    req = SEBIOrderRequest(
        symbol="NIFTY",
        exchange="NSE",
        order_type="BUY",
        quantity=50,
        price=24000.03,
        order_kind="LIMIT",
    )

    # Mock market open
    with patch("src.institutional_integrations.hyper_grid_engine.is_ist_market_open", return_value=True):
        res = adapter.execute_order(req)
        assert res.success is True
        assert res.status == "FILLED"
        assert res.price == 24000.05

    # Mock market closed
    with patch("src.institutional_integrations.hyper_grid_engine.is_ist_market_open", return_value=False):
        res_closed = adapter.execute_order(req)
        assert res_closed.success is False
        assert res_closed.status == "REJECTED"

    adapter.disconnect()
    assert adapter.is_connected() is False
