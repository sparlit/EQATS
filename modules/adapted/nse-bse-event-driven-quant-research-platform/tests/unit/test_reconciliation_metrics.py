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


"""Reconciliation logic + metrics exporter tests."""

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from indian_quant.adapters.upstox.reconciliation import (  # noqa: E402
    Reconciler,
    should_halt,
)


class TestCompareLogic:
    def test_positions_match(self):
        rows = [{"instrument_key": "NSE_EQ|X", "quantity": 100}]
        assert Reconciler.compare_positions({"NSE_EQ|X": 100.0}, rows) == []

    def test_position_mismatch_detected(self):
        rows = [{"instrument_key": "NSE_EQ|X", "quantity": 75}]
        out = Reconciler.compare_positions({"NSE_EQ|X": 100.0}, rows)
        assert out and out[0]["kind"] == "POSITION"
        assert out[0]["local_qty"] == 100.0 and out[0]["broker_qty"] == 75.0

    def test_local_only_position_detected(self):
        out = Reconciler.compare_positions({"NSE_EQ|Y": 10.0}, [])
        assert out and out[0]["instrument"] == "NSE_EQ|Y"

    def test_orders_symmetric_mismatch(self):
        broker = [{"order_id": "A", "status": "open"}]
        out = Reconciler.compare_orders({"B"}, broker)
        kinds = {m["kind"] for m in out}
        assert "ORDER_LOCAL_ONLY" in kinds and "ORDER_BROKER_ONLY" in kinds

    def test_funds_within_tolerance(self):
        assert Reconciler.compare_funds(500000.5, {"available_margin": 500000.9}) == []
        out = Reconciler.compare_funds(400000.0, {"available_margin": 500000.0})
        assert out and out[0]["kind"] == "FUNDS"

    def test_should_halt(self):
        from indian_quant.adapters.upstox.reconciliation import ReconciliationReport

        ok = ReconciliationReport("t", 1, 1, True)
        bad = ReconciliationReport("t", 1, 1, True, mismatches=[{"kind": "POSITION"}])
        assert not should_halt(ok) and should_halt(bad)


class TestReconcilerRun:
    def _client(self):
        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/order/retrieve-all"):
                return httpx.Response(
                    200, json={"data": [{"order_id": "O1", "status": "complete"}]}
                )
            if "positions" in path:
                return httpx.Response(
                    200, json={"data": [{"instrument_key": "NSE_EQ|X", "quantity": 100}]}
                )
            if path.endswith("/funds-and-margin"):
                return httpx.Response(200, json={"data": {"equity": {"available_margin": 500000}}})
            return httpx.Response(200, json={})

        return Reconciler(
            "TOK",
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )

    def test_clean_run_passes(self):
        report = self._client().run(
            local_positions={"NSE_EQ|X": 100.0},
            local_open_orders=set(),
            local_available_funds=500000.0,
            checked_at_iso="2026-08-23T00:00:00+00:00",
        )
        assert report.ok and report.orders_compared == 1

    def test_divergence_halts(self):
        report = self._client().run(
            local_positions={"NSE_EQ|X": 999.0},
            local_open_orders=set(),
            local_available_funds=500000.0,
            checked_at_iso="2026-08-23T00:00:00+00:00",
        )
        assert not report.ok
        assert should_halt(report)

    def test_missing_token_raises(self):
        with pytest.raises(RuntimeError):
            Reconciler(None).fetch_order_book()


class TestMetrics:
    def test_metrics_from_real_metadata(self, tmp_path):
        import metrics
        from indian_quant.storage import MetadataStore

        md = MetadataStore(f"sqlite:///{tmp_path}/meta.db")
        md.start_job("j1", tool="t", source="NSE", params={})
        md.finish_job("j1", status="OK")
        md.record_quality_report(dataset="d", report={"n_errors": 2})
        md.close()

        class S:
            storage = type("St", (), {"metadata_dsn": f"sqlite:///{tmp_path}/meta.db"})()

        out = metrics.render(metrics.collect_metrics(S()))
        assert "indian_quant_jobs_total 1" in out
        assert "indian_quant_quality_reports_total 1" in out
        assert "indian_quant_metadata_present 1" in out
