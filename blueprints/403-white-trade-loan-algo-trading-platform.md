# Integration Blueprint: algo-trading-platform with eqats

## Overview
The algo-trading-platform provides a unified broker API and real-time market data over WebSocket. eqats is a Rust-core quantitative trading system with Python/PyO3 bindings for strategy execution. The integration uses the platform's REST API to send/receive orders, positions, and market data, while keeping strategy logic in eqats.

## Components
1. **eqats Core (Rust)** – handles data engines, signal generation, risk checks, and order execution.
2. **Python Bindings (PyO3)** – allow eqats to be called from Python strategies hosted in the platform's /python surface.
3. **Algo-Trading Platform (TypeScript)** – supplies unified broker adapters, WebSocket feed, and UI.

## Data Flow
- Market data arrives via the platform's WebSocket proxy (port 8765) -> eqats Rust core receives normalized ticks through a thin WebSocket client (or via shared Redis cache).
- Strategies (Python or Rust) running in eqats compute signals.
- Signals are validated by the risk engine (position sizing, margin checks).
- Approved orders are sent to the platform's REST endpoint /api/v1/orders.
- Order fills, positions, and account updates flow back via REST /api/v1/positions or WebSocket updates.

## Implementation Steps
1. Add a Rust HTTP client module (src/integration/algo_trading_platform.rs) that wraps reqwest for the platform's base URL and API key.
2. Expose the client to Python through PyO3 (#[pyfunction]).
3. In the eqats signal/execution layer, replace direct broker calls with calls to this client.
4. Configure the platform to route its WebSocket stream to a Redis channel that eqats subscribes to for low-latency tick data.
5. Write unit tests using mockito to verify request building and error handling.
6. Deploy both services in the same Docker-compose network or on the same host; the platform's sandbox mode can be used for end-to-end validation.

## Safety & Risk
- All orders pass through eqats' risk engine before hitting the platform's API.
- The platform's sandbox mode (₹1 Crore capital) is used for integration testing.
- Failover: if the platform's API returns 501 for a broker, eqats treats it as a risk-reject and logs.

## Future Work
- Generate Rust bindings from the platform's OpenAPI spec (if available) using openapi-generator.
- Replace polling with a native WebSocket client that decodes the platform's ZeroMQ-based message bus.
- Add PyO3-enabled strategy runner that can execute eqats-compiled strategies directly from the platform's /flow editor.
