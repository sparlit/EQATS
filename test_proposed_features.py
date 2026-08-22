from institutional_integrations.alert_dispatcher import MultiChannelAlertDispatcher
from institutional_integrations.backtest_engine import EventDrivenBacktester
from institutional_integrations.drl_execution_agent import DRLExecutionPolicyAgent
from institutional_integrations.execution_slicing import ExecutionSlicer
from institutional_integrations.fix_engine import FIXEngine
from institutional_integrations.mcts_risk_engine import BlackSwanStressEngine
from institutional_integrations.portfolio_optimizer import BlackLittermanOptimizer
from institutional_integrations.tft_tcn_predictor import (
    TemporalConvolutionalNetwork,
    TemporalFusionTransformer,
)
from institutional_integrations.whale_tracker import WhaleLiquidityTracker



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

    shortfall = ExecutionSlicer.calculate_implementation_shortfall(
        1.1000, 1.1002, 1.1005, 1.0
    )
    assert "shortfall_bps" in shortfall


def test_ml_and_whale_trackers():
    tft = TemporalFusionTransformer()
    forecasts = tft.predict_multi_horizon([1.1000, 1.1010, 1.1020, 1.1015, 1.1025])
    assert 1 in forecasts
    assert "price" in forecasts[1]

    tcn = TemporalConvolutionalNetwork()
    conv_res = tcn.compute_causal_conv(
        [1.1000, 1.1010, 1.1020, 1.1015, 1.1025, 1.1030, 1.1035, 1.1040]
    )
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
    cov = [
        [0.0001, 0.00008, 0.00002],
        [0.00008, 0.00012, 0.00003],
        [0.00002, 0.00003, 0.0005],
    ]
    views = {"EURUSD": 0.002, "GBPUSD": 0.001, "BTCUSD": 0.005}
    conf = {"EURUSD": 0.8, "GBPUSD": 0.6, "BTCUSD": 0.9}

    weights = bl.optimize(assets, caps, cov, views, conf)
    assert "EURUSD" in weights
    assert sum(weights.values()) > 0.0


def test_backtester_and_alerts():
    bt = EventDrivenBacktester()
    history = [
        {
            "open": 1.1000 + i * 0.0001,
            "high": 1.1005 + i * 0.0001,
            "low": 1.0995 + i * 0.0001,
            "close": 1.1002 + i * 0.0001,
        }
        for i in range(100)
    ]
    wf_res = bt.walk_forward_optimization(history)
    assert "best_sharpe" in wf_res

    dispatcher = MultiChannelAlertDispatcher()
    alert_res = dispatcher.dispatch_alert(
        "TEST_TITLE",
        "Test messageBody",
        severity="WARNING",
        channels=["TELEGRAM", "WHATSAPP", "TTS"],
    )
    assert alert_res["channel_status"]["WHATSAPP"] is True


def setup_module():
    import config
    import database

    config.DB_PATH = "test_proposed_features.db"
    database.init_db()


def test_customizable_leverage_persistence():
    import database

    database.init_db()

    # Test saving custom leverage entries
    database.save_broker_credentials(
        "TestServer",
        "123456",
        "pwd123",
        "1:888",
        broker_name="Custom Gateway",
        environment="Demo",
    )
    creds = database.get_broker_credentials()
    assert creds["leverage"] == "1:888"

    database.save_broker_credentials(
        "TestServer",
        "123456",
        "pwd123",
        "1:10000",
        broker_name="High Lev Gateway",
        environment="Demo",
    )
    creds2 = database.get_broker_credentials()
    assert creds2["leverage"] == "1:10000"


def test_fixed_001_lot_position_sizing():
    import brain

    scalper_brain = brain.ScalperBrain()

    # Generate dummy price history
    bars = [
        {
            "open": 1.1000 + i * 0.0001,
            "high": 1.1005 + i * 0.0001,
            "low": 1.0995 + i * 0.0001,
            "close": 1.1002 + i * 0.0001,
        }
        for i in range(210)
    ]

    # Test with $10,000 equity
    res1 = scalper_brain.evaluate("EURUSD", bars, 10000.0)
    if res1["decision"] in ["BUY", "SELL"]:
        assert res1["lot_size"] == 0.01

    # Test with $100,000 equity
    res2 = scalper_brain.evaluate("XAUUSD", bars, 100000.0)
    if res2["decision"] in ["BUY", "SELL"]:
        assert res2["lot_size"] == 0.01

    # Test _calculate_lot_size direct helper
    assert scalper_brain._calculate_lot_size("EURUSD", 50000.0, 0.0020) == 0.01


def test_symbol_floating_loss_protection_gate():
    import time

    import brain
    import database
    database.init_db()

    # Log an open trade running in floating loss
    ticket_id = f"TEST_LOSS_{int(time.time() * 1000)}"
    database.log_trade_open(ticket_id, "EURUSD", "BUY", 1.1500, 1.1400, 1.1600, 0.01)

    scalper_brain = brain.ScalperBrain()
    # History with current price = 1.1000 (< entry 1.1500, so BUY in loss)
    bars = [
        {
            "open": 1.1000 + i * 0.00001,
            "high": 1.1005 + i * 0.00001,
            "low": 1.0995 + i * 0.00001,
            "close": 1.1002 + i * 0.00001,
        }
        for i in range(210)
    ]

    res = scalper_brain.evaluate("EURUSD", bars, 10000.0)
    assert res["decision"] == "HOLD"
    assert "Symbol Floating Loss Protection Gate Active" in res["explanation"]

    # Cleanup open trade
    database.log_trade_close(ticket_id, 1.1002, -498.0, "TEST_CLOSE")


def test_universal_broker_adapter_and_connector():
    from connector import UniversalConnector
    from institutional_integrations.universal_broker_adapter import (
        UniversalBrokerGateway,
    )

    gw = UniversalBrokerGateway(protocol="SIMULATOR")
    assert gw.connect() is True
    assert gw.is_connected() is True
    acc = gw.get_account_info()
    assert "balance" in acc

    conn = UniversalConnector(protocol="SIMULATOR")
    assert conn.connect() is True
    assert conn.is_connected() is True
    exec_res = conn.execute_order("EURUSD", "BUY", 0.01, 1.0900, 1.1100)
    assert exec_res["success"] is True
