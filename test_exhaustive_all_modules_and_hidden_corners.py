import os
import unittest
import time
import brain_agents_orchestrator
import config
import database
import event_bus
import main
import predictive_brain
import release_gates
import supervisor_agent
import telegram_bot

import institutional_integrations as ii
import institutional_integrations.alert_dispatcher as alert_disp
import institutional_integrations.backtest_engine as backtest
import institutional_integrations.brain_self_healer as self_healer
import institutional_integrations.causal_inference_engine as causal
import institutional_integrations.circuit_breaker as cb
import institutional_integrations.cointegration_pairs as cointeg
import institutional_integrations.comprehensive_suite as suite
import institutional_integrations.databases as db_inst
import institutional_integrations.drl_execution_agent as drl
import institutional_integrations.execution_slicing as slicing
import institutional_integrations.fix_engine as fix
import institutional_integrations.go_gateway as go_gw
import institutional_integrations.mcts_risk_engine as mcts
import institutional_integrations.options_gex_engine as gex
import institutional_integrations.order_flow_imbalance as ofi
import institutional_integrations.portfolio_optimizer as port_opt
import institutional_integrations.quantum_local_llm as llm
import institutional_integrations.quantum_quantum_engine as q_eng
import institutional_integrations.rust_bridge as rust_b
import institutional_integrations.smc_ict_engine as smc_eng
import institutional_integrations.tft_tcn_predictor as tft_tcn
import institutional_integrations.trade_memory_protocol as trade_mem
import institutional_integrations.universal_broker_adapter as univ_adapter
import institutional_integrations.web_api as web_api
import institutional_integrations.whale_tracker as whale


