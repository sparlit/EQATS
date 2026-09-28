"""
Unit tests for Phil Self-Improving Trader Engine.
Target Integration: bennyjo/phil
Magic Number: 9100087
"""

from datetime import UTC, datetime, timezone

import pytest

from institutional_integrations.phil_self_improving_trader_engine import (
    MAGIC_NUMBER_PHIL,
    BrierEvaluationResult,
    PhilSelfImprovingTraderBrokerAdapter,
    PhilSelfImprovingTraderEngine,
    PredictionMarketQuote,
    StrategyMutationRule,
    is_ist_market_open,
    round_tick_005,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
)


def test_magic_number_assignment():
    assert MAGIC_NUMBER_PHIL == 9100087


def test_round_tick_005():
    assert round_tick_005(100.02) == 100.00
    assert round_tick_005(100.03) == 100.05
    assert round_tick_005(100.08) == 100.10


def test_ist_market_open():
    dt_weekday_open = datetime(2026, 3, 30, 10, 0, 0, tzinfo=UTC)  # Monday 15:30 IST / 10:00 UTC
    assert isinstance(is_ist_market_open(dt_weekday_open), bool)


def test_brier_score_calculation():
    engine = PhilSelfImprovingTraderEngine()
    # Forecast = 0.8, Actual = 1.0 -> (0.8 - 1.0)^2 = 0.04
    score_yes = engine.calculate_brier_score(0.8, 1.0)
    assert pytest.approx(score_yes, 0.001) == 0.04

    # Forecast = 0.8, Actual = 0.0 -> (0.8 - 0.0)^2 = 0.64
    score_no = engine.calculate_brier_score(0.8, 0.0)
    assert pytest.approx(score_no, 0.001) == 0.64


def test_screen_prediction_markets():
    engine = PhilSelfImprovingTraderEngine(min_resolution_minutes=20.0)

    quotes = [
        PredictionMarketQuote(
            market_id="m1",
            category="earnings",
            symbol="INFY_EARNINGS_BEAT",
            yes_ask=0.40,
            yes_bid=0.38,
            no_ask=0.60,
            no_bid=0.58,
            estimated_prob=0.70,  # 0.70 - 0.40 = 0.30 edge
            time_to_resolution_minutes=120.0,
        ),
        PredictionMarketQuote(
            market_id="m2",
            category="crypto_coinflip",  # should be filtered
            symbol="BTC_10MIN_FLIP",
            yes_ask=0.50,
            yes_bid=0.49,
            no_ask=0.50,
            no_bid=0.49,
            estimated_prob=0.80,
            time_to_resolution_minutes=60.0,
        ),
        PredictionMarketQuote(
            market_id="m3",
            category="macro",
            symbol="RBI_RATE_CUT",
            yes_ask=0.80,
            yes_bid=0.78,
            no_ask=0.20,
            no_bid=0.18,
            estimated_prob=0.82,  # edge = 0.02 (< min_div 0.05)
            time_to_resolution_minutes=300.0,
        ),
    ]

    screened = engine.screen_prediction_markets(quotes)
    assert len(screened) == 1
    assert screened[0]["market_id"] == "m1"
    assert screened[0]["target_outcome"] == "YES"
    assert pytest.approx(screened[0]["probability_edge"], 0.01) == 0.30


def test_evaluate_brier_delta():
    engine = PhilSelfImprovingTraderEngine()

    quote = PredictionMarketQuote(
        market_id="m1",
        category="macro",
        symbol="FED_HIKE",
        yes_ask=0.60,
        yes_bid=0.58,
        no_ask=0.40,
        no_bid=0.38,
        estimated_prob=0.85,
        time_to_resolution_minutes=120.0,
    )

    summary = engine.evaluate_brier_delta([(quote, 1.0)])
    assert summary["total_evaluations"] == 1
    assert summary["agent_outperformed"] is True
    assert summary["overall_brier_delta"] > 0


def test_retrospective_mutation():
    engine = PhilSelfImprovingTraderEngine()

    brier_summary = {
        "evaluations": [
            BrierEvaluationResult(
                market_id="m1",
                category="earnings",
                estimated_prob=0.70,
                actual_outcome=0.0,
                market_price_paid=0.30,
                agent_brier=0.49,
                market_brier=0.09,
                brier_delta=-0.40,  # Agent underperformed heavily
            )
        ]
    }

    rules = [
        StrategyMutationRule(
            rule_id="r1",
            category="earnings",
            min_prob_divergence=0.05,
            max_bet_cap=10.0,
            min_brier_advantage=0.01,
            active=True,
        )
    ]

    updated_rules = engine.evaluate_retrospective_mutation(brier_summary, rules)
    assert updated_rules[0].min_prob_divergence > 0.05
    assert updated_rules[0].mutations_applied == 1


def test_twin_execution_routing():
    engine = PhilSelfImprovingTraderEngine(max_paper_bet_cap=10.0, max_real_twin_cap=1.0)

    exec_res = engine.route_twin_execution(
        market_id="m1",
        outcome_target="YES",
        estimated_prob=0.75,
        market_price=0.50,
        bankroll=1000.0,
        is_real_enabled=True,
    )

    assert exec_res.execution_status == "EXECUTED_TWIN_SUCCESS"
    assert exec_res.paper_price == 0.50
    assert exec_res.real_executed is True
    assert exec_res.real_price == 0.50


def test_broker_adapter_integration():
    adapter_cls = IndianBrokerPluginRegistry._registry.get("PHIL_SELF_IMPROVING_TRADER")
    assert adapter_cls is not None

    adapter = adapter_cls()
    assert adapter.connect() is True
    assert adapter.is_connected() is True

    req = SEBIOrderRequest(
        symbol="INFY_EARNINGS",
        exchange="NSE",
        order_type="BUY",
        quantity=10,
        price=0.50,
        product="CNC",
    )

    resp = adapter.execute_order(req)
    assert resp.success is True
    assert resp.status == "EXECUTED_TWIN_SUCCESS"
    assert adapter.disconnect() is True
    assert adapter.is_connected() is False
