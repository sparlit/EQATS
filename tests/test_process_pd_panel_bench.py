"""
Unit tests for modules/adapted/tickdownload/process_pd_panel_bench.py
Verifies ProfileContext context manager, panel bench helper functions, and ProcessPandasPanelBench.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Mock tickerplot before importing process_pd_panel_bench
mock_sqla = MagicMock()
mock_tickerplot_wrapper = MagicMock()

sys.modules.setdefault("sqlalchemy", mock_sqla)
sys.modules.setdefault("tickerplot", MagicMock())
sys.modules.setdefault("tickerplot.sql", MagicMock())
sys.modules.setdefault("tickerplot.sql.sqlalchemy_wrapper", mock_tickerplot_wrapper)

# Add modules/adapted/tickdownload to path for import compatibility
tickdownload_dir = str(
    Path(__file__).resolve().parent.parent / "modules" / "adapted" / "tickdownload"
)
if tickdownload_dir not in sys.path:
    sys.path.insert(0, tickdownload_dir)

import modules.adapted.tickdownload.process_pd_panel_bench as bench_module  # noqa: E402


def test_profile_context_manager():
    """Test that ProfileContext executes code block, tracks elapsed time, and populates stats."""
    with bench_module.ProfileContext(sort_by="cumulative", print_fraction=0.1) as prof:
        # Perform some dummy computation
        total = sum(i * i for i in range(1000))

    assert total == 332833500
    assert prof.elapsed_time >= 0.0
    assert prof.stats is not None
    assert isinstance(prof.stats_output, str)


def test_is_ist_market_session_active():
    """Test market session helper for IST time."""
    import datetime

    import pytz

    ist = pytz.timezone("Asia/Kolkata")
    # A Wednesday at 10:00 AM IST
    weekday_active = datetime.datetime(2025, 1, 15, 10, 0, 0, tzinfo=ist)
    assert bench_module.is_ist_market_session_active(weekday_active) is True

    # Saturday
    weekend_dt = datetime.datetime(2025, 1, 18, 10, 0, 0, tzinfo=ist)
    assert bench_module.is_ist_market_session_active(weekend_dt) is False


def test_round_to_ist_tick():
    """Test price tick rounding function."""
    assert bench_module.round_to_ist_tick(100.03) == 100.05
    assert bench_module.round_to_ist_tick(100.02) == 100.00
    assert bench_module.round_to_ist_tick(-1.0) == 0.0


def test_process_pandas_panel_bench_init_and_set_method():
    """Test initialization and method validation in ProcessPandasPanelBench."""
    bench = bench_module.ProcessPandasPanelBench(
        method="cProfile", limit_rows=10, db_path="sqlite:///:memory:"
    )
    assert bench.method_name == "cProfile"
    assert bench.limit_rows == 10

    bench.set_method("cProfile")
    assert bench.method_name == "cProfile"

    bench.set_method("cprofile")
    assert bench.method_name == "cprofile"

    with pytest.raises(ValueError, match="Method name should be 'cProfile'"):
        bench.set_method("invalid_method")


def test_run_bench_cprofile():
    """Test run_bench_cprofile with mocked panel benchmark functions."""
    bench = bench_module.ProcessPandasPanelBench(limit_rows=5, db_path="sqlite:///:memory:")
    fake_panel = {"STOCK1": {"close": [10.0, 12.0]}}

    with (
        patch(
            "modules.adapted.tickdownload.process_pd_panel_bench.panel_bench_lc",
            return_value=[True],
        ) as mock_lc,
        patch(
            "modules.adapted.tickdownload.process_pd_panel_bench.panel_bench_vector",
            return_value=["STOCK1"],
        ) as mock_vec,
    ):
        bench.run_bench_cprofile(fake_panel)
        mock_lc.assert_called_once_with(panel=fake_panel)
        mock_vec.assert_called_once_with(panel=fake_panel)
