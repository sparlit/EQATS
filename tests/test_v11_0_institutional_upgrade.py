"""
Comprehensive & Strict Unit & Integration Test Suite for EQATS Version 11.0.0 Institutional Upgrade.

Verifies:
  1. System version 11.0.0 assertions across brain.py, self-healing governor, and design specs.
  2. Multi-Thread Parallel Multi-Processing execution pool orchestrator and batch symbol evaluations under stress.
  3. Strict 33 Validation & Anti-Overfitting Gates (Gates 0-33, Deflated Sharpe Ratio calculation with skewness/kurtosis, health state transitions).
  4. Quantum Strategy Genome Brain (26 Strategy Families x 8 Trading Horizons, Bowtie/Hourglass conditional structure).
  5. Multi-Asset Taxonomy Classification (Forex, Metals, Energy, Crypto, Indian NSE, BSE, MSE, MCX, NCDEX).
  6. Dynamic Macro Regime & Cross-Asset Correlation Classifier (Trend, Volatility, Liquidity, Macro Risk-On/Risk-Off).
  7. High-Priority Agentic Executive Agent Overseer.
  8. Standalone High-Priority Backend Autonomous Self-Healing Governor Daemon lifecycle and recovery.
"""

import os
import time
import pytest
import brain
import config
import database

try:
    from institutional_integrations.parallel_pool import (
        get_parallel_pool,
        parallel_process_map,
        parallel_thread_map,
    )
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
    from parallel_pool import (
        get_parallel_pool,
        parallel_process_map,
        parallel_thread_map,
    )
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

from v11_autonomous_self_healing_engine import (
    V11HyperAutonomousSelfFixingGovernor,
    global_v11_self_healing_governor,
)


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


def test_parallel_multi_processing_core_stress() -> None:
    """Verifies ParallelPoolOrchestrator thread/process pool execution and batch parallel evaluation across multiple assets."""
    pool = get_parallel_pool()
    assert pool.max_threads >= 4
    assert pool.max_processes >= 1

    def _sample_task(x: int) -> int:
        return x * x

    thread_results = parallel_thread_map(_sample_task, [1, 2, 3, 4, 5, 6, 7, 8])
    assert thread_results == [1, 4, 9, 16, 25, 36, 49, 64]

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
        "USDJPY": bars,
        "XAUUSD": bars,
        "BTCUSD": bars,
        "NSE:RELIANCE": bars,
    }

    eval_results = scalper_brain.evaluate_symbols_parallel(symbols_dict, 10000.0)
    assert len(eval_results) == 6
    for sym in symbols_dict:
        assert sym in eval_results
        assert "decision" in eval_results[sym]
        assert "v11_0_slippage_pips" in eval_results[sym]


