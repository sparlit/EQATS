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


"""Tests for backend/performance.py (C1 plan item + P0 integrity)."""
import datetime
import os
import random
import sys
import unittest
from unittest.mock import patch

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import performance  # noqa: E402


class TestCohortStats(unittest.TestCase):
    def test_empty(self):
        s = performance.cohort_stats([])
        assert s["n"] == 0
        assert s["median"] is None
        assert s["q1"] is None
        assert s["hit_rate"] is None

    def test_single(self):
        s = performance.cohort_stats([5.0])
        assert s["n"] == 1
        assert s["median"] == 5.0
        assert s["mean"] == 5.0
        assert s["hit_rate"] == 1.0

    def test_known_distribution(self):
        vals = [float(i) for i in range(1, 11)]
        s = performance.cohort_stats(vals)
        assert s["n"] == 10
        assert s["median"] == 5.5
        assert s["q1"] == 3.25
        assert s["q3"] == 7.75
        assert s["mean"] == 5.5
        assert s["hit_rate"] == 1.0

    def test_hit_rate_mixed(self):
        s = performance.cohort_stats([-2.0, -1.0, 0.0, 1.0, 3.0])
        # > 0 only: 1.0 and 3.0 → 2/5
        assert s["hit_rate"] == 0.4

    def test_skewed(self):
        vals = [-5.0, -3.0, -1.0, 0.0, 0.0, 1.0, 50.0]
        s = performance.cohort_stats(vals)
        assert s["median"] == 0.0
        assert s["mean"] > s["median"]


class TestScoreBucket(unittest.TestCase):
    def test_pass_v3_buckets(self):
        assert performance.score_bucket(85.0) == "63+"
        assert performance.score_bucket(63.0) == "63+"
        assert performance.score_bucket(62.9) == "60-63"
        assert performance.score_bucket(60.0) == "60-63"
        assert performance.score_bucket(59.9) == "55-60"
        assert performance.score_bucket(55.0) == "55-60"
        assert performance.score_bucket(54.9) == "45-55"
        assert performance.score_bucket(45.0) == "45-55"
        assert performance.score_bucket(44.9) == "<45"
        assert performance.score_bucket(21.9) == "<45"
        assert performance.score_bucket(None) == "unknown"

    def test_pass_v2_legacy_unchanged(self):
        # pass_v2 is kept for re-bucketing historical per_name rows —
        # its boundaries must never drift.
        assert performance.score_bucket_pass_v2(85.0) == "60+"
        assert performance.score_bucket_pass_v2(60.0) == "60+"
        assert performance.score_bucket_pass_v2(59.9) == "55-59"
        assert performance.score_bucket_pass_v2(55.0) == "55-59"
        assert performance.score_bucket_pass_v2(54.9) == "50-54"
        assert performance.score_bucket_pass_v2(50.0) == "50-54"
        assert performance.score_bucket_pass_v2(49.9) == "<50"
        assert performance.score_bucket_pass_v2(None) == "unknown"


class TestBootstrapCI(unittest.TestCase):
    def test_deterministic(self):
        vals = sorted(float(i % 7) - 3 + 0.1 * (i % 3) for i in range(120))
        a = performance.bootstrap_ci(vals)
        b = performance.bootstrap_ci(vals)
        assert a == b

    def test_below_min_n_returns_none(self):
        assert performance.bootstrap_ci([1.0, 2.0, 3.0]) is None

    def test_at_min_n_returns_interval(self):
        vals = sorted(float(i % 5) - 2 for i in range(performance.BOOTSTRAP_MIN_N))
        ci = performance.bootstrap_ci(vals)
        assert ci is not None
        assert ci["low"] <= ci["high"]

    def test_interval_brackets_mean_and_tightens_with_n(self):
        rng = random.Random(1234)
        vals = sorted(rng.gauss(2.0, 1.0) for _ in range(400))
        ci = performance.bootstrap_ci(vals)
        mean = sum(vals) / len(vals)
        assert ci["low"] < mean
        assert ci["high"] > mean
        narrow = performance.bootstrap_ci(sorted(rng.gauss(2.0, 1.0) for _ in range(4000)))
        assert narrow["high"] - narrow["low"] < ci["high"] - ci["low"]


