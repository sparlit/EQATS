import pytest
from institutional_integrations.cointegration_pairs import run_johansen_cointegration_test, calculate_z_score_spread, evaluate_pairs_arbitrage_signal
from institutional_integrations.order_flow_imbalance import calculate_vpin, detect_bid_ask_imbalance, predict_short_term_book_pressure
from institutional_integrations.options_gex_engine import compute_black_scholes_greeks, calculate_aggregate_gex, detect_gamma_flip_level
from institutional_integrations.causal_inference_engine import CausalInferenceEngine
from institutional_integrations.spatial_supply_chain import SpatialSupplyChainAnalytics

def test_cointegration_and_stat_arb():
    prices_a = [1.1000 + i*0.0005 for i in range(30)]
    prices_b = [1.2000 + i*0.0004 for i in range(30)]

    coint_res = run_johansen_cointegration_test(prices_a, prices_b)
    assert "cointegrated" in coint_res
    assert "hedge_ratio" in coint_res

    z_score = calculate_z_score_spread(prices_a, prices_b, hedge_ratio=coint_res["hedge_ratio"])
    assert isinstance(z_score, float)

    signal = evaluate_pairs_arbitrage_signal(2.5)
    assert signal["action"] == "SHORT_A_LONG_B"

def test_order_flow_and_vpin():
    buys = [10.0, 15.0, 20.0, 8.0, 5.0]
    sells = [5.0, 8.0, 22.0, 12.0, 15.0]

    vpin = calculate_vpin(buys, sells, bucket_size=50.0)
    assert 0.0 <= vpin <= 1.0

    dom = {"bids": [(1.1000, 250), (1.0999, 150)], "asks": [(1.1001, 50), (1.1002, 50)]}
    imb = detect_bid_ask_imbalance(dom)
    assert imb["dominant_side"] == "BUY_DOMINANT"

    press = predict_short_term_book_pressure(250, 170)
    assert "pressure_score" in press

def test_options_gex():
    greeks = compute_black_scholes_greeks(1.1000, 1.1000, 0.25, rate=0.04, iv=0.15)
    assert greeks["delta"] > 0.0
    assert greeks["gamma"] > 0.0

    chain = [
        {'strike': 1.0900, 'call_open_interest': 1000, 'put_open_interest': 500, 'gamma': 0.001},
        {'strike': 1.1000, 'call_open_interest': 2000, 'put_open_interest': 800, 'gamma': 0.002},
        {'strike': 1.1100, 'call_open_interest': 500, 'put_open_interest': 2500, 'gamma': 0.001}
    ]
    gex_res = calculate_aggregate_gex(chain)
    assert "total_gex_usd" in gex_res

    flip_strike = detect_gamma_flip_level(gex_res["gex_by_strike"])
    assert flip_strike > 0.0

def test_causal_inference():
    causal = CausalInferenceEngine()
    causal.add_causal_edge("FED_RATES", "USD_INDEX", 0.85)
    causal.add_causal_edge("USD_INDEX", "EURUSD", -0.92)

    res = causal.evaluate_do_calculus_intervention("FED_RATES", "USD_INDEX", 0.25)
    assert res["causal_effect"] > 0.0
    assert res["spurious_correlation_eliminated"] is True

def test_spatial_supply_chain():
    choke_res = SpatialSupplyChainAnalytics.parse_maritime_vessel_density("SUEZ_CANAL")
    assert choke_res["current_vessel_density"] > 0

    shock = SpatialSupplyChainAnalytics.score_supply_shock_index(2200.0, 90.0)
    assert "composite_supply_stress_score" in shock
