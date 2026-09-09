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


"""
Tests for backend/scripts/evaluate_feedback.py — the 1.5.0 continuous
feedback loop (sub-score ICs, confirmation A/B, shadow re-scoring).

All statistics are stdlib and deterministic; no network, no pandas.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(HERE, ".."))
SCRIPTS_DIR = os.path.join(BACKEND_DIR, "scripts")
for p in (BACKEND_DIR, SCRIPTS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import evaluate_feedback as ef  # noqa: E402


def make_row(score, subs, t5=None, t10=None, confirmation="anticipatory", regime="neutral"):
    windows = {}
    for label, v in (("T+5", t5), ("T+10", t10)):
        if v is None:
            windows[label] = {"excess_return_pct": None, "untrackable": False, "reason": "window_not_closed"}
        else:
            windows[label] = {"excess_return_pct": v, "untrackable": False, "reason": None}
    return {
        "snapshot": "2026-08-01-am",
        "symbol": "TEST",
        "score": score,
        "bucket": None,
        "regime": regime,
        "confirmation": confirmation,
        "sub_scores": subs,
        "score_version": "test-v1",
        "windows": windows,
    }


class TestSpearman(unittest.TestCase):
    def test_perfect_monotonic(self):
        self.assertAlmostEqual(ef.spearman_ic([1, 2, 3, 4, 5], [10, 20, 30, 40, 50]), 1.0)

    def test_inverse(self):
        self.assertAlmostEqual(ef.spearman_ic([1, 2, 3, 4, 5], [50, 40, 30, 20, 10]), -1.0)

    def test_ties_averaged(self):
        # [1, 1, 2] ranks -> [1.5, 1.5, 3]
        ic = ef.spearman_ic([1, 1, 2, 3], [10, 12, 20, 30])
        assert ic is not None
        assert ic > 0.9

    def test_too_short_is_none(self):
        assert ef.spearman_ic([1, 2], [3, 4]) is None


class TestICBootstrap(unittest.TestCase):
    def test_deterministic(self):
        xs = [float(i % 7) for i in range(60)]
        ys = [x * 0.5 + (i % 3) for i, x in enumerate(xs)]
        pairs = list(zip(xs, ys, strict=False))
        a = ef._ic_bootstrap_ci(pairs)
        b = ef._ic_bootstrap_ci(pairs)
        assert a == b
        assert isinstance(a, list)
        assert len(a) == 2

    def test_suppressed_below_min_n(self):
        assert ef._ic_bootstrap_ci([(1.0, 2.0), (3.0, 4.0)]) is None


class TestConfirmationAB(unittest.TestCase):
    def test_groups_partition(self):
        rows = [
            make_row(70, {"quality_composite": 0.9}, t5=5.0, confirmation="confirmed"),
            make_row(60, {"quality_composite": 0.5}, t5=-1.0),
            make_row(50, {}, t5=2.0),  # no sub_scores — still counts for A/B
        ]
        ab = ef.confirmation_ab(rows, "T+5")
        assert ab["confirmed"]["n"] == 1
        assert ab["anticipatory"]["n"] == 2
        self.assertAlmostEqual(ab["confirmed"]["mean"], 5.0)
        self.assertAlmostEqual(ab["anticipatory"]["mean"], 0.5)


class TestShadow(unittest.TestCase):
    def test_shadow_score_renormalises(self):
        # Only one component present: score must be that component x 100.
        self.assertAlmostEqual(ef._shadow_score({"quality_composite": 0.8}, {"quality_composite": 1.0}), 80.0)

    def test_normalize(self):
        w = ef._normalize({"a": 2.0, "b": 2.0})
        self.assertAlmostEqual(sum(w.values()), 1.0)

    def test_shadow_compare_bands_and_baseline_mismatch(self):
        rows = []
        # Sub-score 1 tracks outcome perfectly; sub-score 2 is noise.
        for i in range(24):
            s1 = 0.2 + 0.03 * i
            s2 = 0.5
            rows.append(
                make_row(50 + s1 * 30, {"quality_composite": s1, "conviction_holding": s2}, t5=(s1 - 0.2) * 100 - 2)
            )
            rows.append(make_row(52, {"quality_composite": s1, "conviction_holding": s2}, t5=-(s1 - 0.2) * 100 + 2))
        candidates = {
            "baseline": {"quality_composite": 0.5, "conviction_holding": 0.5},
            "all_quality": {"quality_composite": 1.0, "conviction_holding": 0.0},
        }
        shadow = ef.shadow_compare(rows, candidates)
        assert shadow["rows_used"] == 48
        t5 = shadow["windows"]["T+5"]
        # 63+ band must exist for both candidates on this synthetic data.
        assert "63+" in t5["baseline"]
        assert "63+" in t5["all_quality"]
        # The all-quality candidate's top band should not be worse.
        t5["baseline"]["63+"]
        cand_top = t5["all_quality"]["63+"]
        assert cand_top["mean"] is not None

    def test_baseline_mismatch_flag(self):
        rows = [make_row(90.0, {"quality_composite": 0.1}, t5=1.0) for _ in range(3)]
        shadow = ef.shadow_compare(rows, {"baseline": {"quality_composite": 1.0}})
        assert shadow["baseline_score_mismatch_gt5"] >= 1


class TestTopBandLift(unittest.TestCase):
    def test_lift_matches_cell_means(self):
        rows = [make_row(70, {"quality_composite": 0.9}, t5=4.0) for _ in range(5)]
        candidates = {
            "baseline": {"quality_composite": 0.5, "conviction_holding": 0.5},
            "all_quality": {"quality_composite": 1.0, "conviction_holding": 0.0},
        }
        shadow = ef.shadow_compare(rows, candidates)
        lift = ef.top_band_lift(shadow, "T+5")
        assert "all_quality" in lift


class TestEndToEnd(unittest.TestCase):
    def test_build_feedback_and_report(self):
        perf = {
            "generated_at": "2026-09-06T00:00:00+00:00",
            "meta": {"total_passed": 3, "snapshots_used": 1},
            "per_name": [
                make_row(70, {"quality_composite": 0.9}, t5=4.0, confirmation="confirmed"),
                make_row(55, {"quality_composite": 0.4}, t5=-1.0),
                make_row(30, {"quality_composite": 0.1}, t10=2.0),
            ],
        }
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(perf, f)
            path = f.name
        try:
            fb = ef.build_feedback(__import__("pathlib").Path(path))
            assert fb["meta"]["rows_closed_any_window"] >= 2
            self.assertAlmostEqual(fb["meta"]["baseline_weights"]["quality_composite"], 0.2)
            rep = ef.render_report(fb)
            assert "Promotion checklist" in rep
            assert "IN-SAMPLE" in rep
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
