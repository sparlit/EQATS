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


"""Delivery feature + signal evaluation tests."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from indian_quant.features.delivery import (  # noqa: E402
    SIGNAL_NAMES,
    add_features,
    prepare_frame,
    signal_mask,
)
from indian_quant.research.signals import (  # noqa: E402
    evaluate_bucket,
    forward_returns,
    stability_split,
    summarize,
)


def make_symbol_frame(n: int = 120, base_deliv: float = 45.0, seed: int = 1):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2026-01-01", periods=n, freq="B", tz="UTC")
    close = 100 * np.cumprod(1 + rng.normal(0.001, 0.01, n))
    deliv = np.clip(base_deliv + rng.normal(0, 8, n), 5, 95)
    df = pd.DataFrame(
        {
            "date": dates,
            "symbol": "TEST",
            "segment": "EQ",
            "close": close,
            "deliv_pct": deliv,
            "high": close * 1.01,
            "low": close * 0.99,
            "volume": rng.integers(50_000, 200_000, n).astype(float),
        }
    )
    return add_features(prepare_frame(df))


class TestFeatures:
    def test_prepare_drops_short_frames(self):
        assert prepare_frame(pd.DataFrame({"date": [], "close": []})) is None

    def test_zscore_fires_on_spike(self):
        df = make_symbol_frame()
        spiked = df.copy()
        spiked.loc[df.index[-1], "deliv_pct"] = 95.0
        feat = add_features(prepare_frame(spiked[["date", "symbol", "segment", "close", "deliv_pct"]]))
        assert feat["deliv_z"].iloc[-1] > 2

    def test_streak_counter(self):
        df = make_symbol_frame()
        df["deliv_pct"] = 70.0
        feat = add_features(df)
        assert feat["hi_streak"].iloc[-1] == len(feat)

    def test_all_signals_known(self):
        df = make_symbol_frame()
        for name in SIGNAL_NAMES:
            mask = signal_mask(df, name)
            assert mask.dtype == bool


class TestEvaluate:
    def test_forward_returns_math(self):
        s = pd.Series([100.0, 110.0, 121.0])
        fwd = forward_returns(s, 1).tolist()
        assert fwd == pytest.approx([0.10, 0.10])

    def test_summarize_stats(self):
        out = summarize(np.array([0.01, 0.02, 0.03, -0.01]))
        assert out["n"] == 4
        assert out["mean_bps"] == pytest.approx(125.0)
        assert out["net_mean_bps"] == pytest.approx(125.0 - 107.0)
        assert out["hit_rate"] == pytest.approx(0.75)

    def test_stability_split_halves(self):
        vals = np.concatenate([np.full(50, 0.01), np.full(50, -0.01)])
        first, second = stability_split(vals)
        assert first["n"] == second["n"] == 50

    def test_evaluate_bucket_positive_edge(self):
        frames = []
        for _ in range(3):
            f = make_symbol_frame()
            f.loc[f.index[-2], "deliv_pct"] = 90.0
            f.loc[f.index[-2], "ret_1d"] = 0.05
            frames.append(f)
        results = evaluate_bucket(frames, "dz_hi_up", horizons=(1,))
        assert "1" in results
        assert results["1"]["n"] >= 1

    def test_unknown_signal_raises(self):
        with pytest.raises(KeyError):
            evaluate_bucket([], "nope")


class TestClusters:
    def test_cluster_entry_mask_first_day_only(self):
        from indian_quant.features.delivery import cluster_entry_mask

        m = pd.Series([False, True, True, False, True])
        assert list(cluster_entry_mask(m)) == [False, True, False, False, True]

    def test_cluster_evaluation_runs(self):
        frames = [make_symbol_frame() for _ in range(2)]
        results = evaluate_bucket(frames, "streak3", horizons=(3,), cluster_entries=True)
        assert isinstance(results, dict)

    def test_conditions_filter(self):
        f = make_symbol_frame()
        f["close"] = np.where(np.arange(len(f)) % 2 == 0, 40.0, 400.0)
        from indian_quant.research.signals import apply_conditions

        cond = apply_conditions(f, {"price_max": 100})
        assert cond.sum() == len(f) // 2
