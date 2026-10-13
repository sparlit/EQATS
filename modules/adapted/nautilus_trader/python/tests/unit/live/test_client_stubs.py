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
Check generated adapter types against their runtime Python interface.
"""

import ast
import inspect
from pathlib import Path

import nautilus_trader.live as live  # noqa: PLR0402 - Load the Python package; the root attribute can refer to the native module.
import pytest


@pytest.fixture(scope="module")
def stub_classes() -> dict[str, ast.ClassDef]:
    """
    Read generated class definitions from the installed public module.
    """
    tree = ast.parse(Path(live.__file__).with_suffix(".pyi").read_text(encoding="utf-8"))
    return {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}


@pytest.mark.parametrize(
    "name",
    [
        "BarsResponse",
        "BatchCancelOrders",
        "BatchModifyOrders",
        "BookDeltasResponse",
        "BookDepthResponse",
        "BookResponse",
        "CancelAllOrders",
        "CancelOrder",
        "CustomDataResponse",
        "FundingRatesResponse",
        "GenerateFillReports",
        "GenerateOrderStatusReport",
        "GenerateOrderStatusReports",
        "GeneratePositionStatusReports",
        "InstrumentResponse",
        "InstrumentsResponse",
        "ModifyOrder",
        "OptionChainReferencePriceResponse",
        "QueryAccount",
        "QueryOrder",
        "QuotesResponse",
        "RequestBars",
        "RequestBookDeltas",
        "RequestBookDepth",
        "RequestBookSnapshot",
        "RequestCustomData",
        "RequestFundingRates",
        "RequestInstrument",
        "RequestInstruments",
        "RequestOptionChainReferencePrice",
        "RequestQuotes",
        "RequestTrades",
        "SubmitOrder",
        "SubmitOrderList",
        "SubscribeBars",
        "SubscribeBookDeltas",
        "SubscribeBookDepth",
        "SubscribeCustomData",
        "SubscribeFundingRates",
        "SubscribeIndexPrices",
        "SubscribeInstrument",
        "SubscribeInstrumentClose",
        "SubscribeInstrumentStatus",
        "SubscribeInstruments",
        "SubscribeMarkPrices",
        "SubscribeOptionGreeks",
        "SubscribeQuotes",
        "SubscribeTrades",
        "TradesResponse",
        "UnsubscribeBars",
        "UnsubscribeBookDeltas",
        "UnsubscribeBookDepth",
        "UnsubscribeCustomData",
        "UnsubscribeFundingRates",
        "UnsubscribeIndexPrices",
        "UnsubscribeInstrument",
        "UnsubscribeInstrumentClose",
        "UnsubscribeInstrumentStatus",
        "UnsubscribeInstruments",
        "UnsubscribeMarkPrices",
        "UnsubscribeOptionGreeks",
        "UnsubscribeQuotes",
        "UnsubscribeTrades",
    ],
)
def test_adapter_stub_names_and_properties_match_runtime(name: str, stub_classes) -> None:
    """
    Expose the runtime name and every native getter as a stub property.
    """
    runtime = getattr(live, name)
    classes = stub_classes
    assert name in classes
    assert "Py" + name not in classes
    stub = classes[name]
    actual = {
        node.name
        for node in stub.body
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(item, ast.Name) and item.id == "property" for item in node.decorator_list
        )
    }
    expected = {key for key, value in vars(runtime).items() if inspect.isgetsetdescriptor(value)}

    assert actual == expected
    assert runtime.__name__ == name
    assert runtime.__module__ == "nautilus_trader.live"


@pytest.mark.parametrize("name", ["DataClientConfig", "ExecutionClientConfig"])
def test_client_config_constructor_stub_preserves_subclass(name: str, stub_classes) -> None:
    """
    Describe the subclass returned by the runtime constructor.
    """
    runtime = getattr(live, name)

    class Derived(runtime):
        pass

    constructor = next(
        node
        for node in stub_classes[name].body
        if isinstance(node, ast.FunctionDef) and node.name == "__new__"
    )

    assert type(Derived.__new__(Derived)) is Derived
    assert ast.unparse(constructor.returns) == "typing.Self"


def test_live_node_run_stub_matches_runtime_arguments(stub_classes) -> None:
    """
    Keep the existing no-argument run method consistent for static callers.
    """
    method = next(
        node
        for node in stub_classes["LiveNode"].body
        if isinstance(node, ast.FunctionDef) and node.name == "run"
    )
    arguments = method.args.posonlyargs + method.args.args + method.args.kwonlyargs

    assert [argument.arg for argument in arguments] == ["self"]
    assert list(inspect.signature(live.LiveNode.run).parameters) == ["self"]
    assert method.args.vararg is None
    assert method.args.kwarg is None
