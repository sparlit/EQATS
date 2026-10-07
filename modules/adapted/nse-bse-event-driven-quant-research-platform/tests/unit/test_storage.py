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


"""Storage layer tests: raw store, parquet store, metadata, duckdb."""

from datetime import UTC, datetime

import pandas as pd
import pytest
from indian_quant.schemas import MarketBar, Timeframe
from indian_quant.storage import MetadataStore, ParquetStore, RawStore


def bar(day: str, close: float):
    return MarketBar(
        instrument_id="NSE_EQ|TEST",
        exchange="NSE",
        timestamp=datetime.fromisoformat(day).replace(tzinfo=UTC),
        timeframe=Timeframe.DAY,
        open=close * 0.99,
        high=close * 1.01,
        low=close * 0.98,
        close=close,
        volume=1000.0,
        source="NSE",
    )


class TestRawStore:
    def test_content_addressed_and_idempotent(self, tmp_path):
        store = RawStore(tmp_path)
        p1, h1 = store.save(source="NSE", tool="t", payload=b"hello", request_meta={"a": 1})
        p2, h2 = store.save(source="NSE", tool="t", payload=b"hello")
        assert p1 == p2 and h1 == h2
        payloads = [
            p for p in (tmp_path / "nse" / "t").rglob("*.json") if not p.name.endswith(".meta.json")
        ]
        assert len(payloads) == 1

    def test_meta_written(self, tmp_path):
        import json

        store = RawStore(tmp_path)
        path, _ = store.save(source="NSE", tool="t", payload=b"x")
        meta = json.loads(path.with_suffix(".meta.json").read_text())
        assert meta["sha256"] and meta["source"] == "NSE"


class TestParquetStore:
    def test_bars_roundtrip(self, tmp_path):
        store = ParquetStore(tmp_path)
        bars = [bar(f"2025-06-0{d}T00:00:00+00:00", 100 + d) for d in range(1, 6)]
        paths = store.write_bars(bars, layer="normalized")
        assert len(paths) == 1
        df = store.read_bars(layer="normalized", exchange="NSE", symbol="TEST")
        assert len(df) == 5
        assert float(df.iloc[0]["close"]) == pytest.approx(101.0)

    def test_empty_write_is_noop(self, tmp_path):
        store = ParquetStore(tmp_path)
        assert store.write_bars([], layer="normalized") == []


class TestMetadata:
    def test_instrument_roundtrip(self, tmp_path):
        md = MetadataStore(f"sqlite:///{tmp_path}/meta.db")
        md.register_instrument(
            {
                "instrument_id": "NSE_EQ|RELIANCE",
                "exchange": "NSE",
                "segment": "EQ",
                "symbol": "RELIANCE",
                "isin": "INE002A01018",
                "security_type": "EQUITY",
                "lot_size": 1,
                "tick_size": 0.05,
                "nautilus_instrument_id": "RELIANCE.NSE",
            }
        )
        row = md.get_instrument("NSE_EQ|RELIANCE")
        assert row["symbol"] == "RELIANCE"
        assert md.get_instrument("NSE_EQ|NOPE") is None
        md.close()

    def test_job_lifecycle(self, tmp_path):
        md = MetadataStore(f"sqlite:///{tmp_path}/meta.db")
        md.start_job("j1", tool="nse_equity_historical", source="NSE", params={"symbol": "X"})
        md.finish_job("j1", status="OK", raw_hash="abc", rows=10)
        md.close()

    def test_quality_report_recorded(self, tmp_path):
        md = MetadataStore(f"sqlite:///{tmp_path}/meta.db")
        rid = md.record_quality_report(dataset="d", report={"n_rows": 5, "n_errors": 0})
        assert rid >= 1
        md.close()

    def test_run_recorded(self, tmp_path):
        md = MetadataStore(f"sqlite:///{tmp_path}/meta.db")
        md.record_run("r1", kind="backtest", config_hash="h", metrics={"pnl": 1.5})
        md.close()


class TestDuckDBResearch:
    def test_view_over_validated_bars(self, tmp_path):
        from indian_quant.storage import ResearchDB

        data_root = tmp_path / "data"
        store = ParquetStore(data_root)
        bars = [bar(f"2025-06-{d:02d}T00:00:00+00:00", 100 + d) for d in range(1, 6)]
        store.write_bars(bars, layer="validated")

        db = ResearchDB(tmp_path / "research.duckdb", data_root)
        summary = db.bar_summary()
        assert len(summary) == 1
        assert int(summary.iloc[0]["n_bars"]) == 5
        db.close()


def test_pandas_compat():
    df = pd.DataFrame({"a": [1]})
    assert list(df.columns) == ["a"]
