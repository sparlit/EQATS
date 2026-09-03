"""
Unit and Integration Tests for Ingestion Blueprint Adapted Quantitative Modules.
Verifies RQAlpha event engine, Polymarket/Kalshi prediction market arbitrage,
High-Frequency L3 matching orderbook, and Option Strategy Greeks engine.
"""

import time
from typing import Any

import pytest

from institutional_integrations.hft_matching_orderbook import BookSide, HighFrequencyMatchingOrderBook, LimitOrder
from institutional_integrations.option_strat_greeks_engine import (
    OptionLeg,
    OptionStratGreeksEngine,
)
from institutional_integrations.option_strat_greeks_engine import (
    OptionType as StratOptionType,
)
from institutional_integrations.polymarket_kalshi_arb import MarketQuote, PolymarketKalshiArbEngine
from institutional_integrations.rqalpha_event_engine import Bar, EventOrder, OrderSide, OrderType, RQAlphaEventEngine


def test_rqalpha_event_engine() -> None:
    engine = RQAlphaEventEngine(initial_capital=100000.0)
    bar1 = Bar(symbol="EURUSD", timestamp=time.time(), open=1.08, high=1.085, low=1.079, close=1.082, volume=1000.0)
    order = EventOrder(
        order_id="ORD001",
        symbol="EURUSD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=1000.0,
        price=1.082,
    )
    assert engine.submit_order(order) is True
    filled = engine.process_bar(bar1, atr_slippage_pips=0.0001)
    assert len(filled) == 1
    assert filled[0].status == "FILLED"
    assert filled[0].avg_fill_price == pytest.approx(1.0821)
    summary = engine.get_portfolio_summary()
    assert summary["open_positions_count"] == 1
    assert summary["cash"] < 100000.0


def test_polymarket_kalshi_arb_engine() -> None:
    arb_engine = PolymarketKalshiArbEngine(min_net_profit_threshold=0.01)
    poly_quote = MarketQuote(
        venue="POLYMARKET",
        market_id="FED_RATE_CUT",
        yes_bid=0.6,
        yes_ask=0.62,
        no_bid=0.35,
        no_ask=0.37,
        yes_ask_depth=5000.0,
        no_ask_depth=5000.0,
    )
    kalshi_quote = MarketQuote(
        venue="KALSHI",
        market_id="FED_RATE_CUT",
        yes_bid=0.68,
        yes_ask=0.7,
        no_bid=0.28,
        no_ask=0.3,
        yes_ask_depth=4000.0,
        no_ask_depth=4000.0,
    )
    opps = arb_engine.evaluate_cross_venue_arbitrage(poly_quote, kalshi_quote)
    assert len(opps) >= 1
    yes_arb = [o for o in opps if o.buy_venue == "POLYMARKET" and o.sell_venue == "KALSHI"]
    assert len(yes_arb) == 1
    assert yes_arb[0].net_profit_per_share > 0.01
    assert yes_arb[0].expected_net_profit > 0.0


def test_hft_matching_orderbook() -> None:
    ob = HighFrequencyMatchingOrderBook(symbol="BTCUSD")
    ask_order = LimitOrder(
        order_id="ASK001", symbol="BTCUSD", side=BookSide.ASK, price=50000.0, quantity=2.0, timestamp_ns=time.time_ns(),
    )
    fills1 = ob.add_limit_order(ask_order)
    assert len(fills1) == 0
    bid_order = LimitOrder(
        order_id="BID001", symbol="BTCUSD", side=BookSide.BID, price=50000.0, quantity=1.0, timestamp_ns=time.time_ns(),
    )
    fills2 = ob.add_limit_order(bid_order)
    assert len(fills2) == 1
    assert fills2[0]["match_qty"] == 1.0
    assert fills2[0]["match_price"] == 50000.0
    queue_info = ob.estimate_queue_position("ASK001")
    assert queue_info is not None
    assert queue_info.queue_position_ahead_qty == 0.0
    depth = ob.get_L2_depth()
    assert len(depth["asks"]) == 1
    assert depth["asks"][0]["volume"] == 1.0


def test_option_strat_greeks_engine() -> None:
    greeks_engine = OptionStratGreeksEngine(risk_free_rate=0.05)
    greeks = greeks_engine.calculate_greeks(
        spot=100.0, strike=100.0, time_to_expiry=0.5, iv=0.2, option_type=StratOptionType.CALL,
    )
    assert greeks.price > 0.0
    assert 0.4 < greeks.delta < 0.6
    assert greeks.gamma > 0.0
    assert greeks.vega > 0.0
    solved_iv = greeks_engine.solve_implied_volatility(
        target_market_price=greeks.price, spot=100.0, strike=100.0, time_to_expiry=0.5, option_type=StratOptionType.CALL,
    )
    assert solved_iv == pytest.approx(0.2, abs=0.001)
    legs = [
        OptionLeg(
            strike=100.0,
            time_to_expiry_years=0.5,
            option_type=StratOptionType.CALL,
            implied_volatility=0.2,
            quantity=1.0,
        ),
        OptionLeg(
            strike=100.0,
            time_to_expiry_years=0.5,
            option_type=StratOptionType.PUT,
            implied_volatility=0.2,
            quantity=1.0,
        ),
    ]
    strat_metrics = greeks_engine.evaluate_multi_leg_strategy(spot=100.0, legs=legs)
    assert strat_metrics["net_premium_cost"] > 0.0
    assert strat_metrics["net_delta"] == pytest.approx(0.195, abs=0.05)
