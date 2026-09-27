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


"""Deterministic replay: same catalog + same config => identical results.

Phase 8 principle: if we cannot reproduce a research result from the same
dataset and configuration, we do not call it production quality.
"""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from indian_quant.config import Settings
from indian_quant.nautilus.adapters.backtest import BacktestRunner, summarize_result
from indian_quant.nautilus.data.catalog import CatalogBridge
from indian_quant.schemas import Exchange, InstrumentIdentity, MarketBar, Segment, Timeframe


def make_bars(seed: int = 99) -> list[MarketBar]:
    rng = np.random.default_rng(seed)
    n = 220
    closes = 1500 * np.cumprod(1 + rng.normal(0.0006, 0.01, n))
    opens = np.concatenate([[closes[0]], closes[:-1]])
    highs = np.maximum(opens, closes) * (1 + np.abs(rng.normal(0, 0.003, n)))
    lows = np.minimum(opens, closes) * (1 - np.abs(rng.normal(0, 0.003, n)))
    vols = rng.integers(500_000, 3_000_000, n)
    start = datetime(2025, 1, 1, tzinfo=UTC)
    bars = []
    d = start
    for i in range(n):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        bars.append(
            MarketBar(
                instrument_id="NSE_EQ|REPLAY",
                exchange="NSE",
                timestamp=d,
                timeframe=Timeframe.DAY,
                open=round(float(opens[i]), 2),
                high=round(float(highs[i]), 2),
                low=round(float(lows[i]), 2),
                close=round(float(closes[i]), 2),
                volume=float(vols[i]),
                source="SYNTHETIC",
            )
        )
        d += timedelta(days=1)
    return bars


@pytest.fixture(scope="module")
def catalog_settings(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("replay")
    settings = Settings()
    settings.backtest.catalog_path = tmp
    bridge = CatalogBridge(tmp)
    identity = InstrumentIdentity(
        instrument_id="NSE_EQ|REPLAY",
        exchange=Exchange.NSE,
        segment=Segment.EQ,
        symbol="REPLAY",
    )
    bridge.write_instrument(identity)
    bridge.write_bars(make_bars(), identity)
    return settings


class TestDeterministicReplay:
    def test_two_runs_identical(self, catalog_settings):
        runner = BacktestRunner(catalog_settings)
        r1 = runner.run_sma_cross(symbol="REPLAY", fast=8, slow=21)
        r2 = runner.run_sma_cross(symbol="REPLAY", fast=8, slow=21)

        assert r1.n_fills == r2.n_fills > 0

        cols = [c for c in ("side", "filled_qty", "avg_px") if c in r1.fills.columns]
        f1 = r1.fills[cols].astype(str).sort_values(list(cols)).reset_index(drop=True)
        f2 = r2.fills[cols].astype(str).sort_values(list(cols)).reset_index(drop=True)
        pd.testing.assert_frame_equal(f1, f2)

        m1, m2 = summarize_result(r1), summarize_result(r2)
        for key in ("gross_pnl", "net_pnl", "total_commissions", "n_closed_positions"):
            assert m1[key] == m2[key], key

    def test_config_change_changes_outcome_or_not_but_is_recorded(self, catalog_settings):
        runner = BacktestRunner(catalog_settings)
        a = runner.run_sma_cross(symbol="REPLAY", fast=5, slow=60)
        b = runner.run_sma_cross(symbol="REPLAY", fast=10, slow=30)
        assert a.config != b.config
