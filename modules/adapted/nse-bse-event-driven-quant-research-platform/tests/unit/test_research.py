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


"""Research engine tests: features + event study on synthetic data."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from indian_quant.features import build_feature_frame, market_regime, momentum, realized_volatility
from indian_quant.research import event_study


def make_frame(n: int = 300, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = []
    d = datetime(2024, 1, 1, tzinfo=UTC)
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d)
        d += timedelta(days=1)
    close = 100 * np.cumprod(1 + rng.normal(0.0005, 0.01, n))
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": close * (1 + rng.normal(0, 0.002, n)),
            "high": close * (1 + np.abs(rng.normal(0, 0.005, n))),
            "low": close * (1 - np.abs(rng.normal(0, 0.005, n))),
            "close": close,
            "volume": rng.integers(1e6, 5e6, n).astype(float),
        }
    )


class TestFeatures:
    def test_feature_frame_columns(self):
        out = build_feature_frame(make_frame())
        for col in ("return_1d", "momentum_20d", "volatility_20d", "volume_zscore_30d", "regime"):
            assert col in out.columns

    def test_momentum_matches_manual(self):
        df = make_frame(60)
        m = momentum(df, window=20)
        expected = df["close"].iloc[59] / df["close"].iloc[39] - 1
        assert m.iloc[59] == pytest.approx(expected)

    def test_volatility_positive(self):
        v = realized_volatility(make_frame(), 20).dropna()
        assert (v > 0).all()

    def test_regime_labels_valid(self):
        regimes = market_regime(make_frame())
        assert set(regimes.dropna()) <= {"BULL", "BEAR", "SIDEWAYS", "HIGH_VOL", "LOW_VOL"}


class TestEventStudy:
    def test_significant_event_detected(self):
        rng = np.random.default_rng(3)
        n = 500
        dates = pd.date_range("2022-01-01", periods=n, freq="B", tz="UTC")
        mkt = pd.Series(rng.normal(0.0002, 0.01, n), index=dates)
        ret = mkt.copy()
        event_positions = [100, 200, 300]
        for pos in event_positions:
            ret.iloc[pos] += 0.05

        result = event_study(
            ret, mkt, pd.DatetimeIndex([dates[p] for p in event_positions]), pre=5, post=10
        )
        assert result.n_events == 3
        assert result.mean_car > 0
        assert not result.car_by_offset.empty

    def test_no_events_when_window_out_of_range(self):
        idx = pd.date_range("2022-01-01", periods=50, freq="B", tz="UTC")
        ret = pd.Series(0.001, index=idx)
        result = event_study(ret, ret * 0, pd.DatetimeIndex([idx[-1]]), pre=5, post=10)
        assert result.n_events == 0

    def test_null_event_has_small_car(self):
        rng = np.random.default_rng(11)
        n = 400
        idx = pd.date_range("2022-01-01", periods=n, freq="B", tz="UTC")
        common = rng.normal(0, 0.01, n)
        ret = pd.Series(common, index=idx)
        mkt = pd.Series(common, index=idx)
        result = event_study(ret, mkt, pd.DatetimeIndex([idx[200]]), pre=5, post=10)
        assert abs(result.mean_car) < 1e-12
