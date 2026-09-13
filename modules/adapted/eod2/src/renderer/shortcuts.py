from __future__ import annotations

import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


"""ShortcutHandler - maps keyboard events to coordinator actions."""


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from matplotlib.backend_bases import KeyEvent
    from matplotlib.figure import Figure

    from .coordinator import PlotCoordinator


class ShortcutHandler:
    """Connects keyboard events to PlotCoordinator actions.

    Key mappings:
        n → next symbol
        p → previous symbol
        q → quit
        d → toggle draw mode
        a → add current symbol to selection set
        h → Plot help info on chart
        j → Jump to number
    """

    def __init__(
        self,
        fig: Figure,
        coordinator: PlotCoordinator,
    ) -> None:
        """Connect keyboard handler to figure.

        Args:
            fig: Matplotlib figure
            coordinator: The PlotCoordinator instance
        """
        self._coordinator: PlotCoordinator = coordinator
        self._cid = fig.canvas.mpl_connect("key_press_event", self._on_key_press)
        self.fig = fig
        self._num_buffer = ""

    def _on_key_press(self, event: KeyEvent) -> None:
        """Handle key press events."""
        key = event.key

        if key is not None and key.isdigit():
            self._num_buffer += key
            self._coordinator.add_jump_status(self._num_buffer)
            return

        match key:
            case "n":
                self._coordinator.navigate_next()
            case "p":
                self._coordinator.navigate_previous()
            case "q":
                self._coordinator.quit()
            case "d":
                self._coordinator.toggle_draw_mode()
            case "a":
                self._coordinator.add_to_selection()
            case "H":
                self._coordinator.plot_help()
            case "j":
                if self._num_buffer:
                    self._coordinator.add_jump_status("")
                    self._coordinator.jump_to(int(self._num_buffer))
                self._num_buffer = ""
            case _:
                # Any other key resets the _num_buffer
                if self._num_buffer:
                    self._num_buffer = ""
                    self._coordinator.add_jump_status("")
