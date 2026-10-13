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


# -------------------------------------------------------------------------------------------------
#  Copyright (C) 2015-2026 Nautech Systems Pty Ltd. All rights reserved.
#  https://nautechsystems.io
#
#  Licensed under the GNU Lesser General Public License Version 3.0 (the "License");
#  You may not use this file except in compliance with the License.
#  You may obtain a copy of the License at https://www.gnu.org/licenses/lgpl-3.0.en.html
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
# -------------------------------------------------------------------------------------------------
"""
Base class for user-defined portfolio statistics.
"""


import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nautilus_trader.model import Position


class PortfolioStatistic:
    """
    The base class for all portfolio performance statistics.

    Subclass this and override the calculation methods for the input categories the
    statistic supports. The analyzer feeds each category separately, so a statistic
    contributes a value only where it overrides the matching method.

    Register an implementation with `Portfolio.register_statistic()` to include it in
    `Portfolio.statistics()`, backtest results, and post-run analysis logs.

    Notes
    -----
    The return value must be a float, or ``None`` when the statistic is undefined for the
    given data.

    """

    @property
    def name(self) -> str:
        """
        Return the name for the statistic.

        The default splits the class name on word boundaries, so `MyCustomRatio` becomes
        "My Custom Ratio". Override this to choose the name directly.

        Returns
        -------
        str

        """
        klass = type(self).__name__
        matches = re.finditer(".+?(?:(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|$)", klass)
        return " ".join([m.group(0) for m in matches])

    def calculate_from_returns(self, returns: dict[int, float]) -> float | None:
        """
        Calculate the statistic value from the given returns.

        Parameters
        ----------
        returns : dict[int, float]
            The returns keyed by UNIX timestamp (nanoseconds).

        Returns
        -------
        float or ``None``

        """
        # Override in implementation

    def calculate_from_realized_pnls(self, realized_pnls: list[float]) -> float | None:
        """
        Calculate the statistic value from the given realized PnLs.

        Parameters
        ----------
        realized_pnls : list[float]
            The realized PnLs for one currency, in ascending event-time order.

        Returns
        -------
        float or ``None``

        """
        # Override in implementation

    def calculate_from_positions(self, positions: list[Position]) -> float | None:
        """
        Calculate the statistic value from the given positions.

        Parameters
        ----------
        positions : list[Position]
            The positions to use for the calculation.

        Returns
        -------
        float or ``None``

        """
        # Override in implementation

    def calculate_from_returns_with_benchmark(
        self,
        returns: dict[int, float],
        benchmark: dict[int, float],
    ) -> float | None:
        """
        Calculate the statistic value from the given returns relative to a benchmark.

        Parameters
        ----------
        returns : dict[int, float]
            The strategy returns keyed by UNIX timestamp (nanoseconds).
        benchmark : dict[int, float]
            The benchmark returns keyed by UNIX timestamp (nanoseconds).

        Returns
        -------
        float or ``None``

        """
        # Override in implementation
