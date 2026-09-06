# Integration Blueprint for nse-bse-mcp into eqats

## Overview
The nse-bse-mcp application serves real-time and historical Indian stock data via the Model Context Protocol (MCP). To integrate its data engine into the eqats trading platform, we will create a Rust MCP client that connects to the nse-bse-mcp service (running locally or remotely) and exposes the data as async streams for use in signal generation and risk management.

## Components
1. **MCP Client Layer** (src/mcp/client.rs) – Handles connection, authentication (if any), and message framing according to the MCP specification.
2. **Data Engine Wrapper** (src/integrations/nse_bse_mcp.rs) – Translates MCP messages into eqats-native data structures (quotes, fundamentals, financials, dividends).
3. **Signal & Execution Logic** – Uses the wrapped data streams to compute indicators and generate trade signals.
4. **Risk Engineering** – Consumes alert streams from the MCP client to trigger risk checks and notifications.

## Data Flow
- nse-bse-mcp (MCP server) ↔ MCP Client (Rust) ↔ eqats Data Engine → Signal Engine → Execution Engine
- Alerts from MCP Client → Risk Engine → Notification Service

## Implementation Steps
1. Determine MCP transport (likely TCP/WebSocket) and message format (protobuf/JSON) by inspecting the nse-bse-mcp source.
2. Generate Rust bindings from the MCP IDL or manually define structs.
3. Implement an async client using tokio and tungstenite (if WebSocket) or tokio::net::TcpStream.
4. Map incoming messages to eqats MarketQuote, Fundamentals, Financials, Dividend structs.
5. Provide a subscribe_quotes(symbol) method returning a Stream<Item = MarketQuote>.
6. Write unit tests using a mock MCP server.
7. Integrate the client into eqats’ data engine initialization sequence.
8. Configure risk rules to consume price‑change alerts from the client.

## Dependencies
- tokio (async runtime)
- tungstenite (WebSocket) or tokio-util (codec)
- serde/serde_json for message parsing
- Optional: pyo3 if a Python fallback is needed.

## Testing
- Unit tests with a mock MCP server.
- Integration test against a running nse-bse-mcp instance.
- Fuzz testing of message parsing.

## Risks & Mitigations
- Undocumented MCP spec → mitigate by reverse‑engineering from open‑source code or contacting the maintainer.
- Windows‑only binary → mitigate by running the server in a Windows VM or using Wine; alternatively, request a cross‑platform library version.
- Latency → mitigate by co‑locating the MCP server with the eqats instance or using a local cache.

## Conclusion
By treating nse-bse-mcp as an MCP data server, eqats can leverage its rich Indian market data feed without needing direct API keys, while keeping the core trading logic language‑agnostic and Rust‑centric.