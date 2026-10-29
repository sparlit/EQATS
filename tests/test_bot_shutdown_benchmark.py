import sys
import time
import unittest
from unittest.mock import MagicMock

# Mock tkinter and submodules if tkinter display is not available
mock_tk = MagicMock()
sys.modules['tkinter'] = mock_tk
sys.modules['tkinter.filedialog'] = MagicMock()
sys.modules['tkinter.messagebox'] = MagicMock()
sys.modules['tkinter.ttk'] = MagicMock()

import src.config as config
import src.gui as gui_module

class TestBotShutdownPerformance(unittest.TestCase):
    def test_bot_shutdown_latency(self):
        """Measures and verifies the shutdown latency of the GUI bot thread."""
        gui = gui_module.ScalperGui.__new__(gui_module.ScalperGui)
        gui.running = False
        gui.bot_stop_event = gui_module.threading.Event()
        gui.scalper = MagicMock()
        gui.scalper.start.return_value = True
        gui.root = MagicMock()
        gui.btn_start = MagicMock()
        gui.btn_stop = MagicMock()
        gui.btn_toggle_mode = MagicMock()
        gui.lbl_clock = MagicMock()

        # Start bot thread
        gui.start_bot()
        time.sleep(0.05) # Allow thread to enter event wait state

        t0 = time.perf_counter()
        gui.stop_bot()
        gui.bot_thread.join(timeout=2.0)
        t1 = time.perf_counter()

        latency = t1 - t0
        print(f"\nBot shutdown latency: {latency:.6f} seconds")
        self.assertFalse(gui.bot_thread.is_alive())
        # Shutdown should happen almost instantaneously (< 0.1s vs up to CHECK_INTERVAL_SECONDS)
        self.assertLess(latency, 0.1)

if __name__ == "__main__":
    unittest.main()
