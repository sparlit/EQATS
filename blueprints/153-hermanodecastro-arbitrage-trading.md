# Integration Blueprint for arbitrage-trading into eqats

## Overview
The `arbitrage-trading` repository provides a Rust-based prototype for detecting arbitrage opportunities between two cryptocurrency exchanges. Its core value lies in the arbitrage detection logic, which can be adapted as a signal generation component within the eqats framework.

## Proposed Integration

### Data Engines
- No explicit data ingestion or storage features are documented in the README. To use this code in eqats, we would need to wrap its exchange connectivity (presumably using crates like `reqwest` or `tokio-tungstenite`) into eqats' market data engine interface, providing normalized order book feeds.

### Signal & Execution Logic
- **Arbitrage Detection Algorithm**: The main logic that identifies price discrepancies across two exchanges and generates trade signals. This can be extracted as a signal module (`eqats::signal::arbitrage`) that consumes normalized market data and emits `Signal` events.
- **Execution Placeholder**: Although not detailed, the project’s goal implies order execution; we can extend the signal module with an execution adapter that routes signals to eqats’ order manager.

### Risk Engineering
- No risk‑management features are mentioned. Integration would rely on eqats’ existing risk engine (position limits, volatility checks, stop‑loss) to arbitrate any signals before execution.

## Implementation Steps
1. **Isolate the arbitrage detection function** from the Rust binary into a library crate.
2. **Create a Foreign Function Interface (FFI) or Rust‑to‑Python bridge** (if eqats is Python‑centric) to call the detection logic.
3. **Map its input/output** to eqats’ market data structures and signal schema.
4. **Plug the module into eqats’ signal pipeline**, ensuring it runs within the strategy runner.
5. **Apply eqats’ risk checks** before allowing any arbitrage trade to be sent to the execution engine.
6. **Write unit tests** using historical order‑book data to validate signal accuracy.
7. **Monitor latency and performance**, adjusting the data engine subscription frequency as needed.

## Expected Benefits
- Adds a low‑latency, cross‑exchange arbitrage signal to eqats’ strategy library.
- Demonstrates how external Rust‑based analytics can be incorporated via FFI, expanding eqats’ language flexibility.
- Provides a starting point for more sophisticated multi‑exchange arbitrage models.

## Caveats
- The original repository lacks explicit risk controls; reliance on eqats’ risk engine is mandatory.
- Exchange API keys and rate‑limit handling must be supplied externally per eqats’ credential management.
- Further work is needed to ensure the detection logic handles fees, slippage, and latency accurately.