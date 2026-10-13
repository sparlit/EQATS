from __future__ import annotations

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


"""Canary tests — four non-negotiable correctness proofs for the evaluation engine.

These tests use ONLY synthetic data (no network, no disk I/O).
They must ALL pass before any real signal is trusted.

Test 1: PERFECT FORESIGHT
    Inject signal = forward 1-day return (lookahead).
    Assert: mean IC at h=1 > 0.98.

Test 2: PURE NOISE
    Inject signal from fixed-seed standard normal, independent of prices.
    Assert: |IC| < 0.02 and |IC t-stat| < 2.5.

Test 3: LEAK DETECTOR
    Inject a signal that is the exact forward return (perfect lookahead).
    Assert: IC(leaked) > IC(correct) + 0.5.

Test 4: DATE SHUFFLE
    Shuffle signal dates while leaving returns intact.
    Assert: |mean IC| < 0.05.
"""


import numpy as np
import pandas as pd
from nse_alpha.eval.alignment import IMPLEMENTATION_GAP, align_signal_to_returns
from nse_alpha.eval.ic import compute_ic_series, compute_ic_stats

# ---------------------------------------------------------------------------
# Synthetic data factory
# ---------------------------------------------------------------------------


def _make_synthetic_panel(
    n_symbols: int = 50,
    n_days: int = 350,
    seed: int = 42,
) -> pd.DataFrame:
    """Build a minimal synthetic panel with MultiIndex(date, symbol).

    All prices follow geometric random walks.  adj_close == close (no splits).
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2018-01-01", periods=n_days, freq="B")
    symbols = [f"STOCK{i:03d}.NS" for i in range(n_symbols)]

    rows: list[pd.DataFrame] = []
    for sym in symbols:
        log_rets = rng.normal(0.0005, 0.015, size=n_days)
        prices = 100.0 * np.exp(np.cumsum(log_rets))
        volume = rng.integers(100_000, 10_000_000, size=n_days).astype(float)

        df = pd.DataFrame(
            {
                "date": dates,
                "symbol": sym,
                "open": prices * (1 + rng.normal(0, 0.002, n_days)),
                "high": prices * (1 + np.abs(rng.normal(0, 0.005, n_days))),
                "low": prices * (1 - np.abs(rng.normal(0, 0.005, n_days))),
                "close": prices,
                "adj_close": prices,
                "volume": volume,
                "turnover_value": prices * volume,
            }
        )
        rows.append(df)

    panel = pd.concat(rows).set_index(["date", "symbol"]).sort_index()
    return panel


# ---------------------------------------------------------------------------
# Test 1: PERFECT FORESIGHT
# ---------------------------------------------------------------------------


class TestPerfectForesight:
    """Signal = forward 1-day return (lookahead) -> IC must be > 0.98."""

    def test_ic_near_one(self) -> None:
        """Perfect foresight signal achieves IC > 0.98 at h=1."""
        panel = _make_synthetic_panel(n_symbols=50, n_days=350)
        adj = panel["adj_close"].unstack("symbol")
        daily_log_ret = np.log(adj / adj.shift(1))

        # alignment.py computes: fwd_return[t] = daily_log_ret[t + IMPLEMENTATION_GAP + h]
        # For h=1: fwd_return[t] = daily_log_ret[t + 2]
        # Perfect signal: signal[t] = daily_log_ret[t + IMPLEMENTATION_GAP + 1]
        # This deliberately looks ahead — that's the point of the test.
        perfect_fw = daily_log_ret.shift(-(IMPLEMENTATION_GAP + 1))
        signal_series = (
            perfect_fw.stack(future_stack=True)  # type: ignore[call-arg]
            .rename("signal")
            .dropna()
        )

        aligned = align_signal_to_returns(signal_series, panel, horizon=1)
        ic = compute_ic_series(aligned)
        mean_ic = float(ic.dropna().mean())

        assert mean_ic > 0.98, (
            f"[CANARY FAIL] Perfect foresight IC={mean_ic:.4f} is not > 0.98. "
            "Alignment is broken — every downstream number is garbage."
        )


# ---------------------------------------------------------------------------
# Test 2: PURE NOISE
# ---------------------------------------------------------------------------


class TestPureNoise:
    """Random signal independent of prices → IC must be near zero."""

    def test_noise_ic_near_zero(self) -> None:
        """Pure noise signal has |IC| < 0.02 and |t-stat| < 2.5."""
        panel = _make_synthetic_panel(n_symbols=50, n_days=350, seed=99)
        rng = np.random.default_rng(42)  # fixed seed, independent of price seed

        noise = rng.standard_normal(len(panel))
        signal_series = pd.Series(noise, index=panel.index, name="signal")

        aligned = align_signal_to_returns(signal_series, panel, horizon=1)
        ic = compute_ic_series(aligned)
        stats = compute_ic_stats(ic)

        mean_ic = stats["ic_mean"]
        ic_tstat = stats["ic_tstat"]

        assert abs(mean_ic) < 0.02, (
            f"[CANARY FAIL] Noise IC={mean_ic:.4f} exceeds 0.02. "
            "Evaluation engine detecting spurious signal in random data."
        )
        assert abs(ic_tstat) < 2.5, (
            f"[CANARY FAIL] Noise t-stat={ic_tstat:.4f} exceeds 2.5. "
            "Possible systematic bias in evaluation engine."
        )


# ---------------------------------------------------------------------------
# Test 3: LEAK DETECTOR
# ---------------------------------------------------------------------------


class TestLeakDetector:
    """Inject a perfect lookahead signal → leaked IC must be >> correct IC.

    Alignment math (alignment.py):
        fwd_return[t] = daily_log_ret[t + IMPLEMENTATION_GAP + h]
                      = daily_log_ret[t + 2]  (for h=1, gap=1)

    LEAKED signal: signal[t] = daily_log_ret[t + IMPLEMENTATION_GAP + 1]
                             = daily_log_ret[t + 2]
    This is *exactly* what fwd_return[t] equals → IC ≈ 1.0.

    CORRECT signal: signal[t] = daily_log_ret[t - 1]
    On a random walk, this is independent of fwd_return[t] → IC ≈ 0.

    The gap is mathematically guaranteed to be >> 0.5.
    """

    def test_leaked_ic_materially_higher(self) -> None:
        """Mathematically exact lookahead signal gives IC≈1; correct signal gives IC≈0."""
        panel = _make_synthetic_panel(n_symbols=50, n_days=400, seed=7)

        adj = panel["adj_close"].unstack("symbol")
        log_ret = np.log(adj / adj.shift(1))

        # LEAKED signal: signal[t] = log_ret[t + IMPLEMENTATION_GAP + 1] = log_ret[t+2]
        # This is exactly fwd_return[t] as computed by align_signal_to_returns.
        leaked_raw = log_ret.shift(-(IMPLEMENTATION_GAP + 1))
        signal_leaked = (
            leaked_raw.stack(future_stack=True)  # type: ignore[call-arg]
            .rename("signal")
            .dropna()
        )

        # CORRECT signal: yesterday's return — independent of f[t+2] on a random walk
        signal_correct = (
            log_ret.shift(1)
            .stack(future_stack=True)  # type: ignore[call-arg]
            .rename("signal")
            .dropna()
        )

        aligned_correct = align_signal_to_returns(signal_correct, panel, horizon=1)
        aligned_leaked = align_signal_to_returns(signal_leaked, panel, horizon=1)

        ic_correct = float(compute_ic_series(aligned_correct).dropna().mean())
        ic_leaked = float(compute_ic_series(aligned_leaked).dropna().mean())

        # Leaked IC should be near 1.0; correct IC near 0; gap >> 0.5
        assert ic_leaked > ic_correct + 0.5, (
            f"[CANARY FAIL] Leaked IC={ic_leaked:.4f} not materially higher than "
            f"correct IC={ic_correct:.4f} (diff={ic_leaked - ic_correct:.4f}). "
            f"Expected: leaked≈1.0, correct≈0.0. "
            "Pipeline cannot detect one-day lookahead leaks."
        )


# ---------------------------------------------------------------------------
# Test 4: DATE SHUFFLE
# ---------------------------------------------------------------------------


class TestDateShuffle:
    """Shuffle signal date index → IC must collapse toward zero."""

    def test_shuffled_ic_near_zero(self) -> None:
        """Destroying temporal structure collapses IC to near zero."""
        rng_state = np.random.default_rng(13)
        panel = _make_synthetic_panel(n_symbols=50, n_days=400, seed=13)

        # 5-day reversal signal
        adj = panel["adj_close"].unstack("symbol")
        log_ret = np.log(adj / adj.shift(1))
        rev5 = -log_ret.rolling(5).sum()
        signal_unshuffled = (
            rev5.stack(future_stack=True)  # type: ignore[call-arg]
            .rename("signal")
            .dropna()
        )

        # Shuffle the date level
        dates_unique = signal_unshuffled.index.get_level_values("date").unique().to_numpy()
        shuffled_dates = rng_state.permutation(dates_unique)
        date_map = dict(zip(dates_unique, shuffled_dates, strict=False))

        orig_dates = signal_unshuffled.index.get_level_values("date")
        new_dates = pd.DatetimeIndex([date_map[d] for d in orig_dates])
        symbols = signal_unshuffled.index.get_level_values("symbol")
        shuffled_index = pd.MultiIndex.from_arrays([new_dates, symbols], names=["date", "symbol"])
        signal_shuffled = pd.Series(
            signal_unshuffled.values, index=shuffled_index, name="signal"
        ).sort_index()

        aligned = align_signal_to_returns(signal_shuffled, panel, horizon=1)
        mean_ic = float(compute_ic_series(aligned).dropna().mean())

        assert abs(mean_ic) < 0.05, (
            f"[CANARY FAIL] Date-shuffled IC={mean_ic:.4f} is not near zero. "
            "Signal dates are not being properly aligned to return dates."
        )
