import ctypes
import unittest
import numpy as np
import pandas as pd
from institutional_integrations.bayesian_consensus import BayesianConsensusEngine, global_bayesian_consensus
from institutional_integrations import aat_strategies
from institutional_integrations.aat_analyst import MacroAnalyst, SMCAnalyst, VolatilityAnalyst
from institutional_integrations.web_api import MCPServerCore
from institutional_integrations import itip_signal_store
from institutional_integrations.mql_colab_engine import SLTPEngine, CandlestickAIClassifier, LatencyArbitrage
from institutional_integrations.sovereign_intelligence import SovereignIntelligencePlugin
from institutional_integrations import vibe_quantlib
from institutional_integrations.openalgo_engine import OpenAlgoSmartOrderSplitter, OpenAlgoSessionSquareOffManager
from institutional_integrations.openbull_analytics import calculate_max_pain, calculate_synthetic_future_price
from institutional_integrations.nautilus_trader_engine import NautilusFixedRiskSizer, NautilusOrderRoutingGuard
from institutional_integrations.prop_firm_tracker import PropFirmChallengeTracker
from institutional_integrations.ftmo_risk_guard import FTMORiskGuardEngine, FTMOQualificationAuditor
from institutional_integrations.meta_edge_quant import calculate_probabilistic_sharpe_ratio, calculate_kelly_fraction, calculate_edge_score, EmpiricalSlippageTracker
from institutional_integrations.nexquant_engine import NexQuantFactorModel, NexQuantPortfolioOptimizer
from institutional_integrations.ftmo_journal_analyzer import FTMOJournalAnalyzer
from institutional_integrations.ftmo_tradingbot_core import ScaleOnProfitEngine, FTMODynamicStopEngine, ConsensusSizingModulator, CombinedExposureCapGuard
from institutional_integrations.prop_firm_calendar_feed import PropFirmCalendarFeedManager
from institutional_integrations.qma_quant_strategy import detect_rsi_failure_swing, calculate_ttm_squeeze, QMAQuantStrategy
from institutional_integrations.mt5bot_engine import MT5BotVolumeNormalizer, RelativePricePredictionEvaluator
from institutional_integrations.ftmo_temporal_matcher import FewShotTemporalMatcher
from institutional_integrations.awesome_llm_finance_team import MultiAgentFinanceTeamOrchestrator
from institutional_integrations.awesome_llm_agents import DeepResearchAgent, InvestmentAgent, DataAnalystAgent
from institutional_integrations.ea_scalper_xauusd_engine import AMDCycleTracker, FootprintPocAnalyzer, MarketGapCooldownGuard
from institutional_integrations.prop_guard_equity_armor import PropGuardEquityArmorEngine
from institutional_integrations.prop_firm_elite_tracker import SignalPulseLogSyncParser, PropFirmEliteMultiAccountAggregator
from institutional_integrations.prop_guardian_safety import PropGuardianMasterFilters, PROP_FIRMS_DATABASE
from datetime import datetime, timezone

