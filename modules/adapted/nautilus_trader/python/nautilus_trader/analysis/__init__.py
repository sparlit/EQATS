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


# ruff: noqa: E402
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
Performance analysis and reporting tools for trading results.
"""

from nautilus_trader._fixup import fixup_module_names
from nautilus_trader._libnautilus.analysis import *  # noqa: F403 (undefined-local-with-import-star)

fixup_module_names(globals(), __name__)
del fixup_module_names

from nautilus_trader.analysis.config import GridLayout as GridLayout
from nautilus_trader.analysis.config import (
    TearsheetBarsWithFillsChart as TearsheetBarsWithFillsChart,
)
from nautilus_trader.analysis.config import TearsheetChart as TearsheetChart
from nautilus_trader.analysis.config import TearsheetConfig as TearsheetConfig
from nautilus_trader.analysis.config import TearsheetCustomChart as TearsheetCustomChart
from nautilus_trader.analysis.config import TearsheetDistributionChart as TearsheetDistributionChart
from nautilus_trader.analysis.config import TearsheetDrawdownChart as TearsheetDrawdownChart
from nautilus_trader.analysis.config import TearsheetEquityChart as TearsheetEquityChart
from nautilus_trader.analysis.config import (
    TearsheetMonthlyReturnsChart as TearsheetMonthlyReturnsChart,
)
from nautilus_trader.analysis.config import (
    TearsheetRollingSharpeChart as TearsheetRollingSharpeChart,
)
from nautilus_trader.analysis.config import TearsheetRunInfoChart as TearsheetRunInfoChart
from nautilus_trader.analysis.config import TearsheetStatsTableChart as TearsheetStatsTableChart
from nautilus_trader.analysis.config import (
    TearsheetYearlyReturnsChart as TearsheetYearlyReturnsChart,
)
from nautilus_trader.analysis.reporter import ReportProvider as ReportProvider
from nautilus_trader.analysis.statistic import PortfolioStatistic as PortfolioStatistic
from nautilus_trader.analysis.tearsheet import create_bars_with_fills as create_bars_with_fills
from nautilus_trader.analysis.tearsheet import create_drawdown_chart as create_drawdown_chart
from nautilus_trader.analysis.tearsheet import create_equity_curve as create_equity_curve
from nautilus_trader.analysis.tearsheet import (
    create_monthly_returns_heatmap as create_monthly_returns_heatmap,
)
from nautilus_trader.analysis.tearsheet import (
    create_returns_distribution as create_returns_distribution,
)
from nautilus_trader.analysis.tearsheet import create_rolling_sharpe as create_rolling_sharpe
from nautilus_trader.analysis.tearsheet import create_tearsheet as create_tearsheet
from nautilus_trader.analysis.tearsheet import (
    create_tearsheet_from_stats as create_tearsheet_from_stats,
)
from nautilus_trader.analysis.tearsheet import create_yearly_returns as create_yearly_returns
from nautilus_trader.analysis.tearsheet import get_chart as get_chart
from nautilus_trader.analysis.tearsheet import list_charts as list_charts
from nautilus_trader.analysis.tearsheet import register_chart as register_chart
from nautilus_trader.analysis.tearsheet import register_tearsheet_chart as register_tearsheet_chart
from nautilus_trader.analysis.themes import get_theme as get_theme
from nautilus_trader.analysis.themes import list_themes as list_themes
from nautilus_trader.analysis.themes import register_theme as register_theme
