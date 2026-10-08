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
The `config` subpackage groups the core configuration types.

Adapter, testkit, and example configurations remain in their owning packages.

"""

from nautilus_trader.analysis import TearsheetConfig
from nautilus_trader.backtest import (
    BacktestDataConfig,
    BacktestEngineConfig,
    BacktestRunConfig,
    BacktestVenueConfig,
)
from nautilus_trader.common import (
    CacheConfig,
    DataActorConfig,
    FileWriterConfig,
    ImportableActorConfig,
    LoggerConfig,
    MessageBusConfig,
)
from nautilus_trader.data import DataEngineConfig
from nautilus_trader.execution import ExecutionEngineConfig, OrderEmulatorConfig
from nautilus_trader.live import (
    DataClientConfig,
    ExecutionClientConfig,
    InstrumentProviderConfig,
    LiveDataEngineConfig,
    LiveExecutionEngineConfig,
    LiveNodeConfig,
    LiveRiskEngineConfig,
    PluginConfig,
    QueueMonitorConfig,
    RoutingConfig,
)
from nautilus_trader.live.config import ImportableConfig, ImportableFactoryConfig
from nautilus_trader.persistence import DataCatalogConfig, RotationConfig, StreamingConfig
from nautilus_trader.portfolio import PortfolioConfig
from nautilus_trader.risk import RiskEngineConfig
from nautilus_trader.trading import (
    ExecutionAlgorithmConfig,
    ImportableControllerConfig,
    ImportableExecutionAlgorithmConfig,
    ImportableStrategyConfig,
    StrategyConfig,
)

__all__ = [
    "BacktestDataConfig",
    "BacktestEngineConfig",
    "BacktestRunConfig",
    "BacktestVenueConfig",
    "CacheConfig",
    "DataActorConfig",
    "DataCatalogConfig",
    "DataClientConfig",
    "DataEngineConfig",
    "ExecutionAlgorithmConfig",
    "ExecutionClientConfig",
    "ExecutionEngineConfig",
    "FileWriterConfig",
    "ImportableActorConfig",
    "ImportableConfig",
    "ImportableControllerConfig",
    "ImportableExecutionAlgorithmConfig",
    "ImportableFactoryConfig",
    "ImportableStrategyConfig",
    "InstrumentProviderConfig",
    "LiveDataEngineConfig",
    "LiveExecutionEngineConfig",
    "LiveNodeConfig",
    "LiveRiskEngineConfig",
    "LoggerConfig",
    "MessageBusConfig",
    "OrderEmulatorConfig",
    "PluginConfig",
    "PortfolioConfig",
    "QueueMonitorConfig",
    "RiskEngineConfig",
    "RotationConfig",
    "RoutingConfig",
    "StrategyConfig",
    "StreamingConfig",
    "TearsheetConfig",
]