class TestAATAdaptedModules(unittest.TestCase):

    def test_prop_guardian_safety(self):
        filters = PropGuardianMasterFilters(max_spread_pips=3.0)
        res = filters.passes_all_filters("EURUSD", current_spread_pips=1.2, current_atr=0.0015, historical_atr=0.0012, utc_hour=10, utc_weekday=2)
        self.assertTrue(res["passed"])
        self.assertEqual(res["base_currency"], "EUR")

        self.assertIn("FTMO", PROP_FIRMS_DATABASE)
        self.assertEqual(PROP_FIRMS_DATABASE["FTMO"]["daily_dd_pct"], 5.0)

    def test_prop_firm_elite_tracker(self):
        parser = SignalPulseLogSyncParser()
        res = parser.parse_log_line("2026.08.29 12:00:00 order #1001 buy 0.1 EURUSD at 1.1000 profit: +150.0")
        self.assertIsNotNone(res)
        self.assertEqual(res["direction"], "BUY")
        self.assertEqual(res["profit"], 150.0)

        agg = PropFirmEliteMultiAccountAggregator()
        accs = [
            {"account_id": "1", "passed": True, "failed": False, "current_profit": 10500.0},
            {"account_id": "2", "passed": False, "failed": False, "current_profit": 3200.0},
        ]
        res_a = agg.aggregate_accounts(accs)
        self.assertEqual(res_a["total_accounts"], 2)
        self.assertEqual(res_a["accounts_passed"], 1)
        self.assertEqual(res_a["total_combined_profit"], 13700.0)

    def test_prop_guard_equity_armor(self):
        armor = PropGuardEquityArmorEngine(daily_loss_limit_pct=5.0, max_drawdown_pct=10.0, kill_switch_cooldown_min=1)
        res1 = armor.update_equity_sample(current_equity=100000.0, day_start_equity=100000.0)
        self.assertEqual(res1["zone"], "GREEN")

        res2 = armor.update_equity_sample(current_equity=96000.0, day_start_equity=100000.0) # 80% daily loss util (Yellow)
        self.assertEqual(res2["zone"], "YELLOW")

        res3 = armor.update_equity_sample(current_equity=94000.0, day_start_equity=100000.0) # 120% daily loss util (Red - Kill switch)
        self.assertEqual(res3["zone"], "RED")
        self.assertTrue(res3["is_locked_out"])

    def test_ea_scalper_xauusd_engine(self):
        amd = AMDCycleTracker()
        closes = [1.1000 + i*0.0001 for i in range(25)]
        highs = [c + 0.0005 for c in closes]
        lows = [c - 0.0005 for c in closes]
        res = amd.detect_amd_phase(closes, highs, lows, utc_hour=14)
        self.assertIn("phase", res)

        fp = FootprintPocAnalyzer()
        res_fp = fp.analyze_footprint(100.0, 40.0, 1.1000, 1.1005)
        self.assertEqual(res_fp["bias"], "BULLISH_POC_SUPPORT")

        gap = MarketGapCooldownGuard(cooldown_bars_after_gap=2)
        has_gap = gap.check_gap(1.1000, 1.1030, atr_val=0.0010)
        self.assertTrue(has_gap)

    def test_awesome_llm_agents(self):
        dra = DeepResearchAgent()
        res_r = dra.research_topic("Quantitative Macro Liquidity")
        self.assertIn("insights", res_r)

        ia = InvestmentAgent()
        res_i = ia.evaluate_investment("AAPL", spot_price=150.0, eps_growth=0.15)
        self.assertEqual(res_i["recommendation"], "BUY")

        daa = DataAnalystAgent()
        df = pd.DataFrame([{"pnl": 100.0, "lots": 0.1}, {"pnl": -50.0, "lots": 0.1}])
        res_d = daa.analyze_dataset(df)
        self.assertEqual(res_d["rows"], 2)

    def test_awesome_llm_finance_team(self):
        team = MultiAgentFinanceTeamOrchestrator()
        allocs = {"EURUSD": 2000.0, "BTCUSD": 3000.0}
        res = team.generate_team_consensus("EURUSD", spot_price=1.1000, equity=10000.0, current_allocations=allocs)
        self.assertEqual(res["symbol"], "EURUSD")
        self.assertIn("consensus_action", res)
        self.assertIn("advisor_summary", res)

    def test_ftmo_temporal_matcher(self):
        matcher = FewShotTemporalMatcher()
        query = [1.1000, 1.1010, 1.1020, 1.1015, 1.1030]
        supp = [
            [1.0900, 1.0910, 1.0920, 1.0915, 1.0930],
            [1.1500, 1.1510, 1.1520, 1.1515, 1.1530]
        ]
        sim = matcher.compute_similarity(query, supp)
        self.assertGreaterEqual(sim, 0.0)
        self.assertLessEqual(sim, 1.0)

    def test_mt5bot_engine(self):
        norm = MT5BotVolumeNormalizer()
        v = norm.normalize_volume(0.123, min_volume=0.01, max_volume=10.0, step_volume=0.01)
        self.assertEqual(v, 0.12)

        evaluator = RelativePricePredictionEvaluator()
        res_buy = evaluator.evaluate_prediction_gap(100.0, 102.0, min_gap_pct=1.0)
        self.assertEqual(res_buy["action"], "BUY")
        self.assertEqual(res_buy["gap_pct"], 2.0)

    def test_qma_quant_strategy(self):
        rsi_series = [30.0, 42.0, 32.0, 45.0, 40.0, 48.0]
        fs = detect_rsi_failure_swing(rsi_series)
        self.assertEqual(fs, "BUY")

        closes = [1.1000 + i*0.0001 for i in range(25)]
        highs = [c + 0.0003 for c in closes]
        lows = [c - 0.0003 for c in closes]
        sq = calculate_ttm_squeeze(closes, highs, lows)
        self.assertIn("squeeze_on", sq)
        self.assertIn("momentum", sq)

        qma = QMAQuantStrategy()
        res = qma.evaluate_qma_setup("EURUSD", closes, highs, lows, rsi_val=48.0, utc_hour=10)
        self.assertEqual(res["symbol"], "EURUSD")
        self.assertIn("decision", res)

    def test_prop_firm_calendar_feed(self):
        cal = PropFirmCalendarFeedManager()
        s_dt = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        e_dt = datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc)
        key = cal.add_event("FTMO", "maintenance", "Scheduled Server Maintenance", s_dt, e_dt)
        self.assertTrue(key)

        ics = cal.generate_ics_feed(firm_filter="FTMO")
        self.assertIn("BEGIN:VCALENDAR", ics)
        self.assertIn("[FTMO] Scheduled Server Maintenance", ics)
        self.assertIn("END:VCALENDAR", ics)

    def test_ftmo_tradingbot_core(self):
        sop = ScaleOnProfitEngine()
        trig = sop.should_trigger_addon("BUY", 1.1000, 1.1020, atr_at_entry=0.0010)
        self.assertTrue(trig)
        params = sop.calculate_addon_params("BUY", 1.1000, main_lot_size=0.10)
        self.assertEqual(params["addon_lot_size"], 0.05)
        self.assertEqual(params["addon_stop_loss"], 1.1000)

        dyn = FTMODynamicStopEngine()
        trail = dyn.evaluate_trailing_stop("BUY", 1.1000, 1.1030, 1.0950, atr_val=0.0010)
        self.assertTrue(trail["should_update"])
        self.assertGreater(trail["new_stop_loss"], 1.0950)

        csm = ConsensusSizingModulator()
        mult = csm.compute_consensus_multiplier([1, 1], 1)
        self.assertEqual(mult, 1.0)

        cap = CombinedExposureCapGuard()
        res = cap.check_exposure_cap([10000.0, 15000.0], 5000.0, current_equity=100000.0)
        self.assertTrue(res["allowed"])

    def test_ftmo_journal_analyzer(self):
        analyzer = FTMOJournalAnalyzer()
        trades = [
            {"ticket": "1", "profit": 200.0, "volume": 0.1},
            {"ticket": "2", "profit": -100.0, "volume": 0.1},
            {"ticket": "3", "profit": 300.0, "volume": 0.1},
        ]
        stats = analyzer.compute_journal_stats(trades)
        self.assertEqual(stats["total_trades"], 3)
        self.assertEqual(stats["profit_factor"], 5.0)
        self.assertEqual(stats["net_profit"], 400.0)

    def test_nexquant_engine(self):
        model = NexQuantFactorModel(learning_rate=0.05)
        model.fit_step(np.array([0.5, 1.01, 0.02, 0.001, 1.0, 1.0]), target=0.8)
        sig = model.predict_alpha_signal([0.5, 1.01, 0.02, 0.001, 1.0, 1.0])
        self.assertGreaterEqual(sig, -1.0)
        self.assertLessEqual(sig, 1.0)

        opt = NexQuantPortfolioOptimizer()
        returns_data = {
            "S1": [0.01, 0.02, -0.005, 0.015],
            "S2": [0.005, 0.01, 0.002, 0.008],
        }
        weights = opt.optimize_weights(returns_data)
        self.assertIn("S1", weights)
        self.assertIn("S2", weights)
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=3)

    def test_meta_edge_quant(self):
        returns = [0.01, 0.02, -0.005, 0.015, 0.008, 0.012, -0.002, 0.025]
        psr = calculate_probabilistic_sharpe_ratio(returns)
        self.assertGreaterEqual(psr, 0.50)

        kelly = calculate_kelly_fraction(win_rate=0.60, reward_risk_ratio=1.5)
        self.assertGreater(kelly, 0.0)

        edge = calculate_edge_score(5.0, 0.60, 1.5, returns)
        self.assertIn("edge_score", edge)
        self.assertIn("is_deploy_safe", edge)

        tracker = EmpiricalSlippageTracker()
        tracker.record_fill("EURUSD", 1.1000, 1.1002, atr=0.0010)
        stats = tracker.get_symbol_stats("EURUSD")
        self.assertEqual(stats["count"], 1)
        self.assertEqual(stats["mean_slippage"], 0.0002)

    def test_ftmo_risk_guard(self):
        engine = FTMORiskGuardEngine(initial_balance=100000.0)
        res = engine.evaluate_order_risk("EURUSD", "BUY", 0.1, 1.1000, 1.0950, current_equity=101000.0, day_start_equity=100000.0)
        self.assertEqual(res["decision"], "ALLOW")

        auditor = FTMOQualificationAuditor()
        closed_trades = [
            {"ftmo_day": "DAY1", "net_profit": 2000.0},
            {"ftmo_day": "DAY2", "net_profit": 3000.0},
            {"ftmo_day": "DAY3", "net_profit": 2500.0},
            {"ftmo_day": "DAY4", "net_profit": 2500.0},
        ]
        qual = auditor.evaluate_qualification(starting_balance=100000.0, current_equity=110000.0, target_profit_pct=10.0, closed_trades=closed_trades)
        self.assertTrue(qual["fully_qualified"])

    def test_prop_firm_tracker(self):
        tracker = PropFirmChallengeTracker(firm="FTMO", starting_balance=100000.0, phase=1)
        res = tracker.evaluate_account_status(current_equity=110500.0, current_balance=110500.0, day_start_equity=108000.0, days_traded=5)
        self.assertTrue(res["passed"])
        self.assertEqual(res["status"], "PASSED")
        self.assertEqual(res["firm"], "FTMO")

    def test_nautilus_trader_engine(self):
        sizer = NautilusFixedRiskSizer()
        size = sizer.calculate_position_size(equity=10000.0, risk_pct=1.0, entry_price=1.1000, stop_loss_price=1.0950)
        self.assertGreater(size, 0.0)

        guard = NautilusOrderRoutingGuard(max_account_exposure=50000.0, max_open_orders=5)
        res = guard.validate_order("EURUSD", "BUY", 1.0, 1.1000, current_open_orders=2)
        self.assertTrue(res["allowed"])

    def test_openbull_analytics(self):
        chain = [
            {"strike": 100.0, "ce_oi": 500, "pe_oi": 100},
            {"strike": 105.0, "ce_oi": 1000, "pe_oi": 800},
            {"strike": 110.0, "ce_oi": 200, "pe_oi": 1200},
        ]
        mp = calculate_max_pain(chain)
        self.assertEqual(mp["max_pain_strike"], 105.0)

        sf = calculate_synthetic_future_price(105.0, 3.5, 2.0, 106.0)
        self.assertEqual(sf["synthetic_future_price"], 106.5)
        self.assertEqual(sf["basis"], 0.5)

    def test_openalgo_engine(self):
        splitter = OpenAlgoSmartOrderSplitter(max_slice_lot=2.0)
        slices = splitter.slice_order("EURUSD", "BUY", 5.5)
        self.assertEqual(len(slices), 3)
        self.assertEqual(slices[0]["volume"], 2.0)
        self.assertEqual(slices[1]["volume"], 2.0)
        self.assertEqual(slices[2]["volume"], 1.5)

        sq = OpenAlgoSessionSquareOffManager()
        self.assertFalse(sq.check_squareoff_required(12, 0))
        self.assertTrue(sq.check_squareoff_required(16, 55))

    def test_vibe_quantlib(self):
        # Test VPIN
        buy_v = [10.0, 15.0, 8.0, 20.0, 12.0]
        sell_v = [5.0, 8.0, 12.0, 5.0, 15.0]
        vpin_val = vibe_quantlib.calculate_vpin(buy_v, sell_v, bucket_size=10.0, n_buckets=5)
        self.assertGreaterEqual(vpin_val, 0.0)
        self.assertLessEqual(vpin_val, 1.0)

        # Test Roll spread & Kyle lambda & Amihud
        prices = [1.1000, 1.1005, 1.0998, 1.1012, 1.1008]
        roll = vibe_quantlib.calculate_roll_spread(prices)
        self.assertGreaterEqual(roll, 0.0)

        kyle = vibe_quantlib.calculate_kyle_lambda([0.0005, -0.0007, 0.0014, -0.0004], [5.0, -8.0, 12.0, -3.0])
        self.assertIsInstance(kyle, float)

        amihud = vibe_quantlib.calculate_amihud_illiquidity([0.001, 0.002, 0.0015], [10000.0, 15000.0, 12000.0])
        self.assertGreaterEqual(amihud, 0.0)

        # Test Copula
        u = [0.1, 0.3, 0.5, 0.7, 0.9]
        v = [0.2, 0.4, 0.6, 0.8, 0.95]
        cop = vibe_quantlib.calculate_copula_dependence(u, v, "clayton")
        self.assertEqual(cop["family"], "clayton")
        self.assertIn("lambda_lower", cop)

        # Test HRP
        cov = np.array([[0.04, 0.01], [0.01, 0.09]])
        hrp = vibe_quantlib.calculate_hrp_weights(cov)
        self.assertEqual(len(hrp), 2)
        self.assertAlmostEqual(float(np.sum(hrp)), 1.0)

    def test_sovereign_intelligence(self):
        sov = SovereignIntelligencePlugin(max_equity_risk=0.01)
        df = pd.DataFrame([
            {"open": 1.1000 + i*0.0005, "high": 1.1010 + i*0.0005, "low": 1.0990 + i*0.0005, "close": 1.1005 + i*0.0005}
            for i in range(25)
        ])
        res = sov.analyze_market_signal("EURUSD", df, equity=10000.0)
        self.assertEqual(res["symbol"], "EURUSD")
        self.assertIn("recommended_lot", res)

    def test_mql_colab_engine(self):
        sltp = SLTPEngine()
        res = sltp.calculate_sl_tp("EURUSD", "BUY", 1.1000, 0.0015)
        self.assertLess(res["sl"], 1.1000)
        self.assertGreater(res["tp"], 1.1000)

        classifier = CandlestickAIClassifier()
        bars = [
            {"open": 1.1000, "high": 1.1010, "low": 1.0990, "close": 1.0995},
            {"open": 1.0990, "high": 1.1025, "low": 1.0985, "close": 1.1020},
        ]
        patterns = classifier.classify_bars(bars)
        self.assertIsInstance(patterns, list)

        lat = LatencyArbitrage()
        lat.record_tick("EURUSD", "LP1", 1.1005, 1000.0)
        lat.record_tick("EURUSD", "LP2", 1.1001, 1000.0)
        lead = lat.detect_lead_lag("EURUSD", "LP1", "LP2")
        self.assertIn("lead_lag", lead)

    def test_itip_signal_store(self):
        itip_signal_store.init_store()
        sig = {
            "timestamp": "2026-08-29 00:00:00",
            "symbol": "EURUSD",
            "timeframe": "M15",
            "direction": "BUY",
            "confidence": 88.5,
            "session": "LONDON",
            "atr": 0.0012,
            "rsi": 55.0,
        }
        rec = itip_signal_store.append_signal(sig)
        self.assertEqual(rec["symbol"], "EURUSD")
        signals = itip_signal_store.read_signals()
        self.assertIsInstance(signals, list)

    def test_bayesian_consensus_engine(self):
        engine = BayesianConsensusEngine()
        engine.set_strategy_reliability("SUPER_STRAT", 0.90)

        # Test default prior
        res0 = engine.get_consensus_decision("EURUSD")
        self.assertEqual(res0["decision"], "HOLD")
        self.assertAlmostEqual(res0["posterior_probability"], 0.5)

        # Update evidence with strong BUY
        post1 = engine.update_evidence("EURUSD", "SUPER_STRAT", "BUY", raw_prob=0.85)
        self.assertGreater(post1, 0.5)

        post2 = engine.update_evidence("EURUSD", "SUPER_STRAT", "BUY", raw_prob=0.90)
        self.assertGreater(post2, post1)

        res_final = engine.get_consensus_decision("EURUSD", buy_threshold=0.70)
        self.assertEqual(res_final["decision"], "BUY")

    def test_aat_strategy_brains(self):
        # Generate dummy bullish bars
        bars = []
        p = 1.1000
        for i in range(50):
            p += 0.0002
            bars.append({
                "open": p - 0.0001,
                "high": p + 0.0003,
                "low": p - 0.0003,
                "close": p,
                "time": 1700000000 + i * 3600
            })

        supertrend_sig = aat_strategies.evaluate_supertrend(bars)
        self.assertIn(supertrend_sig, ["BUY", "SELL", "HOLD"])

        donchian_sig = aat_strategies.evaluate_donchian_breakout(bars)
        self.assertIn(donchian_sig, ["BUY", "SELL", "HOLD"])

        rsi_sig = aat_strategies.evaluate_rsi_momentum(bars)
        self.assertIn(rsi_sig, ["BUY", "SELL", "HOLD"])

        wyckoff_sig = aat_strategies.evaluate_wyckoff_master(bars)
        self.assertIn(wyckoff_sig, ["BUY", "SELL", "HOLD"])

        ict_sig = aat_strategies.evaluate_ict_killzone(bars)
        self.assertIn(ict_sig, ["BUY", "SELL", "HOLD"])

    def test_aat_analyst_subsystem(self):
        macro = MacroAnalyst()
        macro.update_sentiment(0.80)
        weight = macro.get_impact_weight("EURUSD")
        self.assertEqual(weight, 1.15)

        # SMC Analyst
        smc = SMCAnalyst()
        df = pd.DataFrame([
            {"high": 1.10 + i*0.001, "low": 1.09 + i*0.001, "close": 1.095 + i*0.001}
            for i in range(20)
        ])
        struct = smc.detect_market_structure(df)
        self.assertIn("trend", struct)

        fvgs = smc.detect_fvg(df)
        self.assertIsInstance(fvgs, list)

        # Volatility Analyst
        vol = VolatilityAnalyst()
        regime = vol.get_regime(df)
        self.assertIn(regime, ["NORMAL", "TRENDING_FAST", "TRENDING_SLOW", "RANGING_TIGHT", "HIGH_VOLATILITY", "CRASH_SUDDEN", "SPIKE_SUDDEN"])

    def test_mcp_server_core(self):
        mcp = MCPServerCore()
        status = mcp.get_system_status()
        self.assertEqual(status["status"], "ONLINE")
        self.assertEqual(status["mcp_version"], "1.0")

        exec_res = mcp.execute_trade_command("EURUSD", "BUY", 0.05)
        self.assertTrue(exec_res["success"])
        self.assertEqual(exec_res["volume"], 0.05)

        intel = mcp.query_market_intel("EURUSD")
        self.assertEqual(intel["symbol"], "EURUSD")

if __name__ == "__main__":
    unittest.main()
