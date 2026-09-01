"""
Unit and Integration Tests for Quant Backtest Pro Engine.
"""
from typing import Any
import pytest
from institutional_integrations.quant_backtest_pro_engine import MultiAssetMathEngine, HighPrecisionOrderMatchingEngine, SymbolConfig, Candle, PositionSide

def test_multi_asset_math_pnl_and_margin() -> None:
    cfg = SymbolConfig(symbol='EURUSD', contract_size=100000.0, leverage=100.0, commission_per_lot=7.0)
    pnl_buy = MultiAssetMathEngine.calculate_pnl(cfg, PositionSide.BUY, 1.0, 1.08, 1.085)
    assert abs(pnl_buy - 500.0) < 0.0001
    pnl_sell = MultiAssetMathEngine.calculate_pnl(cfg, PositionSide.SELL, 1.0, 1.085, 1.08)
    assert abs(pnl_sell - 500.0) < 0.0001
    margin = MultiAssetMathEngine.calculate_required_margin(cfg, 1.0, 1.08)
    assert abs(margin - 1080.0) < 0.0001
    commission = MultiAssetMathEngine.calculate_commission(cfg, 2.0)
    assert commission == 14.0

def test_order_matching_engine_lifecycle() -> None:
    engine = HighPrecisionOrderMatchingEngine(initial_balance=100000.0)
    pos = engine.open_market_position(side=PositionSide.BUY, lot_size=1.0, current_price=1.08, stop_loss=1.075, take_profit=1.09, trailing_stop_pips=20.0)
    assert len(engine.open_positions) == 1
    assert engine.balance == 99993.0
    assert engine.set_breakeven(pos.position_id, buffer_pips=2.0) is True
    assert pos.stop_loss == pos.entry_price + 0.0002
    assert engine.partial_close_position(pos.position_id, 50.0, 1.085, 1000.0) is True
    assert pos.lot_size == 0.5
    assert len(engine.closed_positions) == 1
    assert abs(engine.closed_positions[0].realized_pnl - 245.0) < 0.0001
    candle = Candle(timestamp=2000.0, open=1.085, high=1.091, low=1.084, close=1.089)
    engine.process_candle(candle)
    assert len(engine.open_positions) == 0
    assert len(engine.closed_positions) == 2
