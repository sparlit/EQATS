"""
Unit tests for Hummingbot Suite integration.
Verifies AvellanedaStoikovMarketMakingEngine, PureMarketMakingInventorySkewEngine, and CrossExchangeArbitrageEngine.
"""
from typing import Any
import pytest
from institutional_integrations.hummingbot_suite import AvellanedaStoikovMarketMakingEngine, CrossExchangeArbitrageEngine, PureMarketMakingInventorySkewEngine

def test_avellaneda_stoikov_market_making() -> None:
    engine = AvellanedaStoikovMarketMakingEngine()
    quote = engine.compute_quotes(mid_price=100.0, inventory=5.0, target_inventory=0.0, volatility=0.02, risk_aversion=0.1)
    assert quote.reservation_price < 100.0
    assert quote.bid_price < quote.reservation_price
    assert quote.ask_price > quote.reservation_price
    assert quote.bid_price < quote.ask_price

def test_pure_market_making_inventory_skew() -> None:
    engine = PureMarketMakingInventorySkewEngine()
    spreads = engine.compute_skewed_spreads(base_bid_spread=0.005, base_ask_spread=0.005, current_inventory_pct=0.8, target_inventory_pct=0.5)
    assert spreads.bid_spread > 0.005
    assert spreads.ask_spread < 0.005
    assert spreads.skew_factor > 0.0

def test_cross_exchange_arbitrage() -> None:
    engine = CrossExchangeArbitrageEngine()
    opp = engine.evaluate_arbitrage(maker_ask=100.0, maker_bid=105.0, taker_ask=101.0, taker_bid=99.0, maker_fee_pct=0.001, taker_fee_pct=0.001)
    assert opp.opportunity_found is True
    assert opp.direction == 'TAKER_BUY_MAKER_SELL'
    assert opp.net_profit_pct > 2.0
    assert opp.buy_price == 101.0
    assert opp.sell_price == 105.0
