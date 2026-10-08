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
Test reports behavior.
"""

from decimal import Decimal

from nautilus_trader.core import UUID4
from nautilus_trader.model import (
    AccountId,
    AvgPxReconciliation,
    ClientId,
    ClientOrderId,
    ContingencyType,
    ExecAlgorithmId,
    ExecutionMassStatus,
    FillReport,
    InstrumentId,
    Money,
    OrderInitialized,
    OrderListId,
    OrderSide,
    OrderSnapshot,
    OrderStatusReport,
    OrderType,
    Position,
    PositionAdjusted,
    PositionAdjustmentType,
    PositionChanged,
    PositionClosed,
    PositionId,
    PositionOpened,
    PositionSide,
    PositionSnapshot,
    PositionStatusReport,
    Price,
    Quantity,
    StrategyId,
    TimeInForce,
    TraderId,
    TriggerType,
    Venue,
    VenueOrderId,
)
from tests.providers import TestInstrumentProvider
from tests.unit.model.factories import (
    make_fill_report,
    make_market_order_snapshot_values,
    make_order_initialized,
    make_order_status_report,
    make_position_fill,
    make_position_status_report,
)


def test_fill_report_to_dict_and_from_dict_roundtrip(audusd_id: InstrumentId) -> None:
    """
    Test fill report to dict and from dict roundtrip.
    """
    report = make_fill_report(audusd_id)

    data = report.to_dict()
    restored = FillReport.from_dict(data)

    assert data["type"] == "FillReport"
    assert restored == report
    assert restored.client_order_id == ClientOrderId("O-1")
    assert restored.venue_position_id == PositionId("P-1")


def test_order_status_report_to_dict_and_from_dict_roundtrip(audusd_id: InstrumentId) -> None:
    """
    Test order status report to dict and from dict roundtrip.
    """
    report = make_order_status_report(audusd_id, include_optionals=False)

    data = report.to_dict()
    restored = OrderStatusReport.from_dict(data)
    report_with_optionals = make_order_status_report(audusd_id, include_optionals=True)

    assert data["type"] == "OrderStatusReport"
    assert report.is_open
    assert restored.venue_order_id == VenueOrderId("1")
    assert restored.filled_qty == Quantity.from_int(25_000)
    assert report_with_optionals.linked_order_ids == [ClientOrderId("O-2")]
    assert report_with_optionals.avg_px == Decimal("1.00005")
    assert report_with_optionals.post_only is True
    assert report_with_optionals.trigger_type == TriggerType.BID_ASK


def test_execution_mass_status_adds_reports_and_roundtrips(audusd_id: InstrumentId) -> None:
    """
    Test execution mass status adds reports and roundtrips.
    """
    order_report = make_order_status_report(audusd_id, include_optionals=False)
    fill_report = make_fill_report(audusd_id)
    position_report = make_position_status_report(audusd_id)

    status = ExecutionMassStatus(
        client_id=ClientId("CID"),
        account_id=AccountId("SIM-001"),
        venue=Venue("SIM"),
        ts_init=77,
    )
    status.add_order_reports([order_report])
    status.add_fill_reports([fill_report])
    status.add_position_reports([position_report])

    data = status.to_dict()
    restored = ExecutionMassStatus.from_dict(data)

    assert data["type"] == "ExecutionMassStatus"
    assert data["lookback_start"] is None
    assert data["reports_complete"] is True
    assert status.lookback_start is None
    assert status.reports_complete is True
    assert restored.lookback_start is None
    assert restored.reports_complete is True
    assert list(data["order_reports"].keys()) == ["1"]
    assert list(data["fill_reports"].keys()) == ["1"]
    assert list(data["position_reports"].keys()) == ["AUD/USD.SIM"]
    assert list(restored.order_reports.keys()) == [VenueOrderId("1")]
    assert list(restored.fill_reports.keys()) == [VenueOrderId("1")]
    assert list(restored.position_reports.keys()) == [InstrumentId.from_str("AUD/USD.SIM")]


def test_order_initialized_to_dict_and_from_dict_roundtrip(audusd_id: InstrumentId) -> None:
    """
    Test order initialized to dict and from dict roundtrip.
    """
    event = make_order_initialized(audusd_id)

    restored = OrderInitialized.from_dict(event.to_dict())

    assert restored.trader_id == TraderId("TRADER-001")
    assert restored.strategy_id == StrategyId("S-001")
    assert restored.instrument_id == audusd_id
    assert restored.client_order_id == ClientOrderId("O-1")
    assert restored.order_side == OrderSide.BUY
    assert restored.order_type == OrderType.STOP_LIMIT
    assert restored.quantity == Quantity.from_int(100_000)
    assert restored.time_in_force == TimeInForce.GTC
    assert restored.post_only is True
    assert restored.reduce_only is False
    assert restored.quote_quantity is False
    assert restored.reconciliation is False
    assert restored.event_id == event.event_id
    assert restored.ts_event == 1
    assert restored.ts_init == 2
    assert restored.price == Price.from_str("1.00010")
    assert restored.activation_price is None
    assert restored.trigger_price == Price.from_str("0.99990")
    assert restored.trigger_type == TriggerType.BID_ASK
    assert restored.limit_offset is None
    assert restored.trailing_offset is None
    assert restored.trailing_offset_type is None
    assert restored.expire_time == 3
    assert restored.display_qty == Quantity.from_int(50_000)
    assert restored.emulation_trigger == TriggerType.LAST_PRICE
    assert restored.trigger_instrument_id == audusd_id
    assert restored.contingency_type == ContingencyType.OCO
    assert restored.order_list_id == OrderListId("L-1")
    assert restored.linked_order_ids == [ClientOrderId("O-2")]
    assert restored.parent_order_id == ClientOrderId("O-P")
    assert restored.exec_algorithm_id == ExecAlgorithmId("VWAP")
    assert restored.exec_algorithm_params == {"speed": "fast"}
    assert restored.exec_spawn_id == ClientOrderId("O-X")
    assert restored.tags == ["tag-1", "tag-2"]


def test_order_snapshot_from_dict_returns_snapshot_instance(audusd_id: InstrumentId) -> None:
    """
    Test order snapshot from dict returns snapshot instance.
    """
    snapshot = OrderSnapshot.from_dict(make_market_order_snapshot_values(audusd_id))

    assert type(snapshot).__name__ == "OrderSnapshot"


def test_position_adjusted_to_dict_and_from_dict_roundtrip(audusd_id: InstrumentId) -> None:
    """
    Test position adjusted to dict and from dict roundtrip.
    """
    event = PositionAdjusted(
        trader_id=TraderId("TRADER-001"),
        strategy_id=StrategyId("S-001"),
        instrument_id=audusd_id,
        position_id=PositionId("P-1"),
        account_id=AccountId("SIM-001"),
        adjustment_type=PositionAdjustmentType.FUNDING,
        quantity_change=Decimal("100.5"),
        pnl_change=Money.from_str("12.00 USD"),
        reason="funding",
        event_id=UUID4(),
        ts_event=10,
        ts_init=11,
    )

    restored = PositionAdjusted.from_dict(event.to_dict())

    assert restored.adjustment_type == PositionAdjustmentType.FUNDING
    assert restored.quantity_change == Decimal("100.5")
    assert restored.pnl_change == Money.from_str("12.00 USD")
    assert restored.reason == "funding"


def test_position_status_report_properties_and_roundtrip(audusd_id: InstrumentId) -> None:
    """
    Test position status report properties and roundtrip.
    """
    report = make_position_status_report(audusd_id)
    restored = PositionStatusReport.from_dict(report.to_dict())

    assert report.is_long
    assert not report.is_short
    assert not report.is_flat
    assert report.quantity == Quantity.from_int(100_000)
    assert report.avg_px_open == Decimal("1.00010")
    assert report.avg_px_open_reconciliation == AvgPxReconciliation.MATCH
    assert report.avg_px_open_precision is None
    assert restored == report


def test_position_status_report_avg_px_open_metadata_roundtrip(audusd_id: InstrumentId) -> None:
    """
    Test position status report average entry metadata survives a dict roundtrip.
    """
    report = PositionStatusReport(
        account_id=AccountId("SIM-001"),
        instrument_id=audusd_id,
        position_side=PositionSide.LONG,
        quantity=Quantity.from_int(100_000),
        ts_last=10,
        ts_init=20,
        avg_px_open=Decimal("1.00010"),
        avg_px_open_reconciliation=AvgPxReconciliation.OPENING_ONLY,
        avg_px_open_precision=4,
    )

    data = report.to_dict()
    restored = PositionStatusReport.from_dict(data)

    assert data["avg_px_open"] == "1.00010"
    assert data["avg_px_open_reconciliation"] == "OPENING_ONLY"
    assert data["avg_px_open_precision"] == 4
    assert restored == report
    assert restored.avg_px_open_reconciliation == AvgPxReconciliation.OPENING_ONLY
    assert restored.avg_px_open_precision == 4


def test_position_snapshot_from_dict_returns_snapshot_instance() -> None:
    """
    Test position snapshot from dict returns snapshot instance.
    """
    instrument = TestInstrumentProvider.audusd_sim()
    fill = make_position_fill(instrument)
    position = Position(instrument=instrument, fill=fill)
    values = position.to_dict()
    values["unrealized_pnl"] = None

    snapshot = PositionSnapshot.from_dict(values)

    assert type(snapshot).__name__ == "PositionSnapshot"


def test_position_event_classes_expose_create_surface() -> None:
    """
    Test position event classes expose create surface.
    """
    assert hasattr(PositionOpened, "position_id")
    assert hasattr(PositionOpened, "quantity")
    assert hasattr(PositionOpened, "realized_pnl")
    assert hasattr(PositionChanged, "peak_quantity")
    assert hasattr(PositionChanged, "peak_qty")
    assert hasattr(PositionChanged, "realized_pnl")
    assert hasattr(PositionClosed, "closing_order_id")
    assert hasattr(PositionClosed, "peak_qty")
    assert hasattr(PositionClosed, "ts_closed")
