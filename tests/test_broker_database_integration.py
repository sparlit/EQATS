"""
Unit Tests for Broker Parameter Database & Universal Gateway Integration.
Verifies database table creation, default profile seeding, profile lookup, and runtime constraint integration.
"""

import unittest
from typing import Any

import database
from institutional_integrations.universal_broker_adapter import UniversalBrokerGateway


class TestBrokerDatabaseIntegration(unittest.TestCase):
    def setUp(self) -> None:
        database.init_db()
        database.seed_default_broker_profiles()

    def test_seed_default_broker_profiles(self) -> None:
        profiles = database.get_all_broker_profiles()
        self.assertGreaterEqual(len(profiles), 20)
        keys = [p["broker_key"] for p in profiles]
        self.assertIn("dhan", keys)
        self.assertIn("zerodha", keys)
        self.assertIn("binance_perps", keys)
        self.assertIn("mt5_demo", keys)

    def test_get_and_add_broker_profile(self) -> None:
        z_profile = database.get_broker_profile("zerodha")
        self.assertIsNotNone(z_profile)
        if z_profile:
            self.assertEqual(z_profile["display_name"], "Zerodha Kite Connect")
            self.assertEqual(z_profile["protocol_type"], "REST_WS")
        database.add_broker_profile(
            broker_key="custom_prop_broker",
            display_name="Custom Prop Broker",
            protocol_type="REST_WS",
            auth_type="api_key_secret",
            rest_url="https://api.customprop.com",
            volume_min=0.1,
            volume_max=500.0,
            volume_step=0.1,
        )
        custom = database.get_broker_profile("custom_prop_broker")
        self.assertIsNotNone(custom)
        if custom:
            self.assertEqual(custom["display_name"], "Custom Prop Broker")
            self.assertEqual(custom["volume_min"], 0.1)
            self.assertEqual(custom["volume_max"], 500.0)

    def test_universal_gateway_uses_broker_database_constraints(self) -> None:
        gw = UniversalBrokerGateway(
            protocol="CCXT", broker_config={"server": "binance_perps", "rest_url": "https://fapi.binance.com"},
        )
        constraints = gw.get_symbol_volume_constraints("BTCUSDT")
        self.assertEqual(constraints["volume_min"], 0.001)
        self.assertEqual(constraints["volume_max"], 1000.0)
        self.assertEqual(constraints["volume_step"], 0.001)


if __name__ == "__main__":
    unittest.main()
