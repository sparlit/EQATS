"""WebSocket telemetry smoke tests (Round 4).

Covers the TelemetryStreamServer payload builder introduced in
commit 8f62709. The full FastAPI/WebSocket server stack requires external
runtime dependencies (uvicorn + websockets); this test pins the data-shape
contract that the WS endpoint broadcasts.
"""
import os
import sys
import time

# Allow direct import when running pytest from project root
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

from institutional_integrations.web_api import TelemetryStreamServer


def test_telemetry_server_default_host_port():
    server = TelemetryStreamServer()
    assert server.host == "127.0.0.1"
    assert server.port == 8000


def test_build_telemetry_payload_shape():
    server = TelemetryStreamServer(host="127.0.0.1", port=8765)
    payload = server.build_telemetry_payload(
        current_time=time.time(),
        equity=10500.50,
        balance=10000.00,
        active_positions=[{"symbol": "EURUSD", "lots": 0.01, "pnl": 12.5}],
        scans={"EURUSD": {"signal": "buy", "confidence": 0.82}},
        perf={"win_rate": 0.58, "net_profit": 500.0},
    )
    assert payload["account"]["equity"] == 10500.5
    assert payload["account"]["balance"] == 10000.0
    assert payload["account"]["open_positions"] == 1
    assert payload["account"]["win_rate"] == 0.58
    assert payload["account"]["net_profit"] == 500.0
    assert payload["positions"] == [{"symbol": "EURUSD", "lots": 0.01, "pnl": 12.5}]
    assert payload["scans"]["EURUSD"]["signal"] == "buy"


def test_build_telemetry_payload_empty_inputs():
    server = TelemetryStreamServer()
    payload = server.build_telemetry_payload(
        current_time=0,
        equity=0,
        balance=0,
        active_positions=[],
        scans={},
        perf={},
    )
    assert payload["account"]["open_positions"] == 0
    assert payload["account"]["win_rate"] == 0.0
    assert payload["account"]["net_profit"] == 0.0
    assert payload["positions"] == []
    assert payload["scans"] == {}
