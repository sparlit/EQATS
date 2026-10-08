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
Test blockchain factories behavior.
"""

import pytest
from nautilus_trader.adapters.blockchain import (
    BlockchainDataClientConfig,
    BlockchainDataClientFactory,
)
from nautilus_trader.common import Environment
from nautilus_trader.live import LiveNode
from nautilus_trader.model import Chain, DexType, TraderId
from unit.adapters.example_modules import (
    capture_actor_example_main,
    capture_data_tester_main,
    load_example_module,
)

BLOCKCHAIN = "BLOCKCHAIN"
blockchain_data_tester = load_example_module("blockchain", "data_tester")
blockchain_node_test = load_example_module("blockchain", "node_test")


def test_blockchain_data_factory_exposes_python_name() -> None:
    """
    Test blockchain data factory exposes python name.
    """
    assert BlockchainDataClientFactory().name() == BLOCKCHAIN


def test_live_node_builder_accepts_blockchain_data_factory() -> None:
    """
    Test live node builder accepts blockchain data factory.
    """
    trader_id = TraderId.from_str("TESTER-001")

    node = (
        LiveNode.builder("BLOCKCHAIN-DATA-PYTEST-001", trader_id, Environment.LIVE)
        .add_data_client(
            "BLOCKCHAIN-Arbitrum",
            BlockchainDataClientFactory(),
            BlockchainDataClientConfig(
                chain=Chain.ARBITRUM(),
                dex_ids=[DexType.UNISWAP_V3],
                http_rpc_url="https://arb1.arbitrum.io/rpc",
            ),
        )
        .build()
    )

    assert node.trader_id == trader_id
    assert node.environment == Environment.LIVE


def test_blockchain_data_tester_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Test blockchain data tester runs.
    """
    monkeypatch.setenv("ENVIO_API_TOKEN", "00000000-0000-0000-0000-000000000000")
    captured = capture_data_tester_main(monkeypatch, blockchain_data_tester)
    kwargs = captured["data_tester_kwargs"]

    assert isinstance(kwargs, dict)
    assert kwargs["request_instruments"] is True
    assert "exec_client_args" not in captured
    assert captured["run_called"] is True


def test_blockchain_data_tester_requires_hypersync_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Test blockchain data tester requires hypersync token.
    """
    monkeypatch.delenv("ENVIO_API_TOKEN", raising=False)

    with pytest.raises(SystemExit, match="ENVIO_API_TOKEN must be set"):
        blockchain_data_tester.main()


def test_blockchain_node_example_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Test blockchain node example runs.
    """
    monkeypatch.setenv("ENVIO_API_TOKEN", "00000000-0000-0000-0000-000000000000")
    captured = capture_actor_example_main(monkeypatch, blockchain_node_test)
    _, _, config = captured["data_client_args"]

    assert isinstance(config, BlockchainDataClientConfig)
    assert config.use_hypersync_for_live_data is True
    assert "importable_actor_config" in captured
    assert captured["run_called"] is True


def test_blockchain_node_example_requires_hypersync_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Test blockchain node example requires hypersync token.
    """
    monkeypatch.delenv("ENVIO_API_TOKEN", raising=False)

    with pytest.raises(SystemExit, match="ENVIO_API_TOKEN must be set"):
        blockchain_node_test.main()
