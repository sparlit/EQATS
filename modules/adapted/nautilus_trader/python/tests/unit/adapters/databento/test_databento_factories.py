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
Test databento factories behavior.
"""

from pathlib import Path

import pytest
from nautilus_trader.adapters.databento import DatabentoDataClientConfig, DatabentoDataClientFactory
from nautilus_trader.common import Environment
from nautilus_trader.live import LiveNode
from nautilus_trader.model import TraderId
from unit.adapters.example_modules import capture_data_tester_main, load_example_module

DATABENTO = "DATABENTO"
SMOKE_API_KEY = "00000000000000000000000000000000"
databento_data_tester = load_example_module("databento", "data_tester")


def test_databento_data_factory_exposes_python_name() -> None:
    """
    Test databento data factory exposes python name.
    """
    assert DatabentoDataClientFactory().name() == DATABENTO


def test_live_node_builder_accepts_databento_data_factory() -> None:
    """
    Test live node builder accepts databento data factory.
    """
    trader_id = TraderId.from_str("TESTER-001")

    node = (
        LiveNode.builder("DATABENTO-DATA-PYTEST-001", trader_id, Environment.LIVE)
        .add_data_client(
            None,
            DatabentoDataClientFactory(),
            DatabentoDataClientConfig(
                api_key=SMOKE_API_KEY,
                publishers_filepath=publishers_filepath(),
            ),
        )
        .build()
    )

    assert node.trader_id == trader_id
    assert node.environment == Environment.LIVE


def test_databento_data_client_config_stores_venue_dataset_map() -> None:
    """
    Test databento data client config stores venue dataset map.
    """
    config = DatabentoDataClientConfig(
        api_key=SMOKE_API_KEY,
        publishers_filepath=publishers_filepath(),
        venue_dataset_map={"EQUS": "EQUS.PLUS"},
    )

    # No field getter is exposed, so the repr is the observable for the stored override.
    assert "EQUS" in repr(config)
    assert "EQUS.PLUS" in repr(config)


def test_databento_data_tester_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Test databento data tester runs.
    """
    monkeypatch.setenv("DATABENTO_API_KEY", "test-api-key")
    captured = capture_data_tester_main(monkeypatch, databento_data_tester)
    kwargs = captured["data_tester_kwargs"]

    assert isinstance(kwargs, dict)
    assert kwargs["subscribe_trades"] is True
    assert "exec_client_args" not in captured
    assert captured["run_called"] is True


def test_databento_data_tester_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Test databento data tester requires api key.
    """
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)

    with pytest.raises(SystemExit, match="DATABENTO_API_KEY must be set"):
        databento_data_tester.main()


def publishers_filepath() -> Path:
    """
    Return the publishers filepath.
    """
    return Path(__file__).resolve().parents[5] / "crates/adapters/databento/publishers.json"
