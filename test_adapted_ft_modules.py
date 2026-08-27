"""
Integration unit tests for adapted Fincept Terminal modules in institutional_integrations:
 - options_derivatives_engine.py
 - finagent_hedgefund_swarm.py
 - extended_market_connectors.py
 - quant_portfolio_analytics.py
 - alpha_strategies_library.py
"""

import numpy as np

from institutional_integrations.options_derivatives_engine import (
    OptionsPricingEngine, GammaExposureAnalyzer, OptionStrategySimulator
)
from institutional_integrations.finagent_hedgefund_swarm import HedgeFundSwarmOrchestrator
from institutional_integrations.extended_market_connectors import ExtendedDataConnectors
from institutional_integrations.quant_portfolio_analytics import (
    PortfolioOptimizationEngine, QuantPerformanceMetrics
)
from institutional_integrations.alpha_strategies_library import AlphaStrategyLibrary


def test_options_pricing_and_greeks():
    spot = 100.0
    strike = 100.0
    T = 0.25
    r = 0.05
    vol = 0.20

    call_price = OptionsPricingEngine.black_scholes(spot, strike, T, r, vol, option_type="call")
    put_price = OptionsPricingEngine.black_scholes(spot, strike, T, r, vol, option_type="put")

    assert call_price > 0.0
    assert put_price > 0.0

    greeks = OptionsPricingEngine.calculate_greeks(spot, strike, T, r, vol, option_type="call")
    assert 0.4 < greeks["delta"] < 0.7
    assert greeks["gamma"] > 0.0
    assert greeks["vega"] > 0.0

    solved_iv = OptionsPricingEngine.implied_volatility(call_price, spot, strike, T, r, option_type="call")
    assert abs(solved_iv - vol) < 1e-3


def test_gamma_exposure_and_strategy_simulator():
    chain = [
        {"strike": 95.0, "type": "put", "open_interest": 500, "iv": 0.22, "expiry_days": 30},
        {"strike": 100.0, "type": "call", "open_interest": 1000, "iv": 0.20, "expiry_days": 30},
        {"strike": 105.0, "type": "call", "open_interest": 800, "iv": 0.18, "expiry_days": 30},
    ]

    gex_profile = GammaExposureAnalyzer.calculate_gex_profile(100.0, chain)
    assert "total_gex" in gex_profile
    assert gex_profile["regime"] in ["LONG_GAMMA_SUPPRESSION", "SHORT_GAMMA_VOLATILITY"]

    legs = [
        {"strike": 100.0, "type": "call", "action": "buy", "premium": 4.5, "qty": 1},
        {"strike": 100.0, "type": "put", "action": "buy", "premium": 3.5, "qty": 1}
    ]
    sim = OptionStrategySimulator.simulate_strategy_payoff(legs, (80.0, 120.0))
    assert sim["net_initial_cost"] == 800.0
    assert sim["max_profit"] > 0.0


def test_hedge_fund_swarm_orchestrator():
    swarm = HedgeFundSwarmOrchestrator()
    market_data = {"volatility": 0.015, "trend": 0.5, "spread": 0.0001}
    res = swarm.process_trading_opportunity("EURUSD", market_data, raw_signal=0.6)

    assert res["final_action"] in ["BUY", "SELL", "HOLD"]
    assert "committee_votes" in res

    analytics = swarm.get_swarm_analytics()
    assert analytics["total_deliberations"] == 1


def test_extended_data_connectors():
    ak_data = ExtendedDataConnectors.fetch_akshare_macro_china()
    assert len(ak_data) > 0

    sec_data = ExtendedDataConnectors.fetch_sec_edgar_filings("AAPL")
    assert sec_data["status"] == "SUCCESS"

    fred_data = ExtendedDataConnectors.fetch_fred_economic_series("FEDFUNDS")
    assert fred_data["status"] == "SUCCESS"

    crypto_data = ExtendedDataConnectors.fetch_crypto_defi_feed("BTC")
    assert crypto_data["status"] == "SUCCESS"

    poly_data = ExtendedDataConnectors.fetch_polymarket_events()
    assert len(poly_data) > 0


def test_quant_portfolio_analytics():
    np.random.seed(42)
    returns = np.random.normal(0.001, 0.015, (252, 4))

    mvo = PortfolioOptimizationEngine.optimize_mean_variance(returns)
    assert mvo["status"] == "SUCCESS"
    assert len(mvo["weights"]) == 4
    assert abs(sum(mvo["weights"]) - 1.0) < 1e-4

    rp = PortfolioOptimizationEngine.optimize_risk_parity(returns)
    assert rp["status"] == "SUCCESS"
    assert len(rp["weights"]) == 4

    metrics = QuantPerformanceMetrics.calculate_performance_summary(returns[:, 0])
    assert "sharpe_ratio" in metrics
    assert "sortino_ratio" in metrics
    assert "max_drawdown" in metrics


def test_alpha_strategies_library():
    universe = [
        {"symbol": "AAPL", "ebit": 100, "enterprise_value": 1000, "working_capital": 100, "fixed_assets": 100},
        {"symbol": "MSFT", "ebit": 120, "enterprise_value": 1000, "working_capital": 80, "fixed_assets": 80},
    ]

    magic = AlphaStrategyLibrary.greenblatt_magic_formula_alpha(universe)
    assert len(magic) == 2
    assert magic[0]["symbol"] == "MSFT"

    highs = np.array([100, 102, 104, 103, 105])
    lows = np.array([98, 99, 101, 100, 102])
    closes = np.array([99, 101, 103, 102, 104.5])
    dual = AlphaStrategyLibrary.vix_dual_thrust_alpha(highs, lows, closes)
    assert dual["signal"] in ["BUY", "SELL", "HOLD"]

    ibs = AlphaStrategyLibrary.global_equity_ibs_alpha(104.5, 105.0, 102.0)
    assert 0.0 <= ibs["ibs"] <= 1.0

    decay = AlphaStrategyLibrary.triple_leverage_decay_arbitrage(50.0, 45.0, 0.35)
    assert decay["signal"] in ["SHORT_BOTH_PAIR", "HOLD"]
