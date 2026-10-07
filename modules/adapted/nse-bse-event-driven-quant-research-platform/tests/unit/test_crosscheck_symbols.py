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


"""Crosscheck comparison logic and symbol-event registry tests."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from crosscheck import compare_series  # noqa: E402


def series(values: list[float], start="2026-08-10"):
    idx = pd.date_range(start, periods=len(values), freq="D", tz="UTC")
    return pd.Series(values, index=idx)


class TestCompareSeries:
    def test_identical_series_passes(self):
        a, b = series([100.0, 101.0]), series([100.0, 101.0])
        report = compare_series(a, b, pair="t", symbol="X", warn_pct=0.1, error_pct=0.5)
        assert report.passed and report.n_compared == 2 and report.max_drift_pct == 0

    def test_small_drift_warns(self):
        a = series([100.0])
        b = series([100.2])
        report = compare_series(a, b, pair="t", symbol="X", warn_pct=0.1, error_pct=0.5)
        assert report.n_warning == 1 and report.passed

    def test_large_drift_errors(self):
        a = series([100.0])
        b = series([102.0])
        report = compare_series(a, b, pair="t", symbol="X", warn_pct=0.1, error_pct=0.5)
        assert not report.passed
        assert report.details[0]["severity"] == "error"

    def test_partial_overlap_only_common_dates(self):
        idx_a = pd.date_range("2026-08-10", periods=3, freq="D", tz="UTC")
        idx_b = pd.date_range("2026-08-11", periods=3, freq="D", tz="UTC")
        a = pd.Series([1.0, 1.0, 1.0], index=idx_a)
        b = pd.Series([1.0, 1.0, 999.0], index=idx_b)
        report = compare_series(a, b, pair="t", symbol="X", warn_pct=0.1, error_pct=0.5)
        assert report.n_compared == 2

    def test_report_dict_shape(self):
        report = compare_series(
            series([100.0]), series([100.0]), pair="p", symbol="S", warn_pct=0.1, error_pct=0.5
        )
        payload = report.to_dict()
        assert {"pair", "symbol", "n_compared", "passed"} <= set(payload)


class TestSymbolEvents:
    def test_roundtrip_and_resolution(self, tmp_path):
        from indian_quant.storage import MetadataStore

        md = MetadataStore(f"sqlite:///{tmp_path}/meta.db")
        md.record_symbol_event(
            isin="INE002A01018",
            exchange="NSE",
            event_type="RENAME",
            effective_date="2026-01-01",
            from_symbol="OLDNAME",
            to_symbol="NEWNAME",
            note="corporate rebrand",
            source="MANUAL",
        )
        events = md.symbol_events_for_isin("ine002a01018")
        assert len(events) == 1
        assert events[0]["to_symbol"] == "NEWNAME"
        assert md.current_symbol_for_isin("INE002A01018", "NSE", "2025-06-01") is None
        assert md.current_symbol_for_isin("INE002A01018", "NSE", "2026-06-01") == "NEWNAME"
        md.close()

    def test_delisting_terminates(self, tmp_path):
        from indian_quant.storage import MetadataStore

        md = MetadataStore(f"sqlite:///{tmp_path}/meta.db")
        md.record_symbol_event(
            isin="INE000DELISTED1".ljust(12, "0")[:12],
            exchange="BSE",
            event_type="DELISTING",
            effective_date="2026-03-01",
            to_symbol="GONE",
        )
        assert md.current_symbol_for_isin("INE000DELIS", "BSE", "2024-01-01") is None
        assert md.current_symbol_for_isin("INE000DELIS", "BSE", "2026-06-01") is None
        md.close()

    def test_invalid_event_type_rejected(self, tmp_path):
        from indian_quant.storage import MetadataStore

        md = MetadataStore(f"sqlite:///{tmp_path}/meta.db")
        with pytest.raises(ValueError):
            md.record_symbol_event(
                isin="INE002A01018",
                exchange="NSE",
                event_type="WHATEVER",
                effective_date="2026-01-01",
            )
        md.close()