def _scan(symbols_with_scores, idx_pct=-1.5, confirmations=None, generated_at="2026-07-15T10:31:00+00:00"):
    stocks = []
    for sym, sc in symbols_with_scores:
        s = {
            "symbol": sym,
            "yf_ticker": f"{sym}.NS",
            "gate_pass": True,
            "swing_score": sc,
            "market_index_pct_from_ema200": idx_pct,
        }
        if confirmations and sym in confirmations:
            s["confirmation_state"] = confirmations[sym]
        stocks.append(s)
    return {
        "generated_at": generated_at,
        "stocks": stocks,
    }


def _perf(excess):
    return {
        "stock_return_pct": round(excess, 2),
        "index_return_pct": 0.0,
        "excess_return_pct": round(excess, 2),
        "untrackable": False,
        "reason": None,
    }


class TestBuildPayload(unittest.TestCase):
    def test_per_scan_and_buckets(self):
        snapshots = [
            ("2026-07-15-pm", _scan([("A", 62), ("B", 57), ("C", 52), ("D", 40)])),
            ("2026-07-16-pm", _scan([("A", 61), ("B", 56), ("E", 65)])),
        ]
        forward = {
            ("2026-07-15-pm", "A"): {w: _perf(2.0) for w in (5, 10, 20)},
            ("2026-07-15-pm", "B"): {w: _perf(2.0) for w in (5, 10, 20)},
            ("2026-07-15-pm", "C"): {w: _perf(2.0) for w in (5, 10, 20)},
            ("2026-07-15-pm", "D"): {
                w: {
                    "untrackable": True,
                    "reason": "delisted",
                    "stock_return_pct": None,
                    "index_return_pct": None,
                    "excess_return_pct": None,
                }
                for w in (5, 10, 20)
            },
            ("2026-07-16-pm", "A"): {w: _perf(2.0) for w in (5, 10, 20)},
            ("2026-07-16-pm", "B"): {w: _perf(2.0) for w in (5, 10, 20)},
            ("2026-07-16-pm", "E"): {w: _perf(2.0) for w in (5, 10, 20)},
        }
        payload = performance.build_performance_payload(snapshots, forward, retention_days=90)

        assert payload["meta"]["snapshots_used"] == 2
        assert payload["meta"]["total_passed"] == 7
        assert payload["meta"]["bucket_scheme"] == "pass_v3"
        assert payload["meta"]["bucket_scheme_history"] == ["pass_v2", "pass_v3"]
        assert payload["retention_days"] == 90

        ps20 = [c["windows"]["T+20"]["n"] for c in payload["per_scan"]]
        assert ps20 == [3, 3]

        buckets = payload["windows"]["T+20"]["buckets"]
        # A(62),A(61),E(65) → 60-63 = 2, 63+ = 1; B(57),B(56) → 55-60 = 2; C(52) → 45-55
        assert buckets["63+"]["n"] == 1
        assert buckets["60-63"]["n"] == 2
        assert buckets["55-60"]["n"] == 2
        assert buckets["45-55"]["n"] == 1
        assert buckets["<45"]["n"] == 0
        assert buckets["63+"]["median"] == 2.0
        assert buckets["63+"]["hit_rate"] == 1.0
        assert buckets["63+"]["ci95"] is None  # n=1 < BOOTSTRAP_MIN_N

        assert payload["windows"]["T+20"]["untrackable_count"] == 1
        assert payload["windows"]["T+5"]["untrackable_count"] == 1
        assert payload["windows"]["T+5"]["trackable_count"] == 6
        assert payload["meta"]["trackable_count"]["T+5"] == 6

    def test_window_not_closed_excluded_from_untrackable(self):
        snapshots = [("2026-07-15-pm", _scan([("A", 62)]))]
        forward = {
            ("2026-07-15-pm", "A"): {
                w: {
                    "stock_return_pct": None,
                    "index_return_pct": None,
                    "excess_return_pct": None,
                    "untrackable": False,
                    "reason": "window_not_closed",
                }
                for w in (5, 10, 20)
            }
        }
        payload = performance.build_performance_payload(snapshots, forward)
        w = payload["windows"]["T+5"]
        assert w["untrackable_count"] == 0
        assert w["window_not_closed_count"] == 1
        assert w["trackable_count"] == 0
        row = payload["per_name"][0]
        assert not row["windows"]["T+5"]["untrackable"]
        assert row["windows"]["T+5"]["reason"] == "window_not_closed"

    def test_no_snapshots_emits_empty_payload(self):
        payload = performance.build_performance_payload([], {}, retention_days=0)
        assert payload["meta"]["snapshots_used"] == 0
        assert payload["per_scan"] == []
        for w_label in ("T+5", "T+10", "T+20"):
            assert w_label in payload["windows"]
            for b in ("63+", "60-63", "55-60", "45-55", "<45", "unknown"):
                assert payload["windows"][w_label]["buckets"][b]["n"] == 0


