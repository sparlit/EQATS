# Integration Blueprint: Market Platform Features into eqats

## Overview
The `market‑platform` repository provides a clean separation between market‑data ingestion, strategy execution, and delivery of signals to a frontend. Its strongest assets for eqats are:
- A **provider‑isolated ingestion layer** that can swap Zerodha Kite Connect for any licensed NSE/BSE feed.
- **Redis‑based hot state** (latest quotes, tick streams) guaranteeing low‑latency access without persisting raw ticks.
- A **validated JSON DSL** for strategies, preventing arbitrary code execution.
- **Signal debounce/idempotency** via Redis `SET NX` cooldowns.
- **Supabase Realtime** for pushing signals to clients with Row‑Level Security.

These pieces can be mapped onto eqats’ three domains as follows.

---

## Data Engines Integration

### 1. Ingestion Adapter Layer
- **What to reuse:** The `internal/ingest/provider.go` `Feed` interface and the Kite Connect adapter.
- **How to integrate:** Implement eqats‑specific adapters (e.g., for NSE/BSE multicast, broker APIs, or CSV replay) that satisfy the same `Feed` contract (`Subscribe() <-chan Quote`, `Close()`). The existing normalization/validation pipeline (`internal/ingest/normalizer.go`‑style) can be wrapped around any adapter.
- **Benefit:** Adding a new market‑data source becomes a drop‑in replacement; no changes needed in the engine or API.

### 2. Hot State Management with Redis
- **What to reuse:** Patterns for storing latest quotes (`market:quote:<symbol>`), tick streams (`market:ticks` stream), and consumer groups.
- **How to integrate:** In eqats, replace any in‑memory cache with Redis Streams for the raw tick feed and Redis hashes for the latest L1/L2 data. Use `XREADGROUP` with the engine as a consumer group to achieve exactly‑once processing semantics.
- **Benefit:** Decouples ingestion from strategy evaluation, enables horizontal scaling of engine workers, and provides built‑in buffering during traffic spikes.

### 3. Persistence Layer (Supabase/Postgres)
- **What to reuse:** Schema design that stores only signals and 1‑minute candles; RLS policies; Realtime publication on the `signals` table.
- **How to integrate:** Adopt the same table layout (`signals(id, user_id, strategy_id, symbol, direction, price, ts)` and `candle_1m(id, symbol, open, high, low, close, volume, ts)`). Enable Supabase Realtime on `signals` and configure RLS so each user sees only their own signals.
- **Benefit:** Guarantees that raw market data never hits the database, reducing storage costs and simplifying compliance.

### 4. Live Quote Distribution via SSE
- **What to reuse:** The `/ws/quotes` endpoint in the Go API that reads Redis latest‑state and pushes via Server‑Sent Events.
- **How to integrate:** Expose an eqats‑compatible SSE endpoint (`/api/v1/quotes`) that subscribes to Redis pub/sub (`market:quote:*`) and forwards updates to connected clients (web, mobile, desktop).
- **Benefit:** Provides low‑latency quote UI without exposing the raw tick feed to the browser.

---

## Signal & Execution Logic Integration

### 1. Validated JSON Strategy DSL
- **What to reuse:** The DSL parser/validator in `internal/engine/rules.go` (whitelisted metrics: SMA, RSI, volatility; operators: >, <, ==, AND, OR).
- **How to integrate:** Incorporate the parser into eqats’ strategy service. Store strategies as JSON blobs in Postgres (or Supabase). On strategy creation/update, run the validator; reject any unknown metric or operator at save time.
- **Benefit:** Eliminates the risk of executing untrusted user code while still allowing expressive rule‑based strategies.

### 2. Rolling Metrics Engine
- **What to reuse:** Incremental SMA, RSI, and volatility calculators that consume the Redis tick stream.
- **How to integrate:** Deploy a fleet of eqats metric workers that subscribe to the same Redis consumer group used by the ingestion layer. Each worker updates per‑symbol metric tables in Redis (e.g., `metrics:sma:<symbol>:<period>`). Strategies read these pre‑computed metrics via fast Redis `GET` calls.
- **Benefit:** Offloads heavy computation from strategy evaluation, ensuring sub‑millisecond signal latency.

### 3. Signal Generation & Debounce
- **What to reuse:** Signal assembly (direction, price, timestamp) and Redis `SET NX` cooldown keys (`signal_cool:<strategy_id>:<symbol>`).
- **How to integrate:** After a strategy rule evaluates to true, attempt to set a cooldown key with a configurable TTL (e.g., 5 seconds). Only if the SET succeeds (`NX`) emit the signal. This guarantees idempotent handling even if the tick stream delivers duplicates.
- **Benefit:** Prevents over‑trading due to network retransmissions or stream replay.

### 4. Signal Delivery & Real‑Time UI
- **What to reuse:** Supabase Realtime broadcast of inserts to the `signals` table with RLS filtering.
- **How to integrate:** In eqats, write signals to the eqats Postgres (or Supabase) `signals` table. Enable Realtime on that table and configure row‑level policies so each authenticated user receives only signals belonging to their strategies. The frontend can subscribe via the Supabase JS client.
- **Benefit:** Provides instant, secure signal push to any client without building a custom WebSocket server.

### 5. 1‑Minute Candle Aggregation
- **What to reuse:** Batch upsert of OHLCV candles to Postgres (once per minute).
- **How to integrate:** In the engine, upon receiving a tick, update running OHLCV accumulators per symbol; on minute boundary, insert/upsert the candle into a `candle_1m` table. This data can feed charting components and back‑testing.
- **Benefit:** Gives eqats a ready‑to‑use historical candle set without extra storage pipelines.

---

## Risk Engineering Integration

The repository does not contain explicit risk‑limit, position‑sizing, or risk‑monitoring components. Therefore, **no direct features** from `market‑platform` map to the Risk Engineering domain. Eqats would need to add its own risk‑engine (e.g., max‑drawdown limits, per‑strategy capital allocation, volatility‑based position sizing) on top of the signal execution pipeline.

---

## Suggested Implementation Roadmap for eqats

1. **Adapter Layer** – Define a `Feed` interface in eqats; implement a Kite Connect adapter (or reuse the existing one) and a mock adapter for testing.
2. **Redis Hot‑State** – Deploy Redis Streams; set up ingestion workers to publish normalized ticks; configure engine workers as a consumer group.
3. **Metrics Service** – Build incremental SMA/RSI/vol calculators that read from the tick stream and write results to Redis hashes.
4. **Strategy DSL** – Import the JSON validator from `market‑platform`; integrate with eqats’ strategy CRUD API.
5. **Signal Engine** – Consume metrics, evaluate DSL rules, apply Redis `SET NX` debounce, write signals to Postgres.
6. **Realtime Delivery** – Enable Supabase (or Postgres logical decoding + pg_notify) Realtime on the `signals` table; enforce RLS.
7. **Live Quote API** – Add an SSE endpoint that reads Redis latest‑state and pushes to clients.
8. **Candle Aggregation** – Implement per‑symbol OHLCV roll‑up and minute‑boundary upserts.
9. **Observability** – Export Prometheus metrics from ingestion, engine, and API layers (follow the existing patterns in the repo).
10. **Testing & CI** – Leverage the existing Go test suite (`go test ./...`) and extend with eqats‑specific unit tests for the DSL and risk rules.

By adopting these components, eqats gains a robust, scalable market‑data pipeline, a secure and verifiable strategy execution engine, and low‑latency signal delivery—all while keeping raw ticks off the persistence layer and the frontend.
