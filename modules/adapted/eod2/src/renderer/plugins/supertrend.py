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


from typing import Any

from mplfinance import make_addplot

from .utils import supertrend

"""
Supertrend plugin.

Calculates the Supertrend indicator and plots separate uptrend and
downtrend lines directly on the main price panel using
``mplfinance.make_addplot``.

Configuration options are supplied through the plugin's entry in
``CHART_PLUGINS`` within ``defs/user.json``. Because Supertrend is a
price overlay, the panel configuration should use ``"kind": "price"``.

Available Options:
    factor (int | float, optional):
        ATR multiplier used to calculate the Supertrend bands.
        Defaults to ``3``.

    atr_length (int, optional):
        ATR calculation period.
        Defaults to ``10``. If omitted, the plugin also checks the
        ``period`` option.

    period (int, optional):
        Alias for ``atr_length``.

    up_color (str, optional):
        Color used when the indicator shows an uptrend.
        Defaults to ``"mediumseagreen"``.

    down_color (str, optional):
        Color used when the indicator shows a downtrend.
        Defaults to ``"crimson"``.

    width (float, optional):
        Width of the Supertrend lines.
        Defaults to ``1.2``.

Example Configuration:
    Add the following entry to the top-level ``CHART_PLUGINS`` object
    in ``defs/user.json``::

        {
          "SUPERTREND": {
            "name": "supertrend",
            "option": "supertrend",
            "help": "Add Supertrend indicator.",
            "lookback": 100,
            "panel": {
              "kind": "price"
            },
            "factor": 3,
            "atr_length": 10,
            "up_color": "mediumseagreen",
            "down_color": "crimson",
            "width": 1.2
          }
        }
"""


def apply(
    df,
    plot_args: dict[str, Any],
    options: dict[str, Any],
    display_period: int,
) -> None:
    factor = int(options.get("factor", 3))
    atr_length = int(options.get("atr_length", options.get("period", 10)))

    up_color = options.get("up_color", "mediumseagreen")
    down_color = options.get("down_color", "crimson")
    width = float(options.get("width", 1.2))

    trend, direction = supertrend(
        high=df.High,
        low=df.Low,
        close=df.Close,
        factor=factor,
        atr_length=atr_length,
    )

    uptrend = trend.where(direction == 1)
    downtrend = trend.where(direction == -1)

    addplots = plot_args.setdefault("addplot", [])
    addplots.extend(
        [
            make_addplot(
                uptrend.iloc[-display_period:],
                label=f"Supertrend {factor}, {atr_length}",
                color=up_color,
                width=width,
                secondary_y=False,
            ),
            make_addplot(
                downtrend.iloc[-display_period:],
                color=down_color,
                width=width,
                secondary_y=False,
            ),
        ]
    )
