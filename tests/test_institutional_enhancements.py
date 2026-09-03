from typing import Any

import indicators
import institutional_integrations.smc_ict_engine as smc
import institutional_integrations.trade_memory_protocol as tmp
from institutional_integrations.databases import QuestDBILPTickAdapter
from institutional_integrations.drl_execution_agent import DRLExecutionPolicyAgent
from institutional_integrations.portfolio_optimizer import BlackLittermanOptimizer
from institutional_integrations.web_api import SocketIPCBridge, TelemetryStreamServer


def test_smc_ict_order_block_and_fvg_detection() -> None:
    opens = [1.1, 1.099, 1.098, 1.097, 1.105, 1.11]
    highs = [1.101, 1.1, 1.099, 1.098, 1.106, 1.111]
    lows = [1.099, 1.098, 1.097, 1.096, 1.104, 1.109]
    closes = [1.099, 1.098, 1.097, 1.105, 1.109, 1.11]
    obs = smc.detect_order_blocks(opens, highs, lows, closes)
    assert "bullish_ob" in obs
    assert "bearish_ob" in obs
    fvgs = smc.detect_fair_value_gaps(highs, lows, closes)
    assert "bullish_fvgs" in fvgs
    assert "bearish_fvgs" in fvgs


def test_smc_ict_mss_and_liquidity_sweeps() -> None:
    highs = [1.1, 1.105, 1.102, 1.108, 1.115]
    lows = [1.095, 1.098, 1.094, 1.1, 1.105]
    closes = [1.098, 1.102, 1.096, 1.106, 1.112]
    mss = smc.detect_market_structure_shift(highs, lows, closes)
    assert "mss_status" in mss
    sweeps = smc.detect_liquidity_sweeps(highs, lows, closes)
    assert "bsl_sweep" in sweeps
    assert "ssl_sweep" in sweeps


def test_smc_ict_engine_analysis() -> None:
    engine = smc.SmartMoneyConceptsEngine()
    history_bars = []
    base_price = 1.1
    for i in range(30):
        history_bars.append(
            {
                "open": base_price + i * 0.0001,
                "high": base_price + i * 0.0001 + 0.0005,
                "low": base_price + i * 0.0001 - 0.0005,
                "close": base_price + i * 0.0001 + 0.0002,
            },
        )
    res = engine.analyze(history_bars)
    assert "bias" in res
    assert res["bias"] in ["BULLISH", "BEARISH", "NEUTRAL"]
    assert 0.0 <= res["confluence_score"] <= 100.0


def test_trade_memory_reflection_protocol() -> None:
    proto = tmp.TradeMemoryReflectionProtocol()
    rec = proto.log_reflection(
        ticket=101,
        symbol="EURUSD",
        direction="BUY",
        open_price=1.1,
        close_price=1.102,
        profit=20.0,
        reason="TP",
        mfe=0.0025,
        mae=0.0005,
    )
    assert rec["is_win"] is True
    assert rec["efficiency_score"] > 0
    summary = proto.get_summary()
    assert summary["total_reflections"] >= 1
    assert summary["win_rate"] == 100.0


def test_indicators_smc_wrapper() -> None:
    history_bars = []
    base_price = 1.1
    for i in range(20):
        history_bars.append(
            {"open": base_price, "high": base_price + 0.0005, "low": base_price - 0.0005, "close": base_price + 0.0001},
        )
    smc_res = indicators.get_smc_analysis(history_bars)
    assert "order_blocks" in smc_res
    assert "confluence_score" in smc_res


def test_drl_sac_ddpg_execution_agent() -> None:
    agent = DRLExecutionPolicyAgent()
    state = {"floating_pnl_pct": 2.0, "atr_vol": 0.0015, "rsi": 75.0, "order_book_imbalance": 0.6, "spread_pips": 2.5}
    action = agent.select_action(state)
    assert action["policy_type"] == "SAC_DDPG_CONTINUOUS_L2"
    assert action["slice_count"] >= 2
    assert action["partial_close_ratio"] > 0.0
    reward = agent.compute_reward(10000.0, 10200.0, 10.0, 0.5)
    assert isinstance(reward, float)
    update_res = agent.update_critic_actor_soft(state, action, reward, state)
    assert update_res["status"] == "UPDATED"


def test_cvxpy_qaoa_portfolio_optimizer() -> None:
    opt = BlackLittermanOptimizer()
    assets = ["EURUSD", "GBPUSD", "XAUUSD"]
    caps = {"EURUSD": 1000, "GBPUSD": 800, "XAUUSD": 1200}
    views = {"EURUSD": 0.02, "GBPUSD": 0.01, "XAUUSD": 0.03}
    confs = {"EURUSD": 0.8, "GBPUSD": 0.6, "XAUUSD": 0.9}
    weights = opt.optimize(assets, caps, None, views, confs)
    assert len(weights) == 3
    assert abs(sum(weights.values()) - 1.0) < 0.05
    qaoa_weights = opt.optimize_quantum_qaoa(assets, views)
    assert len(qaoa_weights) == 3
    assert abs(sum(qaoa_weights.values()) - 1.0) < 0.05


def test_questdb_ilp_tick_adapter() -> None:
    adapter = QuestDBILPTickAdapter(port=9999)
    line = adapter.format_ilp_line("EURUSD", 1.085, 1.0851, 100.0, 0.2)
    assert "ticks_l2,symbol=EURUSD" in line
    assert "bid=1.085" in line
    res = adapter.stream_tick("EURUSD", 1.085, 1.0851, 100.0, 0.2)
    assert res["status"] in ["SUCCESS", "FALLBACK"]
    if res["status"] == "FALLBACK":
        assert res["buffer_size"] >= 1


def test_socket_ipc_bridge_and_telemetry_stream() -> None:
    ipc = SocketIPCBridge(port=15555)
    push_res = ipc.push_state(10000.0, 10000.0, [], [], "London")
    assert push_res["status"] == "PUSHED"
    streamer = TelemetryStreamServer()
    payload = streamer.build_telemetry_payload(
        "2024-05-01 12:00:00", 10000.0, 10000.0, [], [], {"win_rate": 60.0, "net_profit": 500.0},
    )
    assert payload["account"]["equity"] == 10000.0
    assert payload["account"]["win_rate"] == 60.0