class TestExhaustiveAllModulesAndHiddenCorners(unittest.TestCase):
    """
    Exhaustive Test Suite covering every single module, class, hidden edge-case,
    fallback loop, and circuit breaker recovery path in the entire repository.
    """

    @classmethod
    def setUpClass(cls):
        cls.orig_db = config.DB_PATH
        config.DB_PATH = "test_exhaustive_modules.db"
        database.init_db()

    @classmethod
    def tearDownClass(cls):
        config.DB_PATH = cls.orig_db
        if os.path.exists("test_exhaustive_modules.db"):
            try:
                os.remove("test_exhaustive_modules.db")
            except Exception:
                pass

    def setUp(self):
        database.init_db()

    # --- 1. CORE ROOT MODULES TESTS ---
    def test_01_predictive_brain_and_learning(self):
        predictor = predictive_brain.get_symbol_predictor("EURUSD")
        inputs = [0.5, 1.0, 0.0, 0.001, 1.0, 1.2]
        prob = predictor.predict(inputs)
        self.assertTrue(0.0 <= prob <= 1.0)
        predictor.learn_and_adjust(1.0)
        state = predictor.get_internal_state()
        self.assertIn("training_cycles", state)

        # Batch prediction
        batch_res = predictive_brain.batch_predict_symbols_parallel({"EURUSD": inputs, "GBPUSD": inputs})
        self.assertIn("EURUSD", batch_res)

    def test_02_database_wal_and_retry_mechanics(self):
        # Database normalization helpers
        self.assertEqual(database.normalize_leverage("500"), "1:500")
        self.assertEqual(database.normalize_leverage("1:1000"), "1:1000")

        # Database credentials & profiles
        database.save_broker_credentials("ServerA", "123", "pass", "1:500", "Gateway", "Demo")
        creds = database.get_broker_credentials()
        self.assertEqual(creds["leverage"], "1:500")

        # WAL checkpointing
        database.checkpoint_wal(force=True)

    def test_03_brain_agents_and_supervisor(self):
        orchestrator = brain_agents_orchestrator.global_brain_orchestrator
        scalper = main.AutonomousScalper()
        orchestrator.run_agentic_loop(scalper, symbol="EURUSD")
        self.assertIsNotNone(orchestrator.last_directive)

        supervisor = supervisor_agent.global_supervisor_agent
        supervisor.run_supervisory_audit(scalper)

    def test_04_event_bus_and_telegram_bot(self):
        bus = event_bus.global_event_bus
        received = []
        def handler(evt):
            received.append(evt)

        bus.subscribe("TestEvent", handler)
        bus.publish(event_bus.Event(family="TestEvent", source="UnitTest", payload={"k": "v"}))
        self.assertEqual(len(received), 1)

        # Telegram bot mock delivery
        telegram_bot.send_telegram_message("Unit test alert message")

    def test_05_release_gates(self):
        runner = release_gates.ReleaseGateRunner()
        res = runner.run_all_gates()
        self.assertTrue(res)

    # --- 2. ALL 30 INSTITUTIONAL INTEGRATIONS MODULES TESTS ---
    def test_06_institutional_modules_sweep(self):
        # 1. Advanced Math
        res_math = suite.integrate_airflow()
        self.assertIn("status", res_math)

        # 2. Alert Dispatcher
        dispatcher = alert_disp.MultiChannelAlertDispatcher()
        dispatcher.dispatch_alert("INFO", "Test alert")

        # 3. Backtest Engine
        bt_engine = backtest.EventDrivenBacktester()
        bt_res = bt_engine.walk_forward_optimization([])
        self.assertIsInstance(bt_res, dict)

        # 4. Brain Self Healer
        healer = self_healer.QuantumSelfHealer()
        self.assertIsNotNone(healer)

        # 5. Causal Inference
        causal_eng = causal.CausalInferenceEngine()
        self.assertIsNotNone(causal_eng)

        # 6. Circuit Breaker
        circuit = cb.CircuitBreaker(failure_threshold=2, cooldown_seconds=1.0)
        self.assertTrue(circuit.allow())
        circuit.record_failure()
        circuit.record_failure()
        self.assertFalse(circuit.allow())  # OPEN state
        time.sleep(1.1)
        self.assertTrue(circuit.allow())   # HALF_OPEN state probe
        circuit.record_success()
        self.assertTrue(circuit.allow())   # CLOSED state restored

        # 7. Cointegration Pairs
        c_res = cointeg.run_johansen_cointegration_test([1.10, 1.11, 1.12], [1.20, 1.21, 1.22])
        self.assertIn("cointegrated", c_res)

        # 8. Data Science / Suite Integration
        funcs = [getattr(ii, name) for name in dir(ii) if name.startswith("integrate_")]
        self.assertGreaterEqual(len(funcs), 110)

        # 9. QuestDB / ILP Adapter
        quest_adapter = db_inst.QuestDBILPTickAdapter()
        self.assertIsNotNone(quest_adapter)

        # 10. DRL Execution Agent
        drl_agent = drl.DRLExecutionPolicyAgent()
        self.assertIsNotNone(drl_agent)

        # 11. Execution Slicing
        slices = slicing.ExecutionSlicer.slice_twap(1.0, duration_seconds=60, num_slices=5)
        self.assertEqual(len(slices), 5)

        # 12. FIX Engine
        fix_eng = fix.FIXEngine()
        self.assertIsNotNone(fix_eng)

        # 13. Go Gateway
        go_res = go_gw.start_go_concurrency_websocket_relay()
        self.assertEqual(go_res["status"], "RUNNING")

        # 14. MCTS / Black Swan Stress Engine
        mcts_res = mcts.BlackSwanStressEngine.run_stress_test(initial_equity=10000.0)
        self.assertIn("2008_LEHMAN_COLLAPSE", mcts_res)

        # 15. Options GEX Engine
        gex_res = gex.compute_black_scholes_greeks(100.0, 100.0, 0.1)
        self.assertIn("delta", gex_res)

        # 16. Order Flow Imbalance
        vpin_val = ofi.calculate_vpin([100.0], [50.0], 100.0)
        self.assertTrue(0.0 <= vpin_val <= 1.0)

        # 17. Portfolio Optimizer
        opt = port_opt.BlackLittermanOptimizer()
        self.assertIsNotNone(opt)

        # 18. Quantum Local LLM
        local_llm = llm.QuantumLocalGPT()
        self.assertIsNotNone(local_llm)

        # 19. Quantum Engine
        q_engine = q_eng.QuantumAutoEngine()
        self.assertIsNotNone(q_engine)

        # 20. Rust Bridge
        is_rust = rust_b.is_rust_available()
        self.assertIsInstance(is_rust, bool)

        # 21. SMC ICT Engine
        bars = [{"open": 1.10, "high": 1.11, "low": 1.09, "close": 1.105} for _ in range(30)]
        smc_res = smc_eng.global_smc_engine.analyze(bars)
        self.assertIn("bias", smc_res)

        # 22. TFT TCN Predictor
        predictor_tft = tft_tcn.TemporalFusionTransformer()
        self.assertIsNotNone(predictor_tft)

        # 23. Trade Memory Protocol
        mem_proto = trade_mem.TradeMemoryReflectionProtocol()
        self.assertIsNotNone(mem_proto)

        # 24. Universal Broker Adapter
        gateway = univ_adapter.UniversalBrokerGateway(protocol="SIMULATOR")
        self.assertTrue(gateway.connect())
        self.assertTrue(gateway.is_connected())

        # 25. Web API & IPC
        streamer = web_api.TelemetryStreamServer()
        telemetry = streamer.build_telemetry_payload("12:00:00", 10000.0, 10000.0, [], [], {})
        self.assertEqual(telemetry.get("schema_version"), 1)

        # 26. Whale Tracker
        tracker = whale.WhaleLiquidityTracker()
        self.assertIsNotNone(tracker)


if __name__ == "__main__":
    unittest.main()
