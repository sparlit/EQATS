"""
Unit Tests for High-Frequency Microstructure, Dual-Timeframe Co-Integration, and Half-Kelly Position Sizing
"""

import pytest
from institutional_integrations.shoonya_option_chain_engine import ShoonyaOptionChainEngine
from institutional_integrations.nse_swing_scanner_engine import NSESwingScannerEngine
from institutional_integrations.indian_trading_skills_engine import IndianTradingSkillsEngine


def test_volume_imbalance_delta_and_spoofing_filter():
    engine = ShoonyaOptionChainEngine(max_imbalance_ratio=3.0, max_cancellation_rate_pct=80.0)

    # 1. Ask volume (3000) is 3x bid volume (1000) -> Block Long Entry
    vid = engine.calculate_volume_imbalance_delta(
        bid_depth_volumes=[200, 200, 200, 200, 200],
        ask_depth_volumes=[600, 600, 600, 600, 600]
    )
    assert vid["sell_wall_detected"] is True
    assert vid["action"] == "BLOCK_LONG_ENTRY"

    # 2. 85% cancellation rate -> Block Spoofed Liquidity
    spoof = engine.evaluate_order_cancellation_spoofing_filter(orders_created=100, orders_cancelled=85)
    assert spoof["spoofing_detected"] is True
    assert spoof["action"] == "BLOCK_SPOOFED_LIQUIDITY"


def test_dual_timeframe_cointegration_and_vix_atr_stop():
    engine = NSESwingScannerEngine()

    bars_5m = [{"close": 500.0 + i} for i in range(25)]
    bars_1d = [{"close": 500.0 + i} for i in range(25)]

    # 1. Both 5m and 1d bullish -> Cointegrated BULLISH signal
    cointeg = engine.validate_dual_timeframe_cointegration(bars_5m, bars_1d)
    assert cointeg["cointegrated"] is True
    assert cointeg["signal"] == "BULLISH"

    # 2. High VIX (24.0) -> ATR multiplier scales to 2.5x
    atr_stop = engine.calculate_dynamic_atr_stop(current_price=500.0, atr=10.0, india_vix=24.0, side="BUY")
    assert atr_stop["atr_multiplier"] == 2.50
    assert atr_stop["stop_loss_price"] == 475.0


def test_half_kelly_position_allocator():
    engine = IndianTradingSkillsEngine()

    # Win Rate = 60%, Win/Loss Ratio = 1.5 -> Full Kelly = 0.333, Half Kelly = 0.1667
    kelly = engine.calculate_half_kelly_position_size(
        account_equity=1000000.0, price=500.0, win_rate_pct=60.0, win_loss_ratio=1.5
    )

    assert kelly["half_kelly_fraction"] > 0.15
    assert kelly["quantity"] > 0
    assert kelly["allocated_capital"] > 150000.0
