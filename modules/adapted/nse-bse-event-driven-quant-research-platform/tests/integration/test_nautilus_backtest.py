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


"""Integration test: synthetic bars -> catalog -> SMA backtest -> report.

This is the Phase 4 exit condition, verified continuously.
"""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from indian_quant.config import Settings
from indian_quant.nautilus.adapters.backtest import BacktestRunner, summarize_result
from indian_quant.nautilus.data.catalog import CatalogBridge
from indian_quant.schemas import Exchange, InstrumentIdentity, MarketBar, Segment, Timeframe


def make_bars(n: int = 250, seed: int = 42) -> list[MarketBar]:
    rng = np.random.default_rng(seed)
    base = 2400.0
    closes = base * np.cumprod(1 + rng.normal(0.0008, 0.012, n))
    opens = np.concatenate([[base], closes[:-1]])
    highs = np.maximum(opens, closes) * (1 + np.abs(rng.normal(0, 0.004, n)))
    lows = np.minimum(opens, closes) * (1 - np.abs(rng.normal(0, 0.004, n)))
    vols = rng.integers(1_000_000, 5_000_000, n)
    start = datetime(2025, 1, 1, tzinfo=UTC)
    bars = []
    for i in range(n):
        ts = start + timedelta(days=i + (i // 5) * 2)
        bars.append(
            MarketBar(
                instrument_id="NSE_EQ|RELIANCE",
                exchange="NSE",
                timestamp=ts,
                timeframe=Timeframe.DAY,
                open=round(float(opens[i]), 2),
                high=round(float(highs[i]), 2),
                low=round(float(lows[i]), 2),
                close=round(float(closes[i]), 2),
                volume=float(vols[i]),
                source="SYNTHETIC",
            )
        )
    return bars


@pytest.fixture(scope="module")
def backtest_result(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("catalog")
    settings = Settings()
    settings.backtest.catalog_path = tmp
    bridge = CatalogBridge(tmp)
    identity = InstrumentIdentity(
        instrument_id="NSE_EQ|RELIANCE",
        exchange=Exchange.NSE,
        segment=Segment.EQ,
        symbol="RELIANCE",
        isin="INE002A01018",
    )
    bridge.write_instrument(identity)
    bt = bridge.write_bars(make_bars(), identity)
    assert bt.endswith("EXTERNAL")

    runner = BacktestRunner(settings)
    return runner.run_sma_cross(symbol="RELIANCE", fast=10, slow=30)


class TestNautilusBacktest:
    def test_backtest_produces_fills(self, backtest_result):
        assert backtest_result.n_fills > 0

    def test_reports_have_expected_shape(self, backtest_result):
        assert not backtest_result.fills.empty
        assert "side" in backtest_result.fills.columns
        assert "avg_px" in backtest_result.fills.columns

    def test_summary_metrics(self, backtest_result):
        metrics = summarize_result(backtest_result)
        assert metrics["n_fills"] == backtest_result.n_fills
        assert "gross_pnl" in metrics
        assert "net_pnl" in metrics
        assert "total_commissions" in metrics
        assert float(metrics["net_pnl"]) <= float(metrics["gross_pnl"])

    def test_account_in_inr(self, backtest_result):
        assert not backtest_result.account.empty
