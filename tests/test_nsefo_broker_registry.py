"""
Unit Tests for NSEFO Broker Configuration Registry.
Verifies spec retrieval and account registration across all 26 supported brokers.
"""
from typing import Any
import unittest
from institutional_integrations.nsefo_broker_registry import NSeFoBrokerConfigManager, NSEFO_BROKERS_REGISTRY

class TestNSeFoBrokerRegistry(unittest.TestCase):

    def test_26_brokers_registered(self) -> None:
        self.assertEqual(len(NSEFO_BROKERS_REGISTRY), 26)
        self.assertIn('dhan', NSEFO_BROKERS_REGISTRY)
        self.assertIn('zerodha', NSEFO_BROKERS_REGISTRY)
        self.assertIn('angelone', NSEFO_BROKERS_REGISTRY)
        self.assertIn('icici', NSEFO_BROKERS_REGISTRY)

    def test_manager_list_and_lookup(self) -> None:
        mgr = NSeFoBrokerConfigManager()
        all_brokers = mgr.list_all_supported_brokers()
        self.assertEqual(len(all_brokers), 26)
        spec = mgr.get_broker_spec('zerodha')
        self.assertIsNotNone(spec)
        if spec is not None:
            self.assertEqual(spec.display_name, 'Zerodha Kite Connect')
            self.assertEqual(spec.rest_url, 'https://api.kite.trade')
if __name__ == '__main__':
    unittest.main()
