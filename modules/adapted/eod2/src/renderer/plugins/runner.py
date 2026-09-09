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


from importlib import import_module
from typing import TYPE_CHECKING, Any

from renderer.cli import CliError

if TYPE_CHECKING:
    import pandas as pd
    from renderer.dtypes import PanelAssignment


class PluginError(CliError):
    """Raised when a chart plugin cannot be loaded or executed."""


class PluginRunner:
    def __init__(
        self,
        plugins: dict[str, dict[str, Any]],
        panel_layout: dict[str, PanelAssignment],
    ) -> None:
        self.plugins = plugins
        self.panel_layout = panel_layout

    def apply(
        self,
        df: pd.DataFrame,
        plot_args: dict[str, Any],
        display_period: int,
    ) -> None:
        for plugin_key, plugin_config in self.plugins.items():
            options = dict(plugin_config)

            module_name = str(options.pop("name", plugin_key.lower()))

            assignment = self.panel_layout.get(f"plugin:{plugin_key}")

            if assignment is not None:
                options["plot_panel"] = assignment.panel

                if assignment.secondary_y is not None:
                    options["secondary_y"] = assignment.secondary_y

            try:
                module = import_module(f"renderer.plugins.{module_name}")
            except ModuleNotFoundError as exc:
                if exc.name in (module_name, f"renderer.plugins.{module_name}"):
                    msg = f"Could not load plugin '{plugin_key}' from module 'renderer.plugins.{module_name}'"
                    raise PluginError(msg) from exc

                raise

            module.apply(df, plot_args, options, display_period)
