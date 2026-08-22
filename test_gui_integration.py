"""
GUI Integration Tests for gui.py (Round 5).
Validates GUI data flows, screen update handlers, calculations, and event logic.
Handles environments without native Tkinter installed via mock stubs.
"""

import sys
import unittest.mock as mock

# Stub tkinter if not available in headless environment
try:
    import tkinter as tk
except ModuleNotFoundError:

    class DummyWidget:
        def __init__(self, *args, **kwargs):
            pass

        def pack(self, *args, **kwargs):
            pass

        def grid(self, *args, **kwargs):
            pass

        def place(self, *args, **kwargs):
            pass

        def config(self, *args, **kwargs):
            pass

        def configure(self, *args, **kwargs):
            pass

        def bind(self, *args, **kwargs):
            pass

        def winfo_children(self):
            return []

        def winfo_width(self):
            return 500

        def winfo_height(self):
            return 400

        def delete(self, *args, **kwargs):
            pass

        def insert(self, *args, **kwargs):
            pass

        def see(self, *args, **kwargs):
            pass

        def get(self):
            return ""

        def __getitem__(self, item):
            return DummyWidget()

        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    tk = mock.MagicMock()
    tk.Tk = DummyWidget
    tk.Toplevel = DummyWidget
    tk.Frame = DummyWidget
    tk.Label = DummyWidget
    tk.Button = DummyWidget
    tk.Entry = DummyWidget
    tk.Text = DummyWidget
    tk.Canvas = DummyWidget
    tk.OptionMenu = DummyWidget
    tk.StringVar = mock.MagicMock
    tk.BooleanVar = mock.MagicMock
    tk.DISABLED = "disabled"
    tk.NORMAL = "normal"
    tk.END = "end"
    tk.WORD = "word"
    tk.FLAT = "flat"
    tk.SOLID = "solid"
    tk.BOTH = "both"
    tk.X = "x"
    tk.Y = "y"
    tk.LEFT = "left"
    tk.RIGHT = "right"
    tk.CENTER = "center"
    tk.TOP = "top"
    tk.BOTTOM = "bottom"
    tk.W = "w"

    ttk = mock.MagicMock()
    ttk.Style = DummyWidget
    ttk.Treeview = DummyWidget
    ttk.Notebook = DummyWidget
    ttk.Scrollbar = DummyWidget

    messagebox = mock.MagicMock()

    sys.modules["tkinter"] = tk
    sys.modules["tkinter.ttk"] = ttk
    sys.modules["tkinter.messagebox"] = messagebox

import config
import database


def test_gui_module_imports_and_logger():
    """Verifies gui module import and logger configuration."""
    import gui

    assert hasattr(gui, "ScalperGui")
    assert hasattr(gui, "_log")
    assert gui._log.name == "gui"


def test_gui_data_flow_updates_without_display():
    """Tests GUI data flow methods and database bindings without requiring a physical X display."""
    database.init_db()

    mock_root = mock.MagicMock()
    mock_scalper = mock.MagicMock()

    # Mock _show_login_dialog to return True so initialization proceeds
    with mock.patch("gui.ScalperGui._show_login_dialog", return_value=True):
        with mock.patch("main.AutonomousScalper", return_value=mock_scalper):
            import gui

            app = gui.ScalperGui(mock_root)

            # Test strategy and style change handlers
            app.on_strategy_change("BREAKOUT")
            assert config.ACTIVE_STRATEGY == "BREAKOUT"

            app.on_style_change("SWING_TRADING")
            assert config.TRADING_STYLE == "SWING_TRADING"

            # Test mode toggle
            initial_sim = config.SIMULATION_MODE
            app.toggle_mode()
            assert config.SIMULATION_MODE != initial_sim
            app.toggle_mode()  # Reset back

            # Test calculation helpers
            app.ent_mkt_loss_pct = mock.MagicMock()
            app.ent_mkt_loss_pct.get.return_value = "20.0"
            app.lbl_mkt_recovery_result = mock.MagicMock()
            app._calc_gain_loss_recovery()

            # Test position size calculator
            app.ent_mkt_ps_bal = mock.MagicMock()
            app.ent_mkt_ps_bal.get.return_value = "10000"
            app.ent_mkt_ps_risk = mock.MagicMock()
            app.ent_mkt_ps_risk.get.return_value = "1.0"
            app.ent_mkt_ps_sl = mock.MagicMock()
            app.ent_mkt_ps_sl.get.return_value = "20.0"
            app.lbl_mkt_ps_result = mock.MagicMock()
            app._calc_position_size()


def test_gui_screen_data_update_handlers():
    """Tests screen update methods for DOM, Whale, and Market screens under mocked GUI components."""
    database.init_db()
    mock_root = mock.MagicMock()
    mock_scalper = mock.MagicMock()
    mock_scalper.conn.get_current_price.return_value = {"bid": 1.1000, "ask": 1.1002}
    mock_scalper.conn.get_historical_ticks.return_value = [
        {"bid": 1.1000, "ask": 1.1002, "volume": 15},
        {"bid": 1.1001, "ask": 1.1003, "volume": 20},
    ]

    with mock.patch("gui.ScalperGui._show_login_dialog", return_value=True):
        with mock.patch("main.AutonomousScalper", return_value=mock_scalper):
            import gui

            app = gui.ScalperGui(mock_root)

            # DOM screen data update
            app.dom_tree = mock.MagicMock()
            app.dom_canvas = mock.MagicMock()
            app.dom_canvas.winfo_width.return_value = 300
            app.dom_canvas.winfo_height.return_value = 200
            app._update_dom_screen_data()

            # Whale screen data update
            app.whale_tree = mock.MagicMock()
            app.lbl_whale_funding = mock.MagicMock()
            app.lbl_whale_liq = mock.MagicMock()
            app._update_whale_screen_data()


def test_gui_poly_screen_switch_and_update():
    """Tests POLY <GO> Polymarket screen switching, panel creation, and telemetry updating."""
    database.init_db()

    mock_root = mock.MagicMock()
    mock_scalper = mock.MagicMock()
    mock_scalper.conn.get_account_info.return_value = {"balance": 15000.0, "equity": 15250.0}
    mock_scalper.conn.get_open_orders.return_value = [{"symbol": "BTCUSD", "direction": "BUY"}]

    with mock.patch("gui.ScalperGui._show_login_dialog", return_value=True):
        with mock.patch("main.AutonomousScalper", return_value=mock_scalper):
            import gui

            app = gui.ScalperGui(mock_root)
            app.switch_to_screen("POLY")
            assert app.active_screen == "POLY"
            assert hasattr(app, "lbl_poly_pnl_val")

            app._update_poly_screen_data()
            assert app.lbl_poly_pnl_val is not None
