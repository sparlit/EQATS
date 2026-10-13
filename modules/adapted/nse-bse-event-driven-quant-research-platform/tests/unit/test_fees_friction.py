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


"""Fee-model and friction-metric tests."""

from datetime import UTC, date, datetime

import pandas as pd
import pytest
from indian_quant.nautilus.adapters.fees import IndiaDeliveryFeeModel
from indian_quant.research.friction import compute_friction_metrics


class FakeOrder:
    def __init__(self, side: str):
        from nautilus_trader.model.enums import OrderSide

        self.side = OrderSide[side]


class TestIndiaDeliveryFeeModel:
    def test_sell_costs_more_than_buy_at_same_notional(self):
        model = IndiaDeliveryFeeModel()
        buy = model.get_commission(FakeOrder("BUY"), 100, 1300.0, None)
        sell = model.get_commission(FakeOrder("SELL"), 100, 1300.0, None)
        assert float(sell) > float(buy)
        expected_buy = 100 * 1300 * (3.0 + 1.5) / 10_000
        expected_sell = 100 * 1300 * (3.0 + 100.0) / 10_000
        assert float(buy) == pytest.approx(expected_buy, abs=0.01)
        assert float(sell) == pytest.approx(expected_sell, abs=0.01)

    def test_flat_fee_added_per_fill(self):
        model = IndiaDeliveryFeeModel(flat_fee_per_order=20.0)
        fee = model.get_commission(FakeOrder("BUY"), 1, 100.0, None)
        assert float(fee) == pytest.approx(20.0 + 100 * 4.5 / 10_000, abs=0.01)

    def test_zero_config_is_free(self):
        model = IndiaDeliveryFeeModel(
            brokerage_bps=0, stt_sell_bps=0, stamp_buy_bps=0, flat_fee_per_order=0
        )
        assert float(model.get_commission(FakeOrder("SELL"), 500, 2000.0, None)) == 0.0

    def test_currency_is_inr(self):
        model = IndiaDeliveryFeeModel()
        fee = model.get_commission(FakeOrder("BUY"), 10, 100.0, None)
        assert str(fee.currency) == "INR"


def _fills_frame(buy_px=1300.0, sell_px=1310.0):
    return pd.DataFrame(
        {
            "instrument_id": ["RELIANCE.NSE"] * 2,
            "side": ["BUY", "SELL"],
            "filled_qty": [100.0, 100.0],
            "avg_px": [buy_px, sell_px],
            "commissions": ["[5.85 INR]", "[134.30 INR]"],
        }
    )


class TestFrictionMetrics:
    def test_turnover_and_commissions_split_by_side(self):
        m = compute_friction_metrics(_fills_frame())
        assert m["turnover_notional"] == pytest.approx(261_000.0)
        assert m["total_commissions"] == pytest.approx(140.15)
        assert m["commissions_buy"] == pytest.approx(5.85)
        assert m["commissions_sell"] == pytest.approx(134.30)

    def test_realized_cost_bps(self):
        m = compute_friction_metrics(_fills_frame())
        assert m["realized_cost_bps"] == pytest.approx(140.15 / 261_000 * 10_000, rel=0.01)

    def test_leakage_when_profitable(self):
        # realized_pnl is NET of commissions: gross = net + commissions
        positions = pd.DataFrame({"realized_pnl": ["559.85 INR"]})
        m = compute_friction_metrics(_fills_frame(), positions)
        assert m["gross_pnl"] == pytest.approx(700.0)
        assert m["alpha_leakage_pct"] == pytest.approx(140.15 / 700 * 100, rel=0.01)

    def test_leakage_none_when_no_gross_alpha(self):
        positions = pd.DataFrame({"realized_pnl": ["-259858.63 INR"]})
        m = compute_friction_metrics(_fills_frame(), positions)
        assert m["gross_pnl"] == pytest.approx(-259718.48, abs=0.01)
        assert m["gross_pnl"] < 0
        assert m["alpha_leakage_pct"] is None

    def test_leakage_none_when_unprofitable(self):
        positions = pd.DataFrame({"realized_pnl": ["-700.00 INR"]})
        m = compute_friction_metrics(_fills_frame(), positions)
        assert m["alpha_leakage_pct"] is None

    def test_holding_days_from_positions(self):
        positions = pd.DataFrame(
            {"realized_pnl": ["700.00 INR"], "duration_ns": [2 * 86_400_000_000_000]}
        )
        m = compute_friction_metrics(_fills_frame(), positions)
        assert m["median_holding_days"] == pytest.approx(2.0)

    def test_empty_fills(self):
        m = compute_friction_metrics(pd.DataFrame(columns=["avg_px", "filled_qty"]))
        assert m["n_fills"] == 0
        assert m["turnover_notional"] == 0.0


class TestContinuityDetector:
    def _bar(self, day, close, instrument_id="NSE_EQ|SPL"):
        from indian_quant.schemas import MarketBar, Timeframe

        return MarketBar(
            instrument_id=instrument_id,
            exchange="NSE",
            timestamp=datetime.fromisoformat(day).replace(tzinfo=UTC),
            timeframe=Timeframe.DAY,
            open=close * 0.99,
            high=close * 1.01,
            low=close * 0.98,
            close=close,
            volume=1000.0,
            source="NSE",
        )

    def test_matching_split_passes(self, tmp_path=None):
        from indian_quant.quality import run_quality_suite
        from indian_quant.schemas import CorporateAction, CorporateActionType

        bars = [
            self._bar("2025-06-09T00:00:00+00:00", 5000.0),
            self._bar("2025-06-10T00:00:00+00:00", 1000.0),
        ]
        action = CorporateAction(
            instrument_id="NSE_EQ|SPL",
            action_type=CorporateActionType.SPLIT,
            old_value=10.0,
            new_value=2.0,
            ex_date=date(2025, 6, 10),
            source="NSE",
        )
        report, _ = run_quality_suite(bars, dataset="t", actions=[action])
        assert not any(i.code == "ADJ_DISCONTINUITY" for i in report.issues)

    def test_mismatched_ratio_flags_error(self):
        from indian_quant.quality import run_quality_suite
        from indian_quant.schemas import CorporateAction, CorporateActionType

        bars = [
            self._bar("2025-06-09T00:00:00+00:00", 5000.0),
            self._bar("2025-06-10T00:00:00+00:00", 4800.0),
        ]
        action = CorporateAction(
            instrument_id="NSE_EQ|SPL",
            action_type=CorporateActionType.SPLIT,
            old_value=10.0,
            new_value=2.0,
            ex_date=date(2025, 6, 10),
            source="NSE",
        )
        report, _ = run_quality_suite(bars, dataset="t", actions=[action])
        issues = [i for i in report.issues if i.code == "ADJ_DISCONTINUITY"]
        assert issues and issues[0].severity == "error"

    def test_dividend_ignored(self):
        from indian_quant.quality import run_quality_suite
        from indian_quant.schemas import CorporateAction, CorporateActionType

        bars = [
            self._bar("2025-06-09T00:00:00+00:00", 1000.0),
            self._bar("2025-06-10T00:00:00+00:00", 1000.0),
        ]
        action = CorporateAction(
            instrument_id="NSE_EQ|SPL",
            action_type=CorporateActionType.DIVIDEND,
            amount=6.0,
            ex_date=date(2025, 6, 10),
            source="NSE",
        )
        report, _ = run_quality_suite(bars, dataset="t", actions=[action])
        assert not any(i.code.startswith("ADJ_") for i in report.issues)
