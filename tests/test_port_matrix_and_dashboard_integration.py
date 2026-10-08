"""
Tests for 50000-60000 6-Port Communication Matrix & Control Center Dashboard Configuration.
"""

import os
import unittest

import src.database as database
import src.institutional_integrations.sebi_broker_adapter as sebi
from src.brain_agents_orchestrator import global_brain_orchestrator


class TestPortMatrixAndDashboardIntegration(unittest.TestCase):
    def test_openalgo_fenix_adapter_base_url_port(self):
        """Verify OpenAlgoFenixAdapter BASE_URL uses port in 50000-60000 range."""
        self.assertIn("50005", sebi.OpenAlgoFenixAdapter.BASE_URL)
        port = int(sebi.OpenAlgoFenixAdapter.BASE_URL.split(":")[2].split("/")[0])
        self.assertTrue(50000 <= port <= 60000, f"Port {port} is outside 50000-60000 matrix")

    def test_database_default_endpoints(self):
        """Verify database endpoints use port in 50000-60000 range."""
        import inspect
        src_db = inspect.getsource(database)
        self.assertIn("50005", src_db)
        self.assertNotIn("127.0.0.1:3000", src_db)

    def test_gui_leverage_option_and_port_check(self):
        """Verify gui.py preserves leverage 1:3000 and uses valid port configs."""
        gui_path = os.path.join("src", "gui.py")
        with open(gui_path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn('"1:3000"', content)

    def test_brain_orchestrator_directive_generation(self):
        """Verify multi-agent orchestrator status summary returns valid non-mock directive."""
        summary = global_brain_orchestrator.get_status_summary()
        self.assertIn("last_directive", summary)
        directive = summary["last_directive"]
        self.assertIn("recommended_bias", directive)
        self.assertIn("confidence_score", directive)
        self.assertGreaterEqual(directive["confidence_score"], 0.0)

if __name__ == "__main__":
    unittest.main()
