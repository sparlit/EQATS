import datetime
import importlib.util
import zoneinfo

import numpy as np

# Dynamically import modules/adapted/nse-observer/utils.py
spec = importlib.util.spec_from_file_location(
    "nse_observer_utils", "modules/adapted/nse-observer/utils.py"
)
assert spec is not None and spec.loader is not None
nse_observer_utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nse_observer_utils)

RandomField = nse_observer_utils.RandomField
is_ist_market_session_active = nse_observer_utils.is_ist_market_session_active
round_to_ist_tick = nse_observer_utils.round_to_ist_tick


class TestNSEObserverUtils:
    def test_random_field_initialization_and_shapes(self):
        rf = RandomField(l_dom=2 * np.pi, N_cells=32, N_modes=16, kappa_peak=8, Q=1e-8, seed=42)
        assert rf.psi.shape == (32, 32)
        assert rf.u.shape == (32, 32)
        assert rf.v.shape == (32, 32)
        assert rf.psi.dtype == np.float64
        assert rf.u.dtype == np.float64
        assert rf.v.dtype == np.float64

    def test_random_field_deterministic_seeding(self):
        rf1 = RandomField(l_dom=2 * np.pi, N_cells=16, N_modes=8, seed=100)
        rf2 = RandomField(l_dom=2 * np.pi, N_cells=16, N_modes=8, seed=100)
        np.testing.assert_array_equal(rf1.psi, rf2.psi)
        np.testing.assert_array_equal(rf1.u, rf2.u)
        np.testing.assert_array_equal(rf1.v, rf2.v)

    def test_round_to_ist_tick(self):
        assert round_to_ist_tick(0.0) == 0.0
        assert round_to_ist_tick(-10.5) == 0.0
        assert round_to_ist_tick(100.02) == 100.00
        assert round_to_ist_tick(100.03) == 100.05
        assert round_to_ist_tick(100.08) == 100.10

    def test_is_ist_market_session_active(self):
        ist = zoneinfo.ZoneInfo("Asia/Kolkata")
        # Monday 10:00 AM IST (during market session)
        mon_market = datetime.datetime(2026, 10, 12, 10, 0, 0, tzinfo=ist)
        assert is_ist_market_session_active(mon_market) is True

        # Monday 08:00 AM IST (before market open)
        mon_early = datetime.datetime(2026, 10, 12, 8, 0, 0, tzinfo=ist)
        assert is_ist_market_session_active(mon_early) is False

        # Saturday 11:00 AM IST (weekend)
        sat_market = datetime.datetime(2026, 10, 17, 11, 0, 0, tzinfo=ist)
        assert is_ist_market_session_active(sat_market) is False
