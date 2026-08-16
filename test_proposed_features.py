import pytest
from institutional_integrations.fix_engine import FIXEngine
from institutional_integrations.execution_slicing import ExecutionSlicer
from institutional_integrations.tft_tcn_predictor import TemporalFusionTransformer, TemporalConvolutionalNetwork
from institutional_integrations.drl_execution_agent import DRLExecutionPolicyAgent
from institutional_integrations.whale_tracker import WhaleLiquidityTracker
from institutional_integrations.mcts_risk_engine import BlackSwanStressEngine
from institutional_integrations.portfolio_optimizer import BlackLittermanOptimizer
from institutional_integrations.backtest_engine import EventDrivenBacktester
from institutional_integrations.alert_dispatcher import MultiChannelAlertDispatcher

def test_fix_engine():
    fix = FIXEngine()
    logon_res = fix.logon()
    assert logon_res["status"] == "CONNECTED"
    assert "35=A" in logon_res["fix_raw"]

    hb_res = fix.heartbeat()
    assert "35=0" in hb_res["fix_raw"]

    ord_res = fix.send_order("EURUSD", "BUY", 0.01, 1.1000)
    assert ord_res["ord_status"] == "FILLED"
    assert ord_res["symbol"] == "EURUSD"

def test_execution_slicing():
    twap_slices = ExecutionSlicer.slice_twap(1.0, duration_seconds=100, num_slices=5)
    assert len(twap_slices) == 5
    assert twap_slices[0]["qty"] == 0.2

    vwap_slices = ExecutionSlicer.slice_vwap(1.0)
    assert len(vwap_slices) == 6

    iceberg_tranches = ExecutionSlicer.slice_iceberg(0.05, visible_qty=0.01)
    assert len(iceberg_tranches) == 5

    shortfall = ExecutionSlicer.calculate_implementation_shortfall(1.1000, 1.1002, 1.1005, 1.0)
    assert "shortfall_bps" in shortfall

def test_ml_and_whale_trackers():
    tft = TemporalFusionTransformer()
    forecasts = tft.predict_multi_horizon([1.1000, 1.1010, 1.1020, 1.1015, 1.1025])
    assert 1 in forecasts
    assert "price" in forecasts[1]

    tcn = TemporalConvolutionalNetwork()
    conv_res = tcn.compute_causal_conv([1.1000, 1.1010, 1.1020, 1.1015, 1.1025, 1.1030, 1.1035, 1.1040])
    assert "bias" in conv_res

    drl = DRLExecutionPolicyAgent()
    action = drl.select_action({"floating_pnl_pct": 2.0, "rsi": 75.0})
    assert action["partial_close_ratio"] > 0

    whale = WhaleLiquidityTracker()
    transfer = whale.fetch_whale_transfers("BTCUSD")
    assert transfer["amount_usd"] >= 1000000.0

def test_risk_and_portfolio_optimization():
    stress_res = BlackSwanStressEngine.run_stress_test(10000.0, 3)
    assert "2008_LEHMAN_COLLAPSE" in stress_res
    assert "status" in stress_res["2008_LEHMAN_COLLAPSE"]

    bl = BlackLittermanOptimizer()
    assets = ["EURUSD", "GBPUSD", "BTCUSD"]
    caps = {"EURUSD": 100.0, "GBPUSD": 80.0, "BTCUSD": 50.0}
    cov = [[0.0001, 0.00008, 0.00002], [0.00008, 0.00012, 0.00003], [0.00002, 0.00003, 0.0005]]
    views = {"EURUSD": 0.002, "GBPUSD": 0.001, "BTCUSD": 0.005}
    conf = {"EURUSD": 0.8, "GBPUSD": 0.6, "BTCUSD": 0.9}

    weights = bl.optimize(assets, caps, cov, views, conf)
    assert "EURUSD" in weights
    assert sum(weights.values()) > 0.0

def test_backtester_and_alerts():
    bt = EventDrivenBacktester()
    history = [{'open': 1.1000+i*0.0001, 'high': 1.1005+i*0.0001, 'low': 1.0995+i*0.0001, 'close': 1.1002+i*0.0001} for i in range(100)]
    wf_res = bt.walk_forward_optimization(history)
    assert "best_sharpe" in wf_res

    dispatcher = MultiChannelAlertDispatcher()
    alert_res = dispatcher.dispatch_alert("TEST_TITLE", "Test messageBody", severity="WARNING", channels=["TELEGRAM", "WHATSAPP", "TTS"])
    assert alert_res["channel_status"]["WHATSAPP"] is True
