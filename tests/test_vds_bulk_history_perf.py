"""
Performance benchmark and unit tests for bulk history retrieval in VDS screen.
"""

import time
from unittest import mock

import database
from connector import SimulatorConnector
from gui import ScalperGui


def test_bulk_history_simulator_connector():
    """Verify that SimulatorConnector.get_bulk_history returns expected data correctly."""
    sim = SimulatorConnector()
    symbols = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BTCUSD", "ETHUSD", "LTCUSD", "XRPUSD"]

    # Measure individual get_history timing
    start_indiv = time.perf_counter()
    indiv_res = {s: sim.get_history(s, 10) for s in symbols}
    indiv_duration = time.perf_counter() - start_indiv

    # Measure get_bulk_history timing
    start_bulk = time.perf_counter()
    bulk_res = sim.get_bulk_history(symbols, 10)
    bulk_duration = time.perf_counter() - start_bulk

    assert len(bulk_res) == len(symbols)
    for s in symbols:
        assert len(bulk_res[s]) == 10
        assert bulk_res[s] == indiv_res[s]

    print(
        f"\n[BENCHMARK] get_history x{len(symbols)}: {indiv_duration * 1000:.3f}ms | "
        f"get_bulk_history: {bulk_duration * 1000:.3f}ms"
    )


def test_gui_vds_screen_bulk_history_call():
    """Verify that ScalperGui._show_vds_screen calls get_bulk_history once instead of N times."""
    database.init_db()
    mock_scalper = mock.MagicMock()

    sim = SimulatorConnector()
    mock_scalper.conn = sim

    with (
        mock.patch("gui.ttk.Style"),
        mock.patch("gui.tk.StringVar"),
        mock.patch("gui.tk.OptionMenu"),
        mock.patch("gui.messagebox"),
        mock.patch("gui.ScalperGui._show_login_dialog", return_value=True),
        mock.patch("main.AutonomousScalper", return_value=mock_scalper),
    ):
        gui = ScalperGui.__new__(ScalperGui)
        gui.scalper = mock_scalper
        gui.selected_symbol_gp = "EURUSD"
        gui.bg_dark = "#000000"
        gui.bg_card = "#121212"
        gui.fg_accent = "#ff9900"
        gui.fg_cyan = "#00ffff"
        gui.fg_green = "#00ff00"
        gui.fg_red = "#ff3333"
        gui.fg_grey = "#888888"

        # Spy on get_bulk_history
        with mock.patch.object(sim, "get_bulk_history", wraps=sim.get_bulk_history) as spy_bulk:
            gui.screen_frame = mock.MagicMock()
            gui._show_vds_screen()  # pylint: disable=protected-access

            # Check get_bulk_history was called once instead of 9 individual get_history calls
            assert spy_bulk.call_count == 1
            requested_symbols = spy_bulk.call_args[0][0]
            assert "EURUSD" in requested_symbols
            assert len(requested_symbols) == 9
