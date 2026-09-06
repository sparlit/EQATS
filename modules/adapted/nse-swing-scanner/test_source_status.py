"""Tests for the source_status envelope."""
import pytest

from source_status import make_status, worst_status, SOURCE_STATUSES


def test_make_status_basic():
    s = make_status("nse:bhavcopy", "ok", as_of="2026-07-01", data={"X": 1})
    assert s["source"] == "nse:bhavcopy"
    assert s["status"] == "ok"
    assert s["as_of"] == "2026-07-01"
    assert s["data"] == {"X": 1}
    assert "error" not in s


def test_make_status_unknown_status_rejected():
    with pytest.raises(ValueError):
        make_status("x", "potato")


def test_make_status_with_error():
    s = make_status("nse", "source_failed", error="HTTP 503")
    assert s["status"] == "source_failed"
    assert s["error"] == "HTTP 503"
    assert "as_of" not in s


def test_worst_status_ordering():
    assert worst_status("ok", "ok") == "ok"
    assert worst_status("ok", "fallback_used") == "fallback_used"
    assert worst_status("ok", "source_failed") == "source_failed"
    assert worst_status("flag_only", "source_failed") == "source_failed"
    assert worst_status("ok", "missing") == "missing"
    assert worst_status() == "ok"
