import pytest
from institutional_integrations.cross_impact_execution import calculate_cross_asset_order_impact, optimize_almgren_chriss_execution, estimate_queue_position_delay
from institutional_integrations.hft_alpha_signals import compute_microstructure_momentum, detect_iceberg_liquidity_refill, score_order_flow_toxicity_index
from institutional_integrations.yield_curve_engine import YieldCurveEngine
from institutional_integrations.central_bank_nlp import CentralBankNLPParser

def test_cross_impact_and_almgren_chriss():
    impacts = calculate_cross_asset_order_impact(10.0)
    assert "EURUSD" in impacts

    trajectory = optimize_almgren_chriss_execution(100.0, duration_periods=5)
    assert len(trajectory) == 5
    assert trajectory[0]["shares_to_sell"] > 0

    delay = estimate_queue_position_delay(50)
    assert delay["expected_delay_sec"] > 0.0

def test_hft_alpha_signals():
    ticks = [{'price': 1.1000 + i*0.0001, 'volume': 10.0, 'timestamp_ms': 1000 + i*100} for i in range(5)]
    mom = compute_microstructure_momentum(ticks)
    assert "signal" in mom

    tape = [{'price': 1.1000, 'volume': 500.0, 'side': 'BUY'}]
    dom = {'asks': [(1.1000, 100.0)]}
    ice = detect_iceberg_liquidity_refill(tape, dom)
    assert ice["iceberg_detected"] is True

    tox = score_order_flow_toxicity_index(0.5, 0.3)
    assert "risk_level" in tox

def test_yield_curve_and_central_bank_nlp():
    yields = {2.0: 4.25, 5.0: 4.10, 10.0: 4.15, 30.0: 4.35}
    fit_res = YieldCurveEngine.fit_nelson_siegel_svensson(yields)
    assert "slope_10y_2y" in fit_res

    term_res = YieldCurveEngine.calculate_term_premium_and_slope(yields)
    assert "recession_probability_12m" in term_res

    cds = {"USA": 35.0, "DEU": 15.0, "ITA": 95.0}
    credit_res = YieldCurveEngine.detect_sovereign_credit_spread_widening(cds)
    assert len(credit_res["credit_stress_alerts"]) == 1

    statement = "Inflation remains elevated and persistent. Upside risks require rate hikes and restrictive tightening."
    nlp_res = CentralBankNLPParser.score_hawkish_dovish_index(statement)
    assert nlp_res["classification"] == "HAWKISH"

    shift_res = CentralBankNLPParser.extract_forward_guidance_shift(
        "We see downside risks and recession headwinds.",
        statement
    )
    assert shift_res["policy_shift"] == "HAWKISH_SHIFT"
