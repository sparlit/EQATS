"""
Integration test suite for EQATS v8.3j self-learning trade reflection, hardware capacity auto-detection,
and zero-mock resilience.
"""

from institutional_integrations.trade_memory_protocol import global_trade_memory_protocol
from institutional_integrations.system_autotune import detect_system_capabilities, auto_tune_system_parameters


def test_trade_memory_self_learning_retraining():
    """Verifies that winning and losing trade reflections retrain strategy weightings dynamically."""
    protocol = global_trade_memory_protocol
    initial_weight = protocol.get_adaptive_strategy_weight("SMC_ICT")

    # Log a winning trade
    protocol.log_reflection(
        ticket=101,
        symbol="EURUSD",
        direction="BUY",
        open_price=1.1000,
        close_price=1.1050,
        profit=50.0,
        reason="TP_HIT",
        strategy_used="SMC_ICT",
    )
    win_weight = protocol.get_adaptive_strategy_weight("SMC_ICT")
    assert win_weight > initial_weight

    # Log a losing trade
    protocol.log_reflection(
        ticket=102,
        symbol="EURUSD",
        direction="SELL",
        open_price=1.1050,
        close_price=1.1080,
        profit=-30.0,
        reason="SL_HIT",
        strategy_used="SMC_ICT",
    )
    loss_weight = protocol.get_adaptive_strategy_weight("SMC_ICT")
    assert loss_weight < win_weight


def test_no_trade_veto_logging_and_feature_analysis():
    """Verifies no-trade veto logging and post-mortem feature statistics."""
    protocol = global_trade_memory_protocol
    protocol.log_no_trade_veto(
        symbol="GBPUSD",
        direction="BUY",
        signal_probability=75.0,
        veto_reason="VPIN_TOXICITY_HIGH",
        strategy_used="ORDER_FLOW",
    )
    analysis = protocol.analyze_post_mortem_features()
    assert analysis["total_records"] > 0
    assert analysis["veto_count"] >= 1
    assert "adaptive_weights" in analysis


def test_system_autotune_capabilities_and_tiers():
    """Verifies hardware capabilities detection and dynamic parameter tuning."""
    caps = detect_system_capabilities()
    assert "cpu_logical_cores" in caps
    assert "ram_total_gb" in caps
    assert caps["performance_tier"] in ["LOW", "MEDIUM", "HIGH", "ULTRA"]

    tuned = auto_tune_system_parameters(caps)
    assert tuned["process_pool_workers"] >= 2
    assert tuned["thread_pool_workers"] >= 4
    assert tuned["ml_batch_size"] in [16, 32, 64, 128]
