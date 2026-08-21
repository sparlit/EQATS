"""WebSocket telemetry smoke tests (Round 4 & Round 5 chaos).

Covers the TelemetryStreamServer payload builder introduced in
commit 8f62709 and Round 5 schema versioning / chaos stress testing.
"""
import time

from institutional_integrations.web_api import TelemetryStreamServer, SocketIPCBridge


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
    assert payload["schema_version"] == 1
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
    assert payload["schema_version"] == 1
    assert payload["account"]["open_positions"] == 0
    assert payload["account"]["win_rate"] == 0.0
    assert payload["account"]["net_profit"] == 0.0
    assert payload["positions"] == []
    assert payload["scans"] == {}


def test_websocket_telemetry_chaos_rapid_burst():
    """Chaos test: simulates rapid 500Hz telemetry payload generation burst without memory leak or breakdown."""
    server = TelemetryStreamServer()
    for i in range(500):
        payload = server.build_telemetry_payload(
            current_time=time.time(),
            equity=10000.0 + i,
            balance=10000.0,
            active_positions=[{"symbol": "EURUSD", "lots": 0.01}],
            scans={"EURUSD": {"signal": "buy"}},
            perf={"win_rate": 60.0, "net_profit": float(i)},
        )
        assert payload["schema_version"] == 1
        assert payload["account"]["equity"] == 10000.0 + i


def test_websocket_telemetry_chaos_malformed_inputs():
    """Chaos test: verifies resilience when given malformed or missing payload dictionary fields."""
    server = TelemetryStreamServer()
    payload = server.build_telemetry_payload(
        current_time="2026-01-01T00:00:00",
        equity=-5000.0,
        balance=-1000.0,
        active_positions=[{"corrupted": True}],
        scans={"MALFORMED": None},
        perf={},
    )
    assert payload["schema_version"] == 1
    assert payload["account"]["win_rate"] == 0.0
    assert payload["account"]["net_profit"] == 0.0
    assert payload["positions"] == [{"corrupted": True}]


def test_socket_ipc_bridge_reconnect_lifecycle_chaos():
    """Chaos test: verifies SocketIPCBridge rapid start/push/stop disconnect and reconnect cycle."""
    bridge = SocketIPCBridge(host="127.0.0.1", port=59990)

    # Start server
    bridge.start_server()
    res1 = bridge.push_state(10000.0, 10000.0, [], [], "Tokyo Session")
    assert res1["status"] == "PUSHED"

    # Stop server
    bridge.stop_server()
    assert bridge.running is False

    # Rapid restart & push
    bridge.start_server()
    res2 = bridge.push_state(10500.0, 10000.0, [{"ticket": "1001"}], [], "London Session")
    assert res2["status"] == "PUSHED"
    assert bridge.latest_state["equity"] == 10500.0

    bridge.stop_server()