class TestRegimeAndPerName(unittest.TestCase):
    def test_regime_tag_thresholds(self):
        assert performance.regime_tag(3.0) == "risk_on"
        assert performance.regime_tag(2.01) == "risk_on"
        assert performance.regime_tag(2.0) == "neutral"
        assert performance.regime_tag(-2.01) == "risk_off"
        assert performance.regime_tag(None) == "unknown"

    def test_per_name_rows_carry_regime_and_confirmation(self):
        snapshots = [
            (
                "2026-07-15-pm",
                _scan(
                    [("A", 62), ("B", 57)],
                    idx_pct=-3.5,
                    confirmations={"A": "confirmed", "B": "anticipatory"},
                ),
            ),
        ]
        forward = {
            ("2026-07-15-pm", "A"): {w: _perf(2.0) for w in (5, 10, 20)},
            ("2026-07-15-pm", "B"): {w: _perf(-1.0) for w in (5, 10, 20)},
        }
        payload = performance.build_performance_payload(snapshots, forward)
        per_name = payload["per_name"]
        assert len(per_name) == 2
        by_sym = {r["symbol"]: r for r in per_name}
        assert by_sym["A"]["regime"] == "risk_off"
        assert by_sym["A"]["confirmation"] == "confirmed"
        assert by_sym["A"]["bucket"] == "60-63"
        assert by_sym["B"]["confirmation"] == "anticipatory"
        assert by_sym["B"]["windows"]["T+20"]["excess_return_pct"] == -1.0
        assert payload["per_scan"][0]["regime"] == "risk_off"

    def test_by_regime_splits_cohorts(self):
        snapshots = [
            ("2026-07-14-pm", _scan([("X", 62)], idx_pct=3.0)),
            ("2026-07-15-pm", _scan([("Y", 62)], idx_pct=-3.0)),
        ]
        forward = {
            ("2026-07-14-pm", "X"): {w: _perf(4.0) for w in (5, 10, 20)},
            ("2026-07-15-pm", "Y"): {w: _perf(-2.0) for w in (5, 10, 20)},
        }
        payload = performance.build_performance_payload(snapshots, forward)
        t20 = payload["by_regime"]["T+20"]
        assert t20["risk_on"]["n"] == 1
        assert t20["risk_on"]["median"] == 4.0
        assert t20["risk_off"]["n"] == 1
        assert t20["risk_off"]["median"] == -2.0

    def test_by_regime_buckets_cross_tab(self):
        # Drawer table (1.4.0): per (window, bucket, regime) cells with
        # cohort stats, regime tag from the scan, bucket from pass_v3.
        snapshots = [
            ("2026-07-14-pm", _scan([("X", 64), ("Z", 57)], idx_pct=3.0)),
            ("2026-07-15-pm", _scan([("Y", 64)], idx_pct=-3.0)),
        ]
        forward = {
            ("2026-07-14-pm", "X"): {w: _perf(4.0) for w in (5, 10, 20)},
            ("2026-07-14-pm", "Z"): {w: _perf(1.0) for w in (5, 10, 20)},
            ("2026-07-15-pm", "Y"): {w: _perf(-2.0) for w in (5, 10, 20)},
        }
        payload = performance.build_performance_payload(snapshots, forward)
        cross = payload["windows"]["T+5"]["by_regime_buckets"]
        assert cross["63+"]["risk_on"]["n"] == 1
        assert cross["63+"]["risk_on"]["mean"] == 4.0
        assert cross["63+"]["risk_off"]["n"] == 1
        assert cross["63+"]["risk_off"]["mean"] == -2.0
        assert cross["55-60"]["risk_on"]["n"] == 1
        assert cross["55-60"]["risk_off"]["n"] == 0
        # Every bucket label present, every regime key present (frontend
        # iterates both unconditionally).
        for b in performance.BUCKET_ORDER:
            assert b in cross
            for rg in ("risk_on", "neutral", "risk_off", "unknown"):
                assert rg in cross[b]
        # CI present on populated cells (n=1 < MIN_N so None here)
        assert cross["63+"]["risk_on"]["ci95"] is None

    def test_per_name_untrackable_marked(self):
        snapshots = [("2026-07-15-pm", _scan([("A", 62)]))]
        payload = performance.build_performance_payload(snapshots, {})
        row = payload["per_name"][0]
        assert row["windows"]["T+20"]["untrackable"]
        assert row["windows"]["T+20"]["excess_return_pct"] is None


