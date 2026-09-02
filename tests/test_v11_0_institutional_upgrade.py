"""
Comprehensive Unit & Integration Test Suite for EQATS Version 11.0.0 Institutional Upgrade Baseline.

Verifies:
  1. System version 11.0.0 assertions across brain.py, self-healing governor, and design specs.
  2. Multi-Thread Parallel Multi-Processing execution pool orchestrator and batch symbol evaluations.
  3. 33 Validation & Anti-Overfitting Gates (Formal Spec, Out-of-Sample, Walk-Forward, Deflated Sharpe, Health States).
  4. Quantum Strategy Genome Brain (26 Strategy Families x 8 Trading Horizons, Bowtie/Hourglass structure).
  5. Dynamic Macro Regime Brain (Direction, Volatility, Liquidity, Risk-On/Risk-Off).
  6. High-Priority Agentic Executive Agent Overseer.
  7. High-Priority Backend Autonomous Self-Healing Daemon.
"""

import os
import time

import pytest

import brain
import config
import database

try:
    from institutional_integrations.parallel_pool import get_parallel_pool, parallel_process_map, parallel_thread_map
    from institutional_integrations.v11_autonomous_executive_agent import (
        AutonomousExecutiveAgent,
        global_v11_executive_agent,
    )
    from institutional_integrations.v11_macro_regime_brain import (
        MacroRegimeClassifierBrain,
        RegimeType,
        global_v11_macro_regime_brain,
    )
    from institutional_integrations.v11_multi_asset_validation_engine import (
        MultiAsset33GateValidationEngine,
        StrategyHealthState,
        global_v11_validation_engine,
    )
    from institutional_integrations.v11_quantum_strategy_brain import (
        AssetClass,
        QuantumStrategyGenomeBrain,
        StrategyFamily,
        TradingHorizon,
        global_v11_quantum_strategy_brain,
    )
except ImportError:
    from parallel_pool import get_parallel_pool, parallel_process_map, parallel_thread_map
    from v11_autonomous_executive_agent import (
        AutonomousExecutiveAgent,
        global_v11_executive_agent,
    )
    from v11_macro_regime_brain import (
        MacroRegimeClassifierBrain,
        RegimeType,
        global_v11_macro_regime_brain,
    )
    from v11_multi_asset_validation_engine import (
        MultiAsset33GateValidationEngine,
        StrategyHealthState,
        global_v11_validation_engine,
    )
    from v11_quantum_strategy_brain import (
        AssetClass,
        QuantumStrategyGenomeBrain,
        StrategyFamily,
        TradingHorizon,
        global_v11_quantum_strategy_brain,
    )

from v11_autonomous_self_healing_engine import V11HyperAutonomousSelfFixingGovernor, global_v11_self_healing_governor


def setup_module() -> None:
    config.DB_PATH = "test_v11_0_upgrade.db"
    config.SIMULATION_MODE = True
    database.init_db()


def teardown_module() -> None:
    if os.path.exists("test_v11_0_upgrade.db"):
        try:
            os.remove("test_v11_0_upgrade.db")
        except Exception:
            pass


def test_v11_0_system_version_assertions() -> None:
    """Verifies that ScalperBrain, validation engine, strategy brain, macro regime, executive agent, and self-healing governor report v11.0.0."""
    scalper_brain = brain.ScalperBrain()
    assert scalper_brain.version == "11.0.0"
    assert global_v11_validation_engine.version == "11.0.0"
    assert global_v11_quantum_strategy_brain.version == "11.0.0"
    assert global_v11_macro_regime_brain.version == "11.0.0"
    assert global_v11_executive_agent.version == "11.0.0"
    assert global_v11_self_healing_governor.version == "11.0.0"


def test_parallel_multi_processing_core() -> None:
    """Verifies ParallelPoolOrchestrator thread/process pool execution and batch parallel evaluation."""
    pool = get_parallel_pool()
    assert pool.max_threads >= 4
    assert pool.max_processes >= 1

    def _sample_task(x: int) -> int:
        return x * x

    thread_results = parallel_thread_map(_sample_task, [1, 2, 3, 4, 5])
    assert thread_results == [1, 4, 9, 16, 25]

    scalper_brain = brain.ScalperBrain()
    bars = [
        {
            "open": 1.1 + i * 0.0001,
            "high": 1.1005 + i * 0.0001,
            "low": 1.0995 + i * 0.0001,
            "close": 1.1002 + i * 0.0001,
        }
        for i in range(210)
    ]

    symbols_dict = {
        "EURUSD": bars,
        "GBPUSD": bars,
        "XAUUSD": bars,
    }

    eval_results = scalper_brain.evaluate_symbols_parallel(symbols_dict, 10000.0)
    assert len(eval_results) == 3
    assert "EURUSD" in eval_results
    assert "GBPUSD" in eval_results
    assert "XAUUSD" in eval_results
    assert "decision" in eval_results["EURUSD"]


