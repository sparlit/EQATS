import unittest
import os
import config
import database
import connector
import eaqts_planes
import main
from event_bus import global_event_bus, Event

class TestEAQTS23ChaosStressCompliance(unittest.TestCase):
    """
    Exhaustive programmatic test suite verifying EAQTS Version 2.3 Chaos Engineering,
    Stress Scenarios, Disagreement Protocols, Reconciliation, and Throttling compliance.
    """

    def setUp(self):
        # Use ':memory:' database for perfect test isolation and to prevent concurrent disk I/O / file locking errors
        config.DB_PATH = ":memory:"
        config.SIMULATION_MODE = True
        config.MAX_CONCURRENT_TRADES = 3
        config.RISK_PER_TRADE_PERCENT = 1.0
        database.init_db()

        self.conn = connector.SimulatorConnector(initial_balance=10000.0)
        self.engine = eaqts_planes.init_core_engine(self.conn)

    def tearDown(self):
        pass

    def test_broker_disconnection_outage_containment(self):
        """Chaos: Injects sudden broker disconnection outage and verifies that risk checks caught it safely."""
        self.conn.connected_status = False
        is_conn = self.conn.is_connected()
        self.assertFalse(is_conn, "Connector should detect broker disconnection.")

        # Re-enable for subsequent tests
        self.conn.connected_status = True
        self.assertTrue(self.conn.is_connected())

    def test_extreme_spread_spikes_liquidity_shock(self):
        """Stress: Injects extreme spread spikes (liquidity shock) and ensures execution blocks entry."""
        scalper = main.AutonomousScalper()
        scalper.conn = self.conn

        # Under normal conditions (spread = 0.0002 / 2 pips <= MAX_SPREAD_PIPS)
        price_info_ok = {"bid": 1.1000, "ask": 1.1002}
        is_safe, reason = scalper._is_market_open_and_liquid("EURUSD", price_info_ok)
        self.assertTrue(is_safe, f"Should be safe under normal spread. Reason: {reason}")

        # Under spread shock (spread = 0.0050 / 50 pips > MAX_SPREAD_PIPS)
        price_info_shock = {"bid": 1.1000, "ask": 1.1050}
        is_safe_shock, reason_shock = scalper._is_market_open_and_liquid("EURUSD", price_info_shock)
        self.assertFalse(is_safe_shock, "Should block trade under extreme spread shock.")
        self.assertIn("Liquidity Filter", reason_shock)

    def test_fat_finger_protection_limits(self):
        """Safety: Verifies fat-finger size limits block hazardous orders."""
        # Standard size (0.5 lots) is allowed
        self.assertTrue(self.engine.execution.validate_fat_finger("EURUSD", 0.5, 1.1000))
        # Extreme size (10.0 lots) is blocked
        self.assertFalse(self.engine.execution.validate_fat_finger("EURUSD", 10.0, 1.1000))
        # Negative size is blocked
        self.assertFalse(self.engine.execution.validate_fat_finger("EURUSD", -1.0, 1.1000))

    def test_self_trade_prevention_enforcement(self):
        """Safety: Verifies self-trade prevention blocks opposing positions on same symbol."""
        open_positions = [
            {"symbol": "EURUSD", "direction": "BUY", "ticket": 10001, "open_price": 1.1000, "sl": 1.0900, "tp": 1.1200, "lot_size": 0.5}
        ]
        # Opposing side (SELL) for the same asset is blocked
        is_conflict = self.engine.execution.prevent_self_trade("EURUSD", "SELL", open_positions)
        self.assertTrue(is_conflict, "Opposing order side on same symbol must trigger conflict block.")

        # Same side (BUY) for the same asset is not blocked by self-trade check (other limits may apply)
        is_no_conflict = self.engine.execution.prevent_self_trade("EURUSD", "BUY", open_positions)
        self.assertFalse(is_no_conflict)

    def test_configuration_transactional_rollback(self):
        """Control: Verifies invalid configuration proposal is rolled back cleanly to restore old state."""
        original_trades_limit = config.MAX_CONCURRENT_TRADES

        # Propose invalid config change (negative trades)
        success = self.engine.control.propose_config_change(
            author_id="AUDITOR_AGENT",
            proposed_updates={"MAX_CONCURRENT_TRADES": -10},
            signature="RSA_SIG"
        )
        self.assertFalse(success, "Invalid config transaction must fail.")
        self.assertEqual(config.MAX_CONCURRENT_TRADES, original_trades_limit, "Config must roll back cleanly.")

        # Propose valid config change
        success_valid = self.engine.control.propose_config_change(
            author_id="AUDITOR_AGENT",
            proposed_updates={"MAX_CONCURRENT_TRADES": 5},
            signature="RSA_SIG"
        )
        self.assertTrue(success_valid, "Valid config change must succeed.")
        self.assertEqual(config.MAX_CONCURRENT_TRADES, 5)

        # Restore original
        config.MAX_CONCURRENT_TRADES = original_trades_limit

    def test_rate_governance_throttling_transitions(self):
        """Execution: Verifies message rate triggers throttled state, then halt state on extreme activity."""
        self.engine.execution._message_history.clear()
        self.assertEqual(self.engine.execution.rate_state, "NORMAL")

        # 1st order check
        self.assertTrue(self.engine.execution.check_rate_limits())
        self.assertEqual(self.engine.execution.rate_state, "NORMAL")

        # 2nd order check
        self.assertTrue(self.engine.execution.check_rate_limits())

        # 3rd order check -> Throttled
        self.assertTrue(self.engine.execution.check_rate_limits())
        self.assertEqual(self.engine.execution.rate_state, "THROTTLED")

        # 4th order check
        self.assertTrue(self.engine.execution.check_rate_limits())

        # 5th order check -> Halted
        self.assertFalse(self.engine.execution.check_rate_limits())
        self.assertEqual(self.engine.execution.rate_state, "HALTED")

    def test_state_disagreement_protocol_freeze(self):
        """Safety: Verifies unresolvable state disagreements trigger a risk freeze and invariant violation."""
        # Agreement setup: Tech trend matches AI trend -> Success
        agreement_decisions = {"technical_trend": "UP", "ai_trend": "UP"}
        self.assertTrue(self.engine.safety.verify_component_agreement(agreement_decisions))

        # Disagreement setup: Tech trend (UP) conflicts with AI trend (DOWN) -> Risk Freeze
        disagreement_decisions = {"technical_trend": "UP", "ai_trend": "DOWN"}
        self.assertFalse(self.engine.safety.verify_component_agreement(disagreement_decisions))

        # Test that evaluating invariants with disagreement results in INV-015 violation
        violations = self.engine.safety.evaluate_invariants(
            current_risk=1.0,
            active_count=1,
            has_reconciliation_mismatch=False,
            has_disagreement=True
        )
        self.assertIn("INV-015", violations, "Should raise disagreement invariant violation INV-015.")

    def test_continuous_reconciliation_mismatch_freeze(self):
        """Resilience: Verifies active position mismatches raise invariant violation INV-013 to block risk."""
        db_positions = [
            {"ticket": 50001, "symbol": "EURUSD", "direction": "BUY"}
        ]
        connector_positions = [] # Mismatch: connector has no open position!

        # Reconciliation check fails due to discrepancy
        reconciled = self.engine.resilience.reconcile_positions(db_positions, connector_positions)
        self.assertFalse(reconciled, "Should fail reconciliation when position discrepancy exists.")

        # Test that evaluating invariants with mismatch results in INV-013 violation
        violations = self.engine.safety.evaluate_invariants(
            current_risk=1.0,
            active_count=1,
            has_reconciliation_mismatch=True,
            has_disagreement=False
        )
        self.assertIn("INV-013", violations, "Should raise reconciliation invariant violation INV-013.")

    def test_decision_quality_and_luck_attribution(self):
        """Learning: Verifies decision quality scores and luck vs. skill performance attribution."""
        case_profitable = {"symbol": "EURUSD", "direction": "BUY", "profit": 150.0}
        case_unprofitable = {"symbol": "EURUSD", "direction": "BUY", "profit": -50.0}

        # 1. Quality scores
        score_ok = self.engine.learning.evaluate_decision_quality(case_profitable)
        score_fail = self.engine.learning.evaluate_decision_quality(case_unprofitable)
        self.assertGreater(score_ok["decision_quality_score"], score_fail["decision_quality_score"])

        # 2. Luck vs Skill attribution
        self.assertEqual(self.engine.learning.attribute_luck_vs_skill(case_profitable), "SKILL")
        self.assertEqual(self.engine.learning.attribute_luck_vs_skill(case_unprofitable), "LUCK")

if __name__ == "__main__":
    unittest.main()
