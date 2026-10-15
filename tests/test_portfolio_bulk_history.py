import time
from unittest import mock

import connector
import database
import gui


def test_get_bulk_history_simulator() -> None:
    """Tests bulk history fetching on SimulatorConnector."""
    sim = connector.SimulatorConnector()
    assets = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BTCUSD"]
    res = sim.get_bulk_history(assets, 30)
    assert isinstance(res, dict)
    assert len(res) == len(assets)
    for sym in assets:
        assert sym in res
        assert isinstance(res[sym], list)
        assert len(res[sym]) <= 30


def test_get_bulk_history_concurrent() -> None:
    """Tests TradingConnector default get_bulk_history concurrent behavior and performance improvement over sequential calls."""

    class SlowConnector(connector.TradingConnector):

        def connect(self) -> None:
            pass

        def is_connected(self) -> bool:
            return True

        def disconnect(self) -> None:
            pass

        def get_account_info(self) -> dict:
            return {}

        def get_history(self, symbol: str, count: int) -> list:
            time.sleep(0.05)  # Simulate 50ms latency per query
            return [{"close": 1.0 + i * 0.01} for i in range(count)]

        def get_current_price(self, symbol: str) -> dict:
            return {"bid": 1.0, "ask": 1.0002}

        def get_symbol_volume_constraints(self, symbol: str) -> dict:
            return {}

        def execute_order(
            self, symbol: str, order_type: str, lot_size: float, sl: float, tp: float, product: str = None
        ) -> dict:
            return {}

        def close_order(self, ticket: str, reason: str = "MANUAL") -> dict:
            return {}

        def modify_order(self, ticket: str, sl: float, tp: float) -> bool:
            return True

        def get_open_orders(self) -> list:
            return []

        def draw_dashboard(self, symbol: str, data: dict) -> None:
            pass

    conn = SlowConnector()
    assets = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BTCUSD"]

    # Measure sequential time
    t0 = time.perf_counter()
    seq_results = {sym: conn.get_history(sym, 30) for sym in assets}
    t_seq = time.perf_counter() - t0

    # Measure bulk concurrent time
    t1 = time.perf_counter()
    bulk_results = conn.get_bulk_history(assets, 30)
    t_bulk = time.perf_counter() - t1

    assert bulk_results == seq_results
    assert len(bulk_results) == 5
    # Bulk concurrent execution should be significantly faster than sequential (e.g. ~0.05s vs ~0.25s)
    assert t_bulk < t_seq
    speedup = t_seq / max(t_bulk, 0.0001)
    print(
        f"\n[BENCHMARK RESULT] Sequential Time: {t_seq*1000:.2f}ms | Bulk Time: {t_bulk*1000:.2f}ms | Speedup: {speedup:.2f}x"
    )


def test_update_port_screen_data_integration() -> None:
    """Tests _update_port_screen_data correctly calls get_bulk_history and populates port_tree."""
    database.init_db()
    mock_scalper = mock.MagicMock()
    sim_conn = connector.SimulatorConnector()
    mock_scalper.conn = sim_conn

    with (
        mock.patch("gui.ttk.Style"),
        mock.patch("gui.tk.StringVar"),
        mock.patch("gui.tk.OptionMenu"),
        mock.patch("gui.messagebox"),
        mock.patch("gui.ScalperGui._show_login_dialog", return_value=True),
        mock.patch("main.AutonomousScalper", return_value=mock_scalper),
    ):
        mock_root = mock.MagicMock()
        scalper_gui = gui.ScalperGui(mock_root)

        mock_tree = mock.MagicMock()
        mock_tree.get_children.return_value = []
        scalper_gui.port_tree = mock_tree

        scalper_gui._update_port_screen_data()

        mock_tree.delete.assert_called_once()
        assert mock_tree.insert.call_count == 5
