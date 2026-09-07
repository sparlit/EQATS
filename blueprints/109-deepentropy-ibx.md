# Integration Blueprint: IBX (deepentropy/ibx) into eqats

## Overview
IBX provides a direct, ultra‑low‑latency connection to Interactive Brokers written in Rust with Python bindings via PyO3. It exposes the classic ibapi `EClient`/`EWrapper` interface, making it a drop‑in replacement for the Java Gateway or ib_async.

## Why IBX for eqats
- **Latency**: Tick‑to‑strategy processing ~340 ns (≈5,900× faster than the Java Gateway).
- **In‑process**: No extra hop, no JVM, no GC pauses.
- **Language flexibility**: Core engine in Rust; strategies can stay in Python (or be ported to Rust).
- **Feature completeness**: Market data, historical data, order management, account queries.

## Proposed Integration

### 1. Data Engine Layer (Rust core)
- Replace eqats’ current market‑data ingestion module with IBX.
- Initialize an `EClient` with `EClientConfig` (username, password, host, paper=true/false).
- Run the IBX message loop on a dedicated thread:
  ```rust
  let mut client = EClient::connect(&cfg)?;
  std::thread::spawn(move || {
      let mut wrapper = EqatsWrapper::new();
      loop { client.process_msgs(&mut wrapper); }
  });
  ```
- Implement `Wrapper` for eqats:
  - `tick_price`, `tick_size`, `tick_string` → publish to an internal lock‑free market‑data bus (e.g., crossbeam channel or async broadcast).
  - `next_valid_id` → store next order ID.
  - `managed_accounts`, `updateAccountValue` → feed account‑state monitor.
- Use the lock‑free `quote(req_id)` method for zero‑copy reads of best bid/ask when strategies need the latest quote.

### 2. Signal & Execution Logic (Python strategy layer)
- Keep existing strategy code (Python) unchanged; swap the import from `ib_insync`/`ib_async` to `ibx`.
- Example bootstrap:
  ```python
  import threading
  from ibx import EWrapper, EClient, Contract, Order

  class Strategy(EWrapper):
      def __init__(self):
          super().__init__()
          self.next_id = None
          self.connected = threading.Event()

      def next_valid_id(self, order_id):
          self.next_id = order_id
          self.connected.set()

      # … tick_price, order_status, etc. …

  app = Strategy()
  client = EClient(app)
  client.connect(username='…', password='…', paper=True)
  threading.Thread(target=client.run, daemon=True).start()
  app.connected.wait(timeout=10)
  ```
- Market data subscription: `client.req_mkt_data(req_id, contract, '', False, False)`.
- Order placement: use `client.next_order_id()` (or the callback‑provided ID) and `client.place_order(id, contract, order)`.
- Cancel/modify via `client.cancel_order` and `client.place_order` with updated `Order`.
- All callbacks run on the IBX‑driven thread; strategies can post signals to a thread‑safe queue that the execution thread consumes.

### 3. Risk Engineering Layer
- IBX does not provide risk limits; implement risk checks in eqats’ risk manager:
  - Pre‑trade: verify position limits, max notional, volatility‑adjusted size using account data from `accountUpdate`/`updatePortfolio`.
  - Post‑trade: monitor PnL, drawdown, and issue `client.cancel_order` if limits breached.
  - Use the same `Wrapper` callbacks to update internal risk state.
- Optionally expose risk‑check functions as Rust callables via PyO3 for low‑latency pre‑trade checks if needed.

### 4. Deployment & Build
- Add IBX as a git dependency in eqats’ `Cargo.toml` (Rust side) and build the Python wheel with `maturin develop --features python`.
- Ensure the same version is used across Rust and Python to maintain ABI compatibility.
- Run unit tests against IBX’s mock server or paper‑trading environment before live deployment.

## Benefits
- **Performance**: Sub‑microsecond tick handling and order submission, enabling strategies that were previously latency‑bound.
- **Simplicity**: Single dependency, no external Java processes, reducing operational overhead.
- **Future‑proof**: Direct access to IB’s API; upgrades follow IB’s releases without waiting for Java Gateway updates.

## Risks & Mitigations
- **Feature gaps**: Verify that all required IBX methods (e.g., historical data, fundamental data) are present; if missing, fall back to ib_async for those specific calls.
- **Threading model**: IBX uses a blocking `process_msgs` loop; ensure eqats’ async runtime does not block the event loop—run IBX on a dedicated OS thread.
- **Error handling**: Propagate IBX error callbacks to eqats’ logging and alerting framework.

## Conclusion
Integrating IBX gives eqats a high‑performance, low‑latency gateway to Interactive Brokers while preserving the familiar ibapi‑style programming model. The data‑engine and execution‑logic components map cleanly onto IBX’s market‑data and order‑management APIs; risk controls remain the responsibility of eqats’ risk‑engineering layer, which can consume the same streamed account and position data.