class TestSessionIndexAndCloses(unittest.TestCase):
    def test_t_plus_session(self):
        # Mon-Fri style sessions
        base = datetime.date(2026, 7, 13)  # Monday
        sessions = [
            base + datetime.timedelta(days=i) for i in range(30) if (base + datetime.timedelta(days=i)).weekday() < 5
        ]
        # scan on Monday → T+0 = Monday, T+5 = next Monday
        assert performance.t_plus_session(sessions, base, 0) == base
        assert performance.t_plus_session(sessions, base, 5) == base + datetime.timedelta(days=7)
        # scan on Saturday snaps forward to Monday
        sat = base + datetime.timedelta(days=5)
        assert performance.t_plus_session(sessions, sat, 0) == base + datetime.timedelta(days=7)

    def test_t_plus_beyond_calendar_returns_none(self):
        sessions = [datetime.date(2026, 7, 13), datetime.date(2026, 7, 14)]
        assert performance.t_plus_session(sessions, sessions[0], 5) is None

    def test_closes_dict_flat(self):
        idx = pd.to_datetime(["2026-07-13", "2026-07-14"])
        df = pd.DataFrame({"Close": [100.0, 102.0], "Open": [99.0, 101.0]}, index=idx)
        got = performance.closes_dict_from_frame(df)
        assert got["2026-07-13"] == 100.0
        assert got["2026-07-14"] == 102.0

    def test_closes_dict_multiindex(self):
        idx = pd.to_datetime(["2026-07-13", "2026-07-14"])
        cols = pd.MultiIndex.from_tuples([("Close", "AAA.NS"), ("Open", "AAA.NS")])
        df = pd.DataFrame([[100.0, 99.0], [102.0, 101.0]], index=idx, columns=cols)
        got = performance.closes_dict_from_frame(df)
        assert got["2026-07-13"] == 100.0

    def test_cache_entry_usable_rejects_empty(self):
        assert not performance.cache_entry_usable(None, min_end_date="2026-08-01")
        assert not performance.cache_entry_usable({"end_date": "2026-08-01", "closes": {}}, min_end_date="2026-08-01")
        assert performance.cache_entry_usable(
            {"end_date": "2026-08-15", "closes": {"2026-07-13": 1.0}}, min_end_date="2026-08-01"
        )
        assert not performance.cache_entry_usable(
            {"end_date": "2026-07-01", "closes": {"2026-07-13": 1.0}}, min_end_date="2026-08-01"
        )


