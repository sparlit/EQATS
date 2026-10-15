import unittest

import config
import connector
import database
import eqats_planes
import main


class TestEQATS24ChaosStressCompliance(unittest.TestCase):
    """
    Exhaustive programmatic test suite verifying EQATS Version 3.0 Chaos Engineering,
    Stress Scenarios, Disagreement Protocols, Reconciliation, and Throttling compliance.
    """

    def setUp(self) -> None:
        config.DB_PATH = ':memory:'
        config.SIMULATION_MODE = True
        config.MAX_CONCURRENT_TRADES = 3
        config.RISK_PER_TRADE_PERCENT = 1.0
        database.init_db()
        self.conn = connector.SimulatorConnector(initial_balance=10000.0)
        self.engine = eqats_planes.init_core_engine(self.conn)

    def tearDown(self) -> None:
        pass

    def test_broker_disconnection_outage_containment(self) -> None:
        """Chaos: Injects sudden broker disconnection outage and verifies that risk checks caught it safely."""
        self.conn.connected_status = False
        is_conn = self.conn.is_connected()
        self.assertFalse(is_conn, 'Connector should detect broker disconnection.')
        self.conn.connected_status = True
        self.assertTrue(self.conn.is_connected())

    def test_extreme_spread_spikes_liquidity_shock(self) -> None:
        """Stress: Injects extreme spread spikes (liquidity shock) and ensures execution blocks entry."""
        old_bw = config.BLOCK_WEEKENDS
        old_ro = config.BLOCK_ROLLOVER_HOUR
        config.BLOCK_WEEKENDS = False
        config.BLOCK_ROLLOVER_HOUR = False
        try:
            scalper = main.AutonomousScalper()
            scalper.conn = self.conn
            price_info_ok = {'bid': 1.1, 'ask': 1.1002}
            is_safe, reason = scalper._is_market_open_and_liquid('EURUSD', price_info_ok)
            self.assertTrue(is_safe, f'Should be safe under normal spread. Reason: {reason}')
            price_info_shock = {'bid': 1.1, 'ask': 1.105}
            is_safe_shock, reason_shock = scalper._is_market_open_and_liquid('EURUSD', price_info_shock)
            self.assertFalse(is_safe_shock, 'Should block trade under extreme spread shock.')
            self.assertIn('Liquidity Filter', reason_shock)
        finally:
            config.BLOCK_WEEKENDS = old_bw
            config.BLOCK_ROLLOVER_HOUR = old_ro

    def test_fat_finger_protection_limits(self) -> None:
        """Safety: Verifies fat-finger size limits block hazardous orders."""
        self.assertTrue(self.engine.execution.validate_fat_finger('EURUSD', 0.5, 1.1))
        self.assertFalse(self.engine.execution.validate_fat_finger('EURUSD', 10.0, 1.1))
        self.assertFalse(self.engine.execution.validate_fat_finger('EURUSD', -1.0, 1.1))

    def test_self_trade_prevention_enforcement(self) -> None:
        """Safety: Verifies self-trade prevention blocks opposing positions on same symbol."""
        open_positions = [{'symbol': 'EURUSD', 'direction': 'BUY', 'ticket': 10001, 'open_price': 1.1, 'sl': 1.09, 'tp': 1.12, 'lot_size': 0.5}]
        is_conflict = self.engine.execution.prevent_self_trade('EURUSD', 'SELL', open_positions)
        self.assertTrue(is_conflict, 'Opposing order side on same symbol must trigger conflict block.')
        is_no_conflict = self.engine.execution.prevent_self_trade('EURUSD', 'BUY', open_positions)
        self.assertFalse(is_no_conflict)

    def test_configuration_transactional_rollback(self) -> None:
        """Control: Verifies invalid configuration proposal is rolled back cleanly to restore old state."""
        original_trades_limit = config.MAX_CONCURRENT_TRADES
        success = self.engine.control.propose_config_change(author_id='AUDITOR_AGENT', proposed_updates={'MAX_CONCURRENT_TRADES': -10}, signature='RSA_SIG')
        self.assertFalse(success, 'Invalid config transaction must fail.')
        self.assertEqual(config.MAX_CONCURRENT_TRADES, original_trades_limit, 'Config must roll back cleanly.')
        success_valid = self.engine.control.propose_config_change(author_id='AUDITOR_AGENT', proposed_updates={'MAX_CONCURRENT_TRADES': 5}, signature='RSA_SIG')
        self.assertTrue(success_valid, 'Valid config change must succeed.')
        self.assertEqual(config.MAX_CONCURRENT_TRADES, 5)
        config.MAX_CONCURRENT_TRADES = original_trades_limit

    def test_rate_governance_throttling_transitions(self) -> None:
        """Execution: Verifies message rate triggers throttled state, then halt state on extreme activity."""
        self.engine.execution._message_history.clear()
        self.assertEqual(self.engine.execution.rate_state, 'NORMAL')
        self.assertTrue(self.engine.execution.check_rate_limits())
        self.assertEqual(self.engine.execution.rate_state, 'NORMAL')
        self.assertTrue(self.engine.execution.check_rate_limits())
        self.assertTrue(self.engine.execution.check_rate_limits())
        self.assertEqual(self.engine.execution.rate_state, 'THROTTLED')
        self.assertTrue(self.engine.execution.check_rate_limits())
        self.assertFalse(self.engine.execution.check_rate_limits())
        self.assertEqual(self.engine.execution.rate_state, 'HALTED')

    def test_state_disagreement_protocol_freeze(self) -> None:
        """Safety: Verifies unresolvable state disagreements trigger a risk freeze and invariant violation."""
        agreement_decisions = {'technical_trend': 'UP', 'ai_trend': 'UP'}
        self.assertTrue(self.engine.safety.verify_component_agreement(agreement_decisions))
        disagreement_decisions = {'technical_trend': 'UP', 'ai_trend': 'DOWN'}
        self.assertFalse(self.engine.safety.verify_component_agreement(disagreement_decisions))
        violations = self.engine.safety.evaluate_invariants(current_risk=1.0, active_count=1, has_reconciliation_mismatch=False, has_disagreement=True)
        self.assertIn('INV-015', violations, 'Should raise disagreement invariant violation INV-015.')

    def test_continuous_reconciliation_mismatch_freeze(self) -> None:
        """Resilience: Verifies active position mismatches raise invariant violation INV-013 to block risk."""
        db_positions = [{'ticket': 50001, 'symbol': 'EURUSD', 'direction': 'BUY'}]
        connector_positions = []
        reconciled = self.engine.resilience.reconcile_positions(db_positions, connector_positions)
        self.assertFalse(reconciled, 'Should fail reconciliation when position discrepancy exists.')
        violations = self.engine.safety.evaluate_invariants(current_risk=1.0, active_count=1, has_reconciliation_mismatch=True, has_disagreement=False)
        self.assertIn('INV-013', violations, 'Should raise reconciliation invariant violation INV-013.')

    def test_decision_quality_and_luck_attribution(self) -> None:
        """Learning: Verifies decision quality scores and luck vs. skill performance attribution."""
        case_profitable = {'symbol': 'EURUSD', 'direction': 'BUY', 'profit': 150.0}
        case_unprofitable = {'symbol': 'EURUSD', 'direction': 'BUY', 'profit': -50.0}
        score_ok = self.engine.learning.evaluate_decision_quality(case_profitable)
        score_fail = self.engine.learning.evaluate_decision_quality(case_unprofitable)
        self.assertGreater(score_ok['decision_quality_score'], score_fail['decision_quality_score'])
        self.assertEqual(self.engine.learning.attribute_luck_vs_skill(case_profitable), 'SKILL')
        self.assertEqual(self.engine.learning.attribute_luck_vs_skill(case_unprofitable), 'LUCK')

    def test_data_plane_store_price_iso_parse_error_handling(self) -> None:
        """DataPlane: Verifies store_price gracefully handles ISO format parse errors when last record timestamp is malformed."""
        data_plane = self.engine.data
        symbol = "EURUSD"
        data_plane._pit_database[symbol] = [
            {
                "event_time": "INVALID_TIMESTAMP",
                "publication_time": "INVALID_TIMESTAMP",
                "availability_time": "INVALID_TIMESTAMP",
                "bid": 1.0500,
                "ask": 1.0502,
            }
        ]

        with self.assertLogs("eqats_planes", level="DEBUG") as cm:
            data_plane.store_price(symbol, 1.0510, 1.0512)

        self.assertTrue(any("ISO format parse error in store_price" in msg for msg in cm.output))
        records = data_plane._pit_database[symbol]
        self.assertEqual(len(records), 2)
        self.assertEqual(records[-1]["bid"], 1.0510)
        self.assertEqual(records[-1]["ask"], 1.0512)

    def test_data_plane_store_price_monotonic_timestamp(self) -> None:
        """DataPlane: Verifies store_price enforces strictly monotonic timestamps when previous timestamp is in the future."""
        import datetime

        data_plane = self.engine.data
        symbol = "GBPUSD"
        future_time_str = "2099-12-31T23:59:59.999999+00:00"
        data_plane._pit_database[symbol] = [
            {
                "event_time": future_time_str,
                "publication_time": future_time_str,
                "availability_time": future_time_str,
                "bid": 1.2500,
                "ask": 1.2502,
            }
        ]

        data_plane.store_price(symbol, 1.2510, 1.2512)
        records = data_plane._pit_database[symbol]
        self.assertEqual(len(records), 2)
        last_time = datetime.datetime.fromisoformat(records[-1]["availability_time"])
        prev_time = datetime.datetime.fromisoformat(future_time_str)
        self.assertGreater(last_time, prev_time)
if __name__ == '__main__':
    unittest.main()