def test_33_gate_validation_and_anti_overfitting_engine() -> None:
    """Verifies all 33 validation gates, Deflated Sharpe Ratio calculation, and strategy health state transitions."""
    engine = MultiAsset33GateValidationEngine()
    returns = [0.01, -0.005, 0.015, 0.02, -0.008, 0.012, 0.018, 0.022, -0.004]

    dsr_prob = engine.calculate_deflated_sharpe_ratio(returns, num_trials=50)
    assert 0.0 <= dsr_prob <= 1.0

    payload = {
        "entry_rules": ["EMA_SHORT > EMA_MEDIUM"],
        "exit_rules": ["SL_OR_TP"],
        "data_valid": True,
        "edge_mechanism": "MOMENTUM_EXPANSION",
        "historical_returns": returns,
        "spread_pips": 1.2,
        "atr_pips": 15.0,
        "win_rate": 62.0,
        "oos_sharpe": 1.4,
        "wf_stability": 0.80,
        "param_robustness": True,
        "perturbation_pass": True,
        "slippage_mult": 1.0,
        "regime_encoded": True,
        "cross_asset_valid": True,
        "cross_tf_valid": True,
        "mc_ruin_prob": 0.005,
        "p_value": 0.01,
        "snooping_free": True,
        "capacity_usd": 5000000.0,
        "portfolio_conflict": False,
        "param_count": 4,
    }

    res = engine.evaluate_33_gates("V11_TEST_STRAT_01", payload)
    assert res["strategy_id"] == "V11_TEST_STRAT_01"
    assert res["overall_pass"] is True
    assert res["gates_passed"] == 33
    assert res["health_state"] == StrategyHealthState.ACTIVE
    assert len(res["gate_details"]) == 34  # Gates 0-32 plus Gate 33 Health State Machine


def test_quantum_strategy_genome_and_horizon_brain() -> None:
    """Verifies Strategy Genome creation, multi-asset asset class taxonomy, and Bowtie/Hourglass structure."""
    brain_instance = QuantumStrategyGenomeBrain()

    assert brain_instance.classify_asset_class("NSE:RELIANCE") == AssetClass.INDIAN_NSE
    assert brain_instance.classify_asset_class("MCX:GOLD") == AssetClass.INDIAN_MCX
    assert brain_instance.classify_asset_class("XAUUSD") == AssetClass.PRECIOUS_METALS
    assert brain_instance.classify_asset_class("USOIL") == AssetClass.OIL_ENERGY
    assert brain_instance.classify_asset_class("BTCUSD") == AssetClass.CRYPTO
    assert brain_instance.classify_asset_class("EURUSD") == AssetClass.FOREX

    genome = brain_instance.generate_strategy_genome(
        symbol="EURUSD",
        family=StrategyFamily.TREND,
        horizon=TradingHorizon.INTRADAY,
        timeframe="M15",
    )
    assert genome.family == StrategyFamily.TREND
    assert genome.horizon == TradingHorizon.INTRADAY
    assert genome.asset_class == AssetClass.FOREX

    bowtie = brain_instance.evaluate_bowtie_hourglass_strategy("EURUSD", 1.1000, 0.0015, regime="TRENDING")
    assert bowtie["strategy"] == StrategyFamily.BOWTIE_HOURGLASS
    assert "buy_trigger" in bowtie
    assert "sell_trigger" in bowtie


def test_macro_regime_and_correlation_classifier() -> None:
    """Verifies multi-asset market regime classification across direction, volatility, and macro bias."""
    classifier = MacroRegimeClassifierBrain()
    closes = [1.1000 + i * 0.0005 for i in range(100)]
    highs = [c + 0.0010 for c in closes]
    lows = [c - 0.0010 for c in closes]

    regime_res = classifier.classify_regime(highs, lows, closes)
    assert regime_res["direction"] == "UP"
    assert regime_res["macro_bias"] == "RISK_ON"
    assert regime_res["regime"] in [RegimeType.TREND_STRONG, RegimeType.HIGH_VOL_TREND, RegimeType.RANGE_LOW_VOL]


def test_autonomous_executive_agent() -> None:
    """Verifies Executive Agentic AI directive synthesis from regime, validation, and Kronos signals."""
    agent = AutonomousExecutiveAgent()
    regime_info = {"regime": RegimeType.TREND_STRONG, "direction": "UP"}
    validation_info = {"overall_pass": True, "gates_passed": 33}

    directive = agent.generate_executive_directive("EURUSD", regime_info, validation_info, kronos_prob=0.72)
    assert directive.bias == "BUY"
    assert directive.executive_confidence > 0.50
    assert len(directive.actionable_instructions) > 0


def test_standalone_self_healing_governor() -> None:
    """Verifies high-priority self-healing daemon status, database recovery, and autotuning."""
    governor = V11HyperAutonomousSelfFixingGovernor(check_interval_sec=0.1)
    status_before = governor.get_status()
    assert status_before["governor_version"] == "11.0.0"
    assert status_before["running"] is False

    # Execute a diagnostic healing cycle directly
    governor.run_healing_cycle()
    assert governor.db_lock_repaired_count >= 1
    assert governor.autotune_cycles_count >= 1

    status_after = governor.get_status()
    assert status_after["active_health_state"] == "ACTIVE"
    assert len(status_after["recent_logs"]) > 0
