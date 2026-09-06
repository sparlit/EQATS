# Integration Blueprint: FerrumFIX into eqats

## Overview
FerrumFIX is a Rust-based FIX engine offering parsing, validation, error recovery, and (de)serialization for FIX 4.2, 4.4, and 5.0 SP2. It provides layered architecture (transport, session, presentation, application) and supports tag-value and JSON encodings, plus code generation for FIX dictionaries.

## Data Engines Integration
- **Market Data Ingestion**: Use FerrumFIX’s tag-value and JSON parsers to consume market data feeds that publish over FIX (e.g., reference data, incremental refresh).
- **Storage**: Persist parsed FIX messages via eqats’ existing storage layer; the structured tag-value maps can be directly mapped to eqats’ canonical event format.
- **Replay & Error Recovery**: Leverage built-in error recovery and resend request handling to guarantee gapless market data capture.
- **Code Generation**: Generate Rust structs for specific FIX dictionaries (e.g., equity options) to enable zero‑copy deserialization into eqats’ data models.

## Signal & Execution Logic Integration
- **Order Entry**: Utilize the session layer (`fefix::session`) to establish and maintain FIX sessions with brokers/exchanges; send NewOrderSingle, OrderCancelReplace, etc., using the dictionary‑driven message builder.
- **Execution Reports**: Parse ExecutionReport messages to update eqats’ order state machine and feed signals to strategy modules.
- **Strategy Agnostic**: Because FerrumFIX isolates transport/session concerns, strategy code can remain focused on signal generation while delegating FIX communication to the engine.
- **Async Support**: The library’s futures‑compatible API can be integrated into eqats’ async runtime (tokio) for non‑blocking order flow.

## Risk Engineering Integration
- **No Native Risk Features**: FerrumFIX does not provide risk limits, position sizing, or monitoring. Risk controls must be implemented in eqats’ risk layer, consuming the order and execution messages parsed by FerrumFIX.
- **Potential Hooks**: Use the parsed ExecutionReport and OrderStatus messages to feed real‑time risk metrics (e.g., gross exposure, P&L) into eqats’ risk engine.

## Implementation Steps
1. Add `fefix` as a dependency in eqats’ Cargo.toml.
2. Configure transport layer (TCP/TLS) using `fefixs` or custom async socket.
3. Initialize a FIX session with appropriate sender/comp IDs, heart‑beat, and sequence numbers.
4. Load or generate the required FIX dictionary (e.g., FIX 4.4) via `fefix::Dictionary`.
5. Build market data adapters that invoke the tag‑value parser on incoming bytes and publish normalized events to eqats’ data bus.
6. Build order execution adapters that use the session’s `send` method to transmit order messages and register callbacks for ExecutionReport.
7. Wire the adapters into eqats’ existing ingestion and execution pipelines.
8. Conduct conformance testing against a FIX simulator or broker sandbox to validate sequencing, gap filling, and message correctness.
9. Monitor session health (logon/logout, resend requests) and expose metrics to eqats’ observability stack.

## Conclusion
FerrumFIX supplies a robust, standards‑compliant FIX foundation that can replace ad‑hoc FIX handling in eqats, providing reliable market data ingestion and order execution while keeping the core trading logic and risk management layers independent.