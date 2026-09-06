# Integration Blueprint for Velocity Features into eqats

## Overview
Velocity is a low‑latency, multi‑market cryptocurrency exchange written in Rust. Its core strengths are sub‑millisecond order placement, an in‑memory orderbook matched by a dedicated thread per market, MPSC‑based asynchronous persistence to Scylla DB, and real‑time market data distribution via WebSocket/pubsub. This blueprint maps those strengths onto the eqats project, showing how to adopt Velocity’s architecture while preserving eqats’ existing abstractions.

## Data Engines Integration
- **Storage Layer:** Replace or augment eqats’ current persistence with Scylla DB for orderbook snapshots, trade logs, and user balances. Scylla’s low‑latency reads/writes match Velocity’s ~10 ms orderbook mutation and ~25‑40 ms database update targets.
- **In‑Memory Orderbooks:** Maintain a hashmap‑based orderbook per market inside the matching engine (similar to Velocity’s `HashMap<price, LimitStruct>`). This gives O(1) access to price levels and enables sub‑millisecond traversal.
- **MPSC Persistence Pipeline:**
  1. Order validation thread locks user balances.
  2. Sends the order via an MPSC channel to a dedicated DB writer thread.
  3. The writer persists the order and balance updates to Scylla without blocking the matching loop.
  4. A second MPSC channel carries trade events from the matcher to an event‑emitter thread that handles Redis/WebSocket broadcasting.
- **Recovery & Replay:** On engine start, read the last 24 h of orders from Scylla, replay them to rebuild in‑memory orderbooks, and reload user balances. This mirrors Velocity’s recovery mechanism and ensures durability after crashes.
- **Parallel Mutations:** Leverage Scylla’s lightweight transactions to persist orderbook updates concurrently with matching, achieving Velocity’s ~10 ms parallel persistence goal.

## Signal & Execution Logic Integration
- **Ultra‑Fast Order Placement:** Queue incoming orders to the matching engine through an MPSC sender; target <1 ms placement latency.
- **Order Book Structure:** Use `HashMap<PriceLevel, Vec<Order>>` where each `Vec` preserves FIFO order for price‑time priority.
- **Matching Loop:**
  - Iterate from best to worst limit.
  - Fill quantities against resting orders, adjusting balances atomically.
  - Emit a trade event (price, quantity, aggressor/maker IDs) on a dedicated MPSC channel.
  - If any quantity remains, insert the remainder back into the book.
- **Order Types:** Implement Limit, Market, Cancel, CancelAll, OpenOrder/OpenOrders exactly as described; market orders are immediately filled and not stored, while cancelled orders are removed from the book.
- **Response & Notification:**
  - Send order acknowledgments/rejections to clients via Redis lists (or eqats’ existing notification bus).
  - Publish trades, tickers, and depth updates over WebSocket/pubsub to public subscribers.
  - Stream private order updates directly from the matching engine to the order maker before persistence (zero‑copy, low‑latency).
- **Balance Updates:** On each trade, adjust maker and taker balances inside the matching engine’s memory; the DB writer later persists these changes to Scylla.

## Risk Engineering Integration
- Velocity’s README does not describe risk limits, position sizing, or real‑time risk monitoring. Therefore, no direct risk‑engineering features can be imported.
- **Suggested Approach:** Add a risk‑validation middleware *before* the order enters the MPSC validation stage. This middleware can enforce:
  - Max order size / notional limits.
  - Position‑size and leverage checks.
  - Margin‑requirement verification.
  - Optional kill‑switch or circuit‑breaker hooks.
- Risk metrics (e.g., current exposure, P&L) can be published on a separate MPSC channel to a monitoring service, enabling eqats to build its own risk dashboard without altering the core matching logic.

## Implementation Steps
1. **Add Dependencies** – Include `scylla`, `redis`, `tokio-tungstenite` (or `warp`), and any needed serialization crates.
2. **Configure Scylla** – Create keyspace/tables for `orderbooks`, `trades`, `balances`, and `order_history`.
3. **In‑Memory Orderbook** – Define per‑market struct with MPSC sender/receiver pairs for incoming orders and trade events.
4. **Refactor Order Flow**
   - `validate_order()` → lock balances → send on `order_tx`.
   - `matching_loop()` receives orders, executes against book, emits trades on `trade_tx`.
   - `db_writer()` consumes from `order_tx` and persists to Scylla.
   - `event_emitter()` consumes from `trade_tx` → updates Redis lists, pushes WebSocket messages.
5. **WebSocket Server** – Implement endpoints for market data (ticker, depth, trades) and private channels (order status, balances).
6. **API Endpoints** – Mirror Velocity’s API collection (limit/market, cancel, cancelAll, openOrders) using eqats’ existing router or a new Actix‑Web/Warpservice.
7. **Recovery Routine** – On start, query Scylla for orders in the last 24 h, replay them to rebuild orderbooks and balances.
8. **Benchmark & Test** – Use criterion or similar to verify:
   - Order placement <1 ms.
   - Matching + event publish ~4 ms.
   - DB write latency ~10‑40 ms.
   - WebSocket broadcast <5 ms.
9. **Risk Layer (Optional)** – Implement pre‑validation risk checks as a pluggable middleware; expose metrics via Prometheus or a simple HTTP endpoint.

## Expected Benefits
- Sub‑millisecond order placement and processing, matching Velocity’s benchmarks.
- Non‑blocking durable writes via MPSC + Scylla, preventing stalls in the matching engine.
- Fast crash recovery using Scylla replay, ensuring zero‑loss of recent orders.
- Real‑time market data distribution through WebSocket/pubsub, enabling low‑latency strategies.
- A clean, modular separation of concerns (matching, persistence, broadcasting) that can be extended with eqats‑specific risk and analytics layers.

By integrating these Velocity‑derived components, eqats can achieve a high‑performance trading backbone while retaining flexibility for strategy development, risk management, and frontend extensions.