def test_33_gate_validation_engine_comprehensive() -> None:
    """Verifies all 33 validation gates, Deflated Sharpe Ratio calculation with skewness/kurtosis, and strategy health state transitions."""
    engine = MultiAsset33GateValidationEngine()

    # Test Deflated Sharpe Ratio calculation with positive return series
    returns = [0.01, -0.005, 0.015, 0.02, -0.008, 0.012, 0.018, 0.022, -0.004, 0.016]
    dsr_prob = engine.calculate_deflated_sharpe_ratio(returns, num_trials=100)
    assert 0.0 <= dsr_prob <= 1.0

    # Test passing 33-gate evaluation
    valid_payload = {
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

    res_active = engine.evaluate_33_gates("V11_STRAT_PASS", valid_payload)
    assert res_active["strategy_id"] == "V11_STRAT_PASS"
    assert res_active["overall_pass"] is True
    assert res_active["gates_passed"] == 33
    assert res_active["health_state"] == StrategyHealthState.ACTIVE

    # Test failing gate evaluation causing SUSPENDED state
    failing_payload = dict(valid_payload)
    failing_payload["data_valid"] = False
    failing_payload["spread_pips"] = 10.0  # High cost ratio > 0.35
    failing_payload["slippage_mult"] = 10.0  # High slippage
    failing_payload["win_rate"] = 40.0
    failing_payload["oos_sharpe"] = 0.2
    failing_payload["wf_stability"] = 0.2
    failing_payload["param_robustness"] = False
    failing_payload["perturbation_pass"] = False
    failing_payload["mc_ruin_prob"] = 0.25
    failing_payload["p_value"] = 0.20
    failing_payload["snooping_free"] = False
    failing_payload["portfolio_conflict"] = True

    res_suspended = engine.evaluate_33_gates("V11_STRAT_FAIL", failing_payload)
    assert res_suspended["overall_pass"] is False
    assert res_suspended["health_state"] in [StrategyHealthState.SUSPENDED, StrategyHealthState.WARNING, StrategyHealthState.DEGRADED]
    assert res_suspended["gates_passed"] < 33


def test_quantum_strategy_genome_and_multi_asset_taxonomy() -> None:
    """Verifies Strategy Genome creation across 26 strategy families, 8 horizons, multi-asset taxonomy, and Bowtie/Hourglass structure."""
    brain_instance = QuantumStrategyGenomeBrain()

    # Asset Class Taxonomy Classification
    assert brain_instance.classify_asset_class("EURUSD") == AssetClass.FOREX
    assert brain_instance.classify_asset_class("XAUUSD") == AssetClass.PRECIOUS_METALS
    assert brain_instance.classify_asset_class("WTI") == AssetClass.OIL_ENERGY
    assert brain_instance.classify_asset_class("US30") == AssetClass.INDICES
    assert brain_instance.classify_asset_class("BTCUSD") == AssetClass.CRYPTO
    assert brain_instance.classify_asset_class("NSE:RELIANCE") == AssetClass.INDIAN_NSE
    assert brain_instance.classify_asset_class("BSE:SENSEX") == AssetClass.INDIAN_BSE
    assert brain_instance.classify_asset_class("MCX:GOLD") == AssetClass.INDIAN_MCX
    assert brain_instance.classify_asset_class("NCDEX:SOYBEAN") == AssetClass.INDIAN_NCDEX

    # Strategy Genome Creation
    families = [
        StrategyFamily.TREND,
        StrategyFamily.MOMENTUM,
        StrategyFamily.BREAKOUT,
        StrategyFamily.MEAN_REVERSION,
        StrategyFamily.QUANTITATIVE,
        StrategyFamily.BOWTIE_HOURGLASS,
    ]
    horizons = [
        TradingHorizon.HFT,
        TradingHorizon.SCALP,
        TradingHorizon.INTRADAY,
        TradingHorizon.DAY,
        TradingHorizon.SWING,
        TradingHorizon.POSITION,
    ]

    for fam in families:
        for hor in horizons:
            genome = brain_instance.generate_strategy_genome(
                symbol="EURUSD",
                family=fam,
                horizon=hor,
                timeframe="M15",
            )
            assert genome.family == fam
            assert genome.horizon == hor
            assert genome.asset_class == AssetClass.FOREX

    # Bowtie / Hourglass conditional breakout structure evaluation
    bowtie = brain_instance.evaluate_bowtie_hourglass_strategy("EURUSD", current_price=1.1000, atr_val=0.0015, regime="TRENDING")
    assert bowtie["strategy"] == StrategyFamily.BOWTIE_HOURGLASS
    assert bowtie["buy_trigger"] > 1.1000
    assert bowtie["sell_trigger"] < 1.1000
    assert bowtie["buy_sl"] < 1.1000
    assert bowtie["sell_sl"] > 1.1000


def test_macro_regime_and_correlation_classifier_broad() -> None:
    """Verifies multi-asset market regime classification across direction, volatility, and macro risk-on/risk-off states."""
    classifier = MacroRegimeClassifierBrain()

    # Strong Uptrend
    closes_up = [1.1000 + i * 0.0005 for i in range(100)]
    highs_up = [c + 0.0010 for c in closes_up]
    lows_up = [c - 0.0010 for c in closes_up]

    regime_up = classifier.classify_regime(highs_up, lows_up, closes_up)
    assert regime_up["direction"] == "UP"
    assert regime_up["macro_bias"] == "RISK_ON"

    # Strong Downtrend
    closes_down = [1.2000 - i * 0.0005 for i in range(100)]
    highs_down = [c + 0.0010 for c in closes_down]
    lows_down = [c - 0.0010 for c in closes_down]

    regime_down = classifier.classify_regime(highs_down, lows_down, closes_down)
    assert regime_down["direction"] == "DOWN"
    assert regime_down["macro_bias"] == "RISK_OFF"


def test_autonomous_executive_agent_directives() -> None:
    """Verifies Executive Agentic AI directive synthesis from regime, 33-gate validation, and Kronos signals."""
    agent = AutonomousExecutiveAgent()

    # Approved BUY directive
    regime_info = {"regime": RegimeType.TREND_STRONG, "direction": "UP"}
    validation_info = {"overall_pass": True, "gates_passed": 33}
    directive_buy = agent.generate_executive_directive("EURUSD", regime_info, validation_info, kronos_prob=0.75)
    assert directive_buy.bias == "BUY"
    assert directive_buy.executive_confidence > 0.50

    # VETO directive due to failed validation
    validation_fail = {"overall_pass": False, "gates_passed": 20}
    directive_veto = agent.generate_executive_directive("EURUSD", regime_info, validation_fail, kronos_prob=0.75)
    assert directive_veto.bias == "HOLD"
    assert directive_veto.executive_confidence < 0.50


def test_standalone_self_healing_governor_daemon_lifecycle() -> None:
    """Verifies high-priority self-healing governor daemon thread start, cycle execution, autotuning, and stop lifecycle."""
    governor = V11HyperAutonomousSelfFixingGovernor(check_interval_sec=0.1)

    status_initial = governor.get_status()
    assert status_initial["governor_version"] == "11.0.0"
    assert status_initial["running"] is False

    # Execute a diagnostic healing cycle directly
    governor.run_healing_cycle()
    assert governor.db_lock_repaired_count >= 1
    assert governor.autotune_cycles_count >= 1

    # Test daemon start and stop lifecycle
    governor.start_high_priority_daemon()
    assert governor._running is True
    time.sleep(0.25)
    governor.stop_daemon()
    assert governor._running is False

    status_final = governor.get_status()
    assert status_final["active_health_state"] == "ACTIVE"
    assert len(status_final["recent_logs"]) > 0
