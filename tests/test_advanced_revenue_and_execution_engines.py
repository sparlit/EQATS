"""
Unit Tests for Advanced Revenue Stability, Execution Slicing, SOR, and Strategy Demotion Engines
"""

import pytest
from institutional_integrations.nse_system_engine import NSESystemEngine
from institutional_integrations.nse_options_data_collector_engine import NSEOptionsDataCollectorEngine
from institutional_integrations.rust_matching_engine import OrderbookL2
from institutional_integrations.nse_bse_api_bshada_engine import NSEBSEApiEngine
from institutional_integrations.rust_finance_engine import RustFinanceEngine
from institutional_integrations.advanced_nse_momentum_engine import AdvancedNSEMomentumEngine
from institutional_integrations.barter_rs_engine import BarterRSEngine


def test_volatility_adjusted_position_size():
    engine = NSESystemEngine()

    # Low VIX (15.0) -> Normal Quantity (100)
    normal = engine.calculate_volatility_adjusted_position_size(100, india_vix=15.0, atr=5.0, price=500.0)
    assert normal["adjusted_quantity"] == 100
    assert normal["volatility_multiplier"] == 1.0

    # High VIX (26.0) -> Scaled Down Quantity (50)
    high_vix = engine.calculate_volatility_adjusted_position_size(100, india_vix=26.0, atr=5.0, price=500.0)
    assert high_vix["adjusted_quantity"] == 50
    assert high_vix["volatility_multiplier"] == 0.50


def test_premarket_gap_down_hedge_trigger():
    engine = NSEOptionsDataCollectorEngine()

    # Gap down of -4.0% -> Trigger Put Hedge
    hedge = engine.evaluate_premarket_gap_hedge_trigger(prev_close=500.0, iep_price=480.0, gap_down_threshold_pct=3.0)
    assert hedge["hedge_triggered"] is True
    assert hedge["recommended_action"] == "PLACE_PUT_HEDGE"

    # Flat open (0.0%) -> No Hedge
    flat = engine.evaluate_premarket_gap_hedge_trigger(prev_close=500.0, iep_price=500.0, gap_down_threshold_pct=3.0)
    assert flat["hedge_triggered"] is False
    assert flat["recommended_action"] == "NO_HEDGE"


def test_twap_micro_slice_execution():
    ob = OrderbookL2("RELIANCE")

    twap = ob.slice_order_twap(total_quantity=1000, num_slices=5, total_duration_seconds=100)
    assert len(twap["slices"]) == 5
    assert sum(s["slice_quantity"] for s in twap["slices"]) == 1000
    assert twap["interval_seconds"] == 20.0


def test_smart_order_router_sor():
    engine = NSEBSEApiEngine()

    # BUY order: BSE ask (499.0) < NSE ask (500.0) -> Select BSE, save 1.0 INR / share
    sor_buy = engine.route_smart_order_sor(
        symbol="INFY", side="BUY", quantity=100,
        nse_bid=499.50, nse_ask=500.00, bse_bid=499.50, bse_ask=499.00
    )
    assert sor_buy["selected_exchange"] == "BSE"
    assert sor_buy["execution_price"] == 499.00
    assert sor_buy["total_savings_inr"] == 100.00


def test_gamma_scalping_rebalance():
    engine = RustFinanceEngine()

    # Net Delta = +0.35 (exceeds 0.20 threshold) -> Sell Futures
    rebalance = engine.calculate_gamma_scalping_rebalance(portfolio_delta=0.35, delta_threshold=0.20, lot_size=50)
    assert rebalance["rebalance_needed"] is True
    assert rebalance["action"] == "SELL_FUTURES"
    assert rebalance["rebalance_qty"] == 18


def test_sector_relative_strength_matrix():
    engine = AdvancedNSEMomentumEngine()

    sector_returns = {"BANK": 3.5, "IT": -1.2, "AUTO": 2.0}
    matrix = engine.rank_sector_relative_strength_matrix(sector_returns, benchmark_return=1.0)

    assert matrix[0]["sector"] == "BANK"
    assert matrix[0]["is_approved_leadership"] is True


def test_strategy_performance_demotion():
    engine = BarterRSEngine(min_profit_factor=1.10, min_sharpe_ratio=0.80)

    # Losing strategy trades -> Demote to PAPER_TRADING
    losing_pnls = [-10.0, -15.0, 5.0, -20.0, -8.0, 2.0, -12.0, -5.0, 4.0, -10.0]
    demotion = engine.evaluate_strategy_performance_demotion("STRAT_MOMENTUM_1", losing_pnls)

    assert demotion["demoted"] is True
    assert demotion["assigned_mode"] == "PAPER_TRADING"
