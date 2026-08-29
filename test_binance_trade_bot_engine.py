"""
Unit and Integration Tests for Binance Trade Bot Bridge Scouting Engine.
"""

import pytest

from institutional_integrations.binance_trade_bot_engine import (
    BridgeCoinScoutEngine,
)


def test_binance_trade_bot_coin_jump_evaluation():
    engine = BridgeCoinScoutEngine(bridge_coin="USDT", min_jump_profit_pct=2.0)
    engine.set_initial_threshold("ETH", "SOL", 10.0)  # Initial ratio ETH / SOL = 10.0

    # 1. Ratio increases to 11.0 (+10% > +2% min) -> Jump Triggered
    dec = engine.evaluate_coin_jump("ETH", "SOL", 2200.0, 200.0)
    assert dec.should_jump is True
    assert dec.expected_profit_pct == 10.0
    assert dec.current_ratio == 11.0

    # 2. Ratio increases to 10.1 (+1% < +2% min) -> No Jump
    dec_below = engine.evaluate_coin_jump("ETH", "SOL", 2020.0, 200.0)
    assert dec_below.should_jump is False


def test_binance_trade_bot_scout_best_jump():
    engine = BridgeCoinScoutEngine(bridge_coin="USDT", min_jump_profit_pct=1.0)
    engine.set_initial_threshold("BTC", "ETH", 15.0)
    engine.set_initial_threshold("BTC", "SOL", 300.0)

    # Current BTC = $60,000, ETH = $3,000 (Ratio 20.0, +33.3% profit vs 15.0)
    # Current SOL = $200 (Ratio 300.0, 0% profit vs 300.0)
    candidates = {"ETH": 3000.0, "SOL": 200.0}

    best = engine.scout_best_jump("BTC", 60000.0, candidates)
    assert best is not None
    assert best.to_coin == "ETH"
    assert best.expected_profit_pct > 30.0
