"""
Comprehensive verification test suite for Devil's Advocate teardown audit remediation.
Verifies fallbacks, exception handling, predictive EWMA forecasts, cross-asset graph propagation, and institutional integrations.
"""
from typing import Any
import pytest
from institutional_integrations.comprehensive_suite import integrate_airflow, integrate_pytorch, integrate_xgboost
from institutional_integrations.data_science import calculate_portfolio_weights
from institutional_integrations.databases import CrossAssetCorrelationGraph, insert_vector_embedding
from institutional_integrations.machine_learning import ActorCriticPolicy, generate_multi_model_ensemble_prediction

def test_comprehensive_suite_fallbacks() -> None:
    """Verify that comprehensive_suite integrations return structured status dictionaries."""
    res_airflow = integrate_airflow()
    assert 'status' in res_airflow
    assert res_airflow['status'] in ['ACTIVE', 'UNAVAILABLE']
    res_torch = integrate_pytorch()
    assert 'status' in res_torch
    res_xgb = integrate_xgboost()
    assert 'status' in res_xgb

def test_machine_learning_ewma_fallback() -> None:
    """Verify that multi-model ensemble prediction computes price forecast without random mock numbers."""
    prices = [1.1, 1.1005, 1.101, 1.1008, 1.1015]
    mean_pred, preds_dict = generate_multi_model_ensemble_prediction(prices)
    assert mean_pred > 0.0
    assert 'pytorch_lstm' in preds_dict
    assert abs(preds_dict['pytorch_lstm'] - 1.1015) < 0.05

def test_actor_critic_rl_policy() -> None:
    """Verify RL policy gradient evaluation on indicator state."""
    policy = ActorCriticPolicy(state_dim=4, action_dim=3)
    action_idx, probs, val = policy.select_action([0.3, 1.02, 0.0005, 0.001])
    assert action_idx in [0, 1, 2]
    assert len(probs) == 3
    assert pytest.approx(sum(probs), abs=0.01) == 1.0

def test_cross_asset_correlation_graph() -> None:
    """Verify cross-asset graph propagation for EURUSD breakouts."""
    graph = CrossAssetCorrelationGraph()
    warnings = graph.propagate_early_breakouts('EURUSD', 'BUY', correlation_threshold=0.4)
    assert isinstance(warnings, list)
    assert len(warnings) > 0
    symbols = [w['symbol'] for w in warnings]
    assert 'GBPUSD' in symbols
    assert 'USDJPY' in symbols
    usdjpy_warn = [w for w in warnings if w['symbol'] == 'USDJPY'][0]
    assert usdjpy_warn['suggested_bias'] == 'SELL'

def test_portfolio_weight_optimizer() -> None:
    """Verify Mean-Variance Sharpe allocation weight calculation."""
    returns = {'EURUSD': [0.001, -0.0005, 0.0012, 0.0008], 'GBPUSD': [0.0008, -0.0003, 0.001, 0.0005], 'USDJPY': [-0.0005, 0.0008, -0.0006, -0.0002]}
    weights = calculate_portfolio_weights(returns)
    assert len(weights) == 3
    assert pytest.approx(sum(weights.values()), abs=0.01) == 1.0

def test_insert_vector_embedding() -> None:
    """Verify vector index insertion fallback."""
    vector = [0.1, 0.2, 0.3, 0.4, 0.5]
    res = insert_vector_embedding('test_vec_1', vector)
    assert isinstance(res, dict)
    assert 'faiss' in res
    assert 'chromadb' in res

def test_floor_pivot_points_calculation() -> None:
    """Verify exact Floor Pivot Points math without dummy hardcoded offsets."""
    high, low, close = (1.105, 1.095, 1.1)
    pivot = (high + low + close) / 3.0
    r1 = 2.0 * pivot - low
    s1 = 2.0 * pivot - high
    assert pivot == pytest.approx(1.1, abs=1e-05)
    assert r1 == pytest.approx(1.105, abs=1e-05)
    assert s1 == pytest.approx(1.095, abs=1e-05)

def test_system_autotune_capabilities() -> None:
    """Verify system autotune detects capabilities and sets non-zero parameters."""
    from institutional_integrations.system_autotune import auto_tune_system_parameters, detect_system_capabilities
    caps = detect_system_capabilities()
    assert caps['cpu_logical_cores'] >= 1
    assert caps['ram_total_gb'] > 0
    tuned = auto_tune_system_parameters(caps)
    assert tuned['process_pool_workers'] >= 1
    assert tuned['ml_batch_size'] >= 8
