# codespell:ignore MIS,IST
"""
Unit and Integration Tests for Newly Discovered Repositories (Repos 002, 005, 016, 017).
Validates Hyperliquid Rust Bot, BSC Volume Bundler, Rig Solana Trader, and Jarvis Trading engines.
"""

import pytest
from src.institutional_integrations import (
    MAGIC_NUMBER_BSC_VOLUME_BUNDLER,
    MAGIC_NUMBER_HYPERLIQUID_RUST_BOT,
    MAGIC_NUMBER_JARVIS_TRADING,
    MAGIC_NUMBER_RIG_SOLANA_TRADER,
    BSCVolumeBundlerAdapter,
    BSCVolumeBundlerStrategy,
    HyperliquidRustBotAdapter,
    HyperliquidRustBotStrategy,
    JarvisTradingAdapter,
    JarvisTradingStrategy,
    RigSolanaTraderAdapter,
    RigSolanaTraderStrategy,
)
from src.institutional_integrations.sebi_broker_adapter import SEBIOrderRequest


def test_hyperliquid_rust_bot_engine() -> None:
    strat = HyperliquidRustBotStrategy(symbol="BTC", style="Scalp", risk="High", stance="Neutral")
    bars = [{"close": 100 + i, "high": 102 + i, "low": 98 + i} for i in range(25)]
    res = strat.evaluate_strategy(bars)
    assert res["symbol"] == "BTC"
    assert res["decision"] in ["BUY", "SELL", "HOLD"]
    assert res["magic_number"] == MAGIC_NUMBER_HYPERLIQUID_RUST_BOT

    adapter = HyperliquidRustBotAdapter()
    assert adapter.connect() is True
    req = SEBIOrderRequest(symbol="BTC", order_type="BUY", quantity=1, price=100.0)
    resp = adapter.execute_order(req)
    assert resp.success is True
    assert resp.raw_response["magic_number"] == MAGIC_NUMBER_HYPERLIQUID_RUST_BOT


def test_bsc_volume_bundler_engine() -> None:
    strat = BSCVolumeBundlerStrategy(symbol="BNB", sell_percentage=0.98)
    # Enforces max 95% sell (5% buffer retention)
    assert strat.sell_percentage <= 0.95
    dist = strat.calculate_bundle_distribution(total_bnb=1.0, num_wallets=4)
    assert len(dist) == 4
    assert abs(sum(dist) - 1.0) < 0.05

    bars = [{"close": 500.0 + i} for i in range(10)]
    res = strat.evaluate_strategy(bars, wallet_balances=[0.05, 0.05, 0.05])
    assert res["decision"] == "BUY"
    assert res["inventory_buffer_pct"] == 5.0
    assert res["magic_number"] == MAGIC_NUMBER_BSC_VOLUME_BUNDLER

    adapter = BSCVolumeBundlerAdapter()
    assert adapter.connect() is True
    req = SEBIOrderRequest(symbol="BNB", order_type="BUY", quantity=10, price=500.0)
    resp = adapter.execute_order(req)
    assert resp.success is True
    assert resp.raw_response["magic_number"] == MAGIC_NUMBER_BSC_VOLUME_BUNDLER


def test_rig_solana_trader_engine() -> None:
    strat = RigSolanaTraderStrategy(symbol="SOL", min_volume_ratio=1.2)
    bars = [{"close": 1500.0 + i} for i in range(10)]

    # Stoic risk check: market cap low -> HOLD
    res_hold = strat.evaluate_strategy(bars, market_cap=5000.0)
    assert res_hold["decision"] == "HOLD"

    # Stoic buy consensus
    res_buy = strat.evaluate_strategy(bars, market_cap=50000.0, buy_volume_4h=200.0, sell_volume_4h=100.0)
    assert res_buy["decision"] == "BUY"
    assert res_buy["sl"] < 1509.0
    assert res_buy["tp"] > 1509.0
    assert res_buy["magic_number"] == MAGIC_NUMBER_RIG_SOLANA_TRADER

    adapter = RigSolanaTraderAdapter()
    assert adapter.connect() is True
    req = SEBIOrderRequest(symbol="SOL", order_type="BUY", quantity=5, price=1500.0)
    resp = adapter.execute_order(req)
    assert resp.success is True
    assert resp.raw_response["magic_number"] == MAGIC_NUMBER_RIG_SOLANA_TRADER


def test_jarvis_trading_engine() -> None:
    strat = JarvisTradingStrategy(symbol="NIFTY", min_composite_score=60.0, regime="BULL")
    score = strat.calculate_composite_score(80, 80, 80, 80, 80)
    assert score == 80.0

    bars = [
        {"close": 21900.0, "high": 21950.0, "low": 21850.0, "volume": 1000},
        {"close": 22000.0, "high": 22050.0, "low": 21950.0, "volume": 2000},
    ]
    res = strat.evaluate_strategy(bars, benchmark_close=22000.0, benchmark_prev_close=21900.0)
    assert res["decision"] == "BUY"
    assert res["score"] >= 60.0
    assert res["magic_number"] == MAGIC_NUMBER_JARVIS_TRADING

    adapter = JarvisTradingAdapter()
    assert adapter.connect() is True
    req = SEBIOrderRequest(symbol="NIFTY", order_type="BUY", quantity=20, price=22000.0)
    resp = adapter.execute_order(req)
    assert resp.success is True
    assert resp.raw_response["magic_number"] == MAGIC_NUMBER_JARVIS_TRADING
