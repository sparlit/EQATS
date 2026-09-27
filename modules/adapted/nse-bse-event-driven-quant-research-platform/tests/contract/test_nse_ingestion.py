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


"""NSE ingestion service tests: MCP payload -> raw store -> canonical contracts."""

import httpx
import pytest
from indian_quant.ingestion import NseBseMcpClient, NseIngestionService
from indian_quant.schemas import CorporateActionType
from indian_quant.storage import MetadataStore, RawStore


def historical_payload():
    return {
        "data": [
            {
                "symbol": "RELIANCE",
                "timestamp": "02-Jun-2025",
                "open": 2400.0,
                "high": 2450.0,
                "low": 2390.0,
                "close": 2440.0,
                "volume": 1_000_000,
            },
            {
                "symbol": "RELIANCE",
                "timestamp": "03-Jun-2025",
                "OPEN": 2440.0,
                "HIGH": 2500.0,
                "LOW": 2430.0,
                "CLOSE": 2490.0,
                "TOTTRDQTY": 900_000,
            },
            {"symbol": "RELIANCE", "timestamp": "", "junk": True},
        ]
    }


def actions_payload():
    return {
        "data": [
            {
                "symbol": "RELIANCE",
                "rate": 10.0,
                "exDate": "04-Jul-2025",
                "purpose": "DIVIDEND - RS 10 PER SHARE",
            },
            {
                "symbol": "RELIANCE",
                "bv": "1:1",
                "exDate": "10-Oct-2024",
                "subject": "BONUS 1:1",
            },
            {"symbol": "RELIANCE", "subject": "unclassifiable"},
        ]
    }


def announcements_payload():
    return {
        "data": [
            {
                "symbol": "RELIANCE",
                "sortDate": "01-Jul-2025 18:30:00",
                "desc": "Board meeting intimation",
                "attchmntFile": "https://nsearchives.nseindia.com/x.pdf",
            }
        ]
    }


def make_service(tmp_path, payloads: dict[str, object]):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        method = body.get("method")
        if method == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
        if method == "tools/call":
            name = body["params"]["name"]
            result = {
                "content": [{"type": "text", "text": json.dumps(payloads[name])}],
                "isError": False,
            }
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body.get("id"), "result": {}})

    client = NseBseMcpClient(
        "http://localhost:3000/mcp", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    return NseIngestionService(
        client,
        RawStore(tmp_path / "raw"),
        MetadataStore(f"sqlite:///{tmp_path / 'meta.db'}"),
    )


import json  # noqa: E402


class TestNseIngestion:
    def test_historical_to_bars_with_lineage(self, tmp_path):
        service = make_service(tmp_path, {"nse_equity_historical": historical_payload()})
        bars = service.equity_historical("reliance", "2025-06-01", "2025-06-05")
        assert len(bars) == 2
        first = bars[0]
        assert first.instrument_id == "NSE_EQ|RELIANCE"
        assert first.close == pytest.approx(2440.0)
        assert first.raw_hash is not None
        assert first.ingestion_timestamp is not None

    def test_raw_store_receives_exact_payload(self, tmp_path):
        service = make_service(tmp_path, {"nse_equity_historical": historical_payload()})
        service.equity_historical("RELIANCE", "2025-06-01", "2025-06-05")
        raw_files = [
            f
            for f in (tmp_path / "raw" / "nse" / "nse_equity_historical").rglob("*.json")
            if not f.name.endswith(".meta.json")
        ]
        assert len(raw_files) == 1
        stored = json.loads(raw_files[0].read_text())
        assert stored == historical_payload()

    def test_corporate_actions_classified(self, tmp_path):
        service = make_service(tmp_path, {"nse_corporate_actions": actions_payload()})
        actions = service.corporate_actions("RELIANCE")
        types = [a.action_type for a in actions]
        assert CorporateActionType.DIVIDEND in types
        assert CorporateActionType.BONUS in types
        assert len(actions) == 2

    def test_announcements_mapped(self, tmp_path):
        service = make_service(tmp_path, {"nse_corporate_announcements": announcements_payload()})
        anns = service.corporate_announcements("RELIANCE")
        assert len(anns) == 1
        assert anns[0].headline == "Board meeting intimation"
        assert anns[0].document_url.endswith(".pdf")

    def test_job_recorded_in_metadata(self, tmp_path):
        meta = MetadataStore(f"sqlite:///{tmp_path / 'meta.db'}")
        service = make_service(tmp_path, {"nse_equity_historical": historical_payload()})
        service.metadata = meta
        service.equity_historical("RELIANCE", "2025-06-01", "2025-06-05")
        rows = meta._con.execute("SELECT status FROM jobs").fetchall()
        assert any(r["status"] == "OK" for r in rows)
        meta.close()
