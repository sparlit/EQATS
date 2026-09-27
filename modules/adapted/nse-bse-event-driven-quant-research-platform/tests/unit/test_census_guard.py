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


"""Census-drift guard tests: the SM/ST delivery-drop bug class."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from indian_quant.quality import QualityReport, detect_census_drift  # noqa: E402


class TestCensusDrift:
    def test_missing_bucket_raises_error(self):
        """Raw has SME rows but lake zero -> exactly the historical SM/ST bug."""
        report = QualityReport(dataset="t")
        detect_census_drift(
            {"EQ": 2400, "BE": 300, "SM": 292, "ST": 143},
            {"EQ": 2700, "BE": 300},
            report,
            label="delivery:2026-08-18",
        )
        drifts = [i for i in report.issues if i.code == "CENSUS_DRIFT"]
        assert len(drifts) == 2
        assert all(i.severity == "error" for i in drifts)
        assert any("SM" in i.detail for i in drifts)

    def test_matching_census_passes_with_bucket_map(self):
        report = QualityReport(dataset="t")
        detect_census_drift(
            {"EQ": 100, "SM": 50},
            {"EQ": 100, "SME": 50},
            report,
            bucket_map={"SM": "SME", "ST": "SME"},
        )
        assert report.passed

    def test_missing_bucket_without_map_still_fires(self):
        report = QualityReport(dataset="t")
        detect_census_drift({"EQ": 100, "SM": 50}, {"EQ": 100, "SME": 50}, report)
        drifts = [i for i in report.issues if i.code == "CENSUS_DRIFT"]
        assert len(drifts) == 1
        assert "SM" in drifts[0].detail

    def test_total_ratio_drop_raises(self):
        report = QualityReport(dataset="t")
        detect_census_drift({"EQ": 1000}, {"EQ": 400}, report, min_ratio=0.95)
        codes = {i.code for i in report.issues}
        assert "CENSUS_DROP" in codes

    def test_within_ratio_passes(self):
        report = QualityReport(dataset="t")
        # small legit differences (holidays filtering etc.)
        detect_census_drift({"EQ": 1000}, {"EQ": 980}, report, min_ratio=0.95)
        assert not any(i.code == "CENSUS_DROP" for i in report.issues)

    def test_zero_raw_buckets_ignored(self):
        report = QualityReport(dataset="t")
        detect_census_drift({"EQ": 100, "ST": 0}, {"EQ": 100}, report)
        assert report.passed

    def test_empty_raw_no_op(self):
        report = QualityReport(dataset="t")
        detect_census_drift({}, {"EQ": 5}, report)
        assert report.passed
