"""
Unit and Integration Tests for Quant Backtest Pro Engine.
"""

import pytest

from institutional_integrations.quant_backtest_pro_engine import (
    MultiAssetMathEngine,
    HighPrecisionOrderMatchingEngine,
    SymbolConfig,
    Candle,
    PositionSide,
)


def test_multi_asset_math_pnl_and_margin():
    cfg = SymbolConfig(symbol="EURUSD", contract_size=100000.0, leverage=100.0, commission_per_lot=7.0)

    pnl_buy = MultiAssetMathEngine.calculate_pnl(cfg, PositionSide.BUY, 1.0, 1.0800, 1.0850)
    assert abs(pnl_buy - 500.0) < 1e-4

    pnl_sell = MultiAssetMathEngine.calculate_pnl(cfg, PositionSide.SELL, 1.0, 1.0850, 1.0800)
    assert abs(pnl_sell - 500.0) < 1e-4

    margin = MultiAssetMathEngine.calculate_required_margin(cfg, 1.0, 1.0800)
    assert abs(margin - 1080.0) < 1e-4  # (100k * 1.08) / 100

    commission = MultiAssetMathEngine.calculate_commission(cfg, 2.0)
    assert commission == 14.0  # 2 * 7.0


def test_order_matching_engine_lifecycle():
    engine = HighPrecisionOrderMatchingEngine(initial_balance=100000.0)

    # 1. Open Position
    pos = engine.open_market_position(
        side=PositionSide.BUY,
        lot_size=1.0,
        current_price=1.0800,
        stop_loss=1.0750,
        take_profit=1.0900,
        trailing_stop_pips=20.0,
    )
    assert len(engine.open_positions) == 1
    assert engine.balance == 99993.0  # 100,000 - $7 commission

    # 2. Breakeven set
    assert engine.set_breakeven(pos.position_id, buffer_pips=2.0) is True
    assert pos.stop_loss == pos.entry_price + 0.0002

    # 3. Partial Close 50%
    assert engine.partial_close_position(pos.position_id, 50.0, 1.0850, 1000.0) is True
    assert pos.lot_size == 0.50
    assert len(engine.closed_positions) == 1
    assert abs(engine.closed_positions[0].realized_pnl - 245.0) < 1e-4

    # 4. Candle Processing -> Take Profit hit
    candle = Candle(timestamp=2000.0, open=1.0850, high=1.0910, low=1.0840, close=1.0890)
    engine.process_candle(candle)

    assert len(engine.open_positions) == 0
    assert len(engine.closed_positions) == 2
