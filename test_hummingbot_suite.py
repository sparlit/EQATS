"""
Unit tests for Hummingbot Suite integration.
Verifies AvellanedaStoikovMarketMakingEngine, PureMarketMakingInventorySkewEngine, and CrossExchangeArbitrageEngine.
"""

import pytest
from institutional_integrations.hummingbot_suite import (
    AvellanedaStoikovMarketMakingEngine,
    CrossExchangeArbitrageEngine,
    PureMarketMakingInventorySkewEngine,
)


def test_avellaneda_stoikov_market_making():
    engine = AvellanedaStoikovMarketMakingEngine()

    quote = engine.compute_quotes(
        mid_price=100.0,
        inventory=5.0,
        target_inventory=0.0,
        volatility=0.02,
        risk_aversion=0.10,
    )

    # When holding positive inventory (5.0 units > 0.0 target), reservation price should shift down below mid price
    assert quote.reservation_price < 100.0
    assert quote.bid_price < quote.reservation_price
    assert quote.ask_price > quote.reservation_price
    assert quote.bid_price < quote.ask_price


def test_pure_market_making_inventory_skew():
    engine = PureMarketMakingInventorySkewEngine()

    spreads = engine.compute_skewed_spreads(
        base_bid_spread=0.005,
        base_ask_spread=0.005,
        current_inventory_pct=0.80,  # Over-inventoried
        target_inventory_pct=0.50,
    )

    # When over-inventoried, bid spread widens (to buy less) and ask spread narrows (to sell more)
    assert spreads.bid_spread > 0.005
    assert spreads.ask_spread < 0.005
    assert spreads.skew_factor > 0.0


def test_cross_exchange_arbitrage():
    engine = CrossExchangeArbitrageEngine()

    # Maker Ask: 100.0, Maker Bid: 105.0. Taker Ask: 101.0, Taker Bid: 99.0
    # Buy on Taker @ 101.0, Sell on Maker @ 105.0 -> Profit ~4%
    opp = engine.evaluate_arbitrage(
        maker_ask=100.0,
        maker_bid=105.0,
        taker_ask=101.0,
        taker_bid=99.0,
        maker_fee_pct=0.001,
        taker_fee_pct=0.001,
    )

    assert opp.opportunity_found is True
    assert opp.direction == "TAKER_BUY_MAKER_SELL"
    assert opp.net_profit_pct > 2.0
    assert opp.buy_price == 101.0
    assert opp.sell_price == 105.0