class TestFetchForwardReturnsInjected(unittest.TestCase):
    def _make_sessions(self, start, n_days=40):
        """Build Mon-Fri session closes for index + stock."""
        dates = []
        d = start
        while len(dates) < n_days:
            if d.weekday() < 5:
                dates.append(d)
            d += datetime.timedelta(days=1)
        return dates

    def test_fetch_computes_excess_and_respects_not_closed(self):
        start = datetime.date(2026, 6, 1)
        sessions = self._make_sessions(start, 50)
        # Build synthetic OHLCV frames
        nifty = {d.isoformat(): 100.0 + i for i, d in enumerate(sessions)}
        stock = {d.isoformat(): 50.0 + i * 0.5 for i, d in enumerate(sessions)}

        def fake_download(tickers, start_s, end_s):
            frames = {}
            for tk in tickers:
                series = nifty if tk == "^NSEI" else stock
                idx = pd.to_datetime(list(series.keys()))
                frames[tk] = pd.DataFrame({"Close": [series[k.strftime("%Y-%m-%d")] for k in idx]}, index=idx)
            if len(tickers) == 1:
                return frames[tickers[0]]
            # Multi-ticker group_by=ticker style
            return pd.concat(frames, axis=1)

        scan_date = sessions[5]  # mid series
        # as_of far enough for T+5 but not T+20 relative to a late scan
        as_of = sessions[5 + 8]  # T+5 closed, T+20 maybe not depending on length
        snapshots = [
            (
                "2026-06-label-pm",
                _scan(
                    [("AAA", 55)],
                    generated_at=scan_date.isoformat() + "T10:00:00+00:00",
                ),
            ),
        ]
        out = performance.fetch_forward_returns(
            snapshots,
            no_cache=True,
            today=as_of,
            download_fn=fake_download,
            max_attempts=1,
        )
        row = out[("2026-06-label-pm", "AAA")]
        assert not row[5]["untrackable"]
        assert row[5]["excess_return_pct"] is not None
        # T+20 should be window_not_closed if as_of is only +8 sessions
        assert row[20]["reason"] == "window_not_closed"

    def test_empty_download_not_cached(self, tmp_path_factory=None):
        import tempfile

        def empty_download(tickers, start_s, end_s):
            return pd.DataFrame()

        snapshots = [
            (
                "2026-07-01-pm",
                _scan(
                    [("AAA", 55)],
                    generated_at="2026-07-01T10:00:00+00:00",
                ),
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = performance.fetch_forward_returns(
                snapshots,
                cache_dir=tmp,
                no_cache=False,
                today=datetime.date(2026, 7, 28),
                download_fn=empty_download,
                max_attempts=1,
            )
            cache_path = os.path.join(tmp, "performance_prices.json")
            # Either no cache file, or no empty-poison entries with ok closes
            if os.path.exists(cache_path):
                import json

                with open(cache_path) as f:
                    cache = json.load(f)
                for entry in cache.values():
                    assert entry.get("closes"), "empty closes must not be cached"
            # All missing stock price or window issues — not silently trackable
            row = out[("2026-07-01-pm", "AAA")]
            assert (
                row[5]["untrackable"]
                or row[5]["reason"] == "window_not_closed"
                or row[5]["reason"] == "missing_stock_price"
            )


class TestOutcomeQuality(unittest.TestCase):
    def test_all_open_ok(self):
        payload = {
            "meta": {
                "snapshots_used": 2,
                "trackable_count": {"T+5": 0},
                "untrackable_count": {"T+5": 0},
                "window_not_closed_count": {"T+5": 10},
            }
        }
        ok, _ = performance.outcome_quality_ok(payload)
        assert ok

    def test_all_untrackable_fails(self):
        payload = {
            "meta": {
                "snapshots_used": 2,
                "trackable_count": {"T+5": 0},
                "untrackable_count": {"T+5": 10},
                "window_not_closed_count": {"T+5": 0},
            }
        }
        ok, reason = performance.outcome_quality_ok(payload)
        assert not ok
        assert "broken" in reason


class TestComputePerformanceCLI(unittest.TestCase):
    def test_empty_snapshots_writes_payload(self):
        import subprocess
        import tempfile

        script = os.path.join(BACKEND_DIR, "scripts", "compute_performance.py")
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)

        with tempfile.TemporaryDirectory() as tmp:
            snaps = os.path.join(tmp, "snapshots")
            os.makedirs(snaps)
            out = os.path.join(tmp, "performance.json")
            empty_proc = subprocess.run(
                [sys.executable, script, "--snapshots", snaps, "--output", out],
                cwd=BACKEND_DIR,
                env=env,
                capture_output=True,
                text=True,
            )
            assert empty_proc.returncode == 0, empty_proc.stderr
            assert os.path.isfile(out)


class TestCoverageHelper(unittest.TestCase):
    def test_compute_coverage(self):
        # Import from scanner
        sys.path.insert(0, BACKEND_DIR)
        import scanner

        records = [
            {"current_price": 100.0, "gate_fail_reason": None},
            {"current_price": None, "gate_fail_reason": "fetch_failed: Too Many Requests. Rate limited."},
            {"current_price": 50.0, "gate_fail_reason": "rsi 50 outside"},
        ]
        cov = scanner.compute_coverage(records)
        assert cov["priced"] == 2
        assert cov["universe"] == 3
        assert cov["rate_limited"] == 1
        self.assertAlmostEqual(cov["pct"], 2 / 3, places=4)

    def test_is_rate_limited_row_uses_tech_price(self):
        import scanner

        assert not scanner._is_rate_limited_row({"tech_current_price": 100.0, "gate_fail_reason": "rsi 50 outside"})
        assert scanner._is_rate_limited_row(
            {"tech_current_price": None, "gate_fail_reason": "fetch_failed: Too Many Requests. Rate limited."}
        )
        assert not scanner._is_rate_limited_row({"tech_current_price": None, "gate_fail_reason": "f_score 4 < 6"})

    def test_recover_rate_limited_rows(self):
        import scanner

        rows = [
            {"symbol": "OK", "tech_current_price": 10.0, "gate_fail_reason": None},
            {
                "symbol": "RL",
                "tech_current_price": None,
                "gate_fail_reason": "fetch_failed: Too Many Requests. Rate limited.",
            },
        ]
        inputs = {
            "OK": {"symbol": "OK", "yf_ticker": "OK.NS"},
            "RL": {"symbol": "RL", "yf_ticker": "RL.NS"},
        }

        def fake_eval(rdict, *a, **k):
            return {
                **rdict,
                "tech_current_price": 42.0,
                "gate_pass": False,
                "gate_fail_reason": "rsi 50 outside",
            }

        with unittest.mock.patch.object(scanner, "_evaluate_one_stock", side_effect=fake_eval):
            out = scanner._recover_rate_limited_rows(
                rows,
                inputs_by_symbol=inputs,
                sleep_between_calls=0,
                surveillance_payload={},
                bhavcopy_payload={},
                skip_holdings=True,
                skip_corporate_actions=True,
                lenient_external_gates=False,
                pause_every=100,
                pause_s=0,
            )
        by_sym = {r["symbol"]: r for r in out}
        assert by_sym["RL"]["tech_current_price"] == 42.0
        assert by_sym["OK"]["tech_current_price"] == 10.0


if __name__ == "__main__":
    unittest.main()
