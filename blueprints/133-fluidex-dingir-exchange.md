# Integrating Dingir Exchange into eqats

## Overview
Dingir Exchange is a high‑performance, async Rust‑based matching engine that exposes its core services via gRPC. It provides persistent order books, user balances, and market data through an append‑only log and a Redis‑like fork‑and‑save mechanism, with Kafka used for event streaming.

## Data Engine Integration
- **Storage**: Replace or supplement eqats’ current storage layer with Dingir’s SQL database (PostgreSQL) for durable order and balance records. The append‑only log can be used as an event source for replaying state.
- **Persistence**: Adopt Dingir’s fork‑and‑save snapshot strategy to create periodic lightweight snapshots of the exchange state, enabling fast recovery.
- **Market Data**: Subscribe to Dingir’s gRPC market data stream (or Kafka topic) to obtain real‑time order book updates, trades, and balance changes, feeding eqats’ data engine for indicator calculation.
- **Ingestion**: Use the librdkafka‑based consumer to ingest Dingir’s event log into eqats’ stream processing pipeline (e.g., Flink, Kafka Streams).

## Signal & Execution Logic Integration
- **Execution Layer**: Call Dingir’s matching engine through its gRPC `MatchEngine` service to submit, cancel, and amend orders. Order state change notifications (new, partially filled, filled, cancelled) are pushed via gRPC streaming, providing immediate execution feedback to eqats’ strategy engine.
- **Order Management**: Leverage Dingir’s internal order ID generation and lifecycle handling; eqats can maintain a thin mapping layer to correlate its own order identifiers with Dingir’s.
- **Trade Flow**: When a trade occurs, Dingir publishes a trade event (via gRPC or Kafka). eqats can consume this event to update position sizing, calculate PnL, and trigger downstream risk checks.

## Risk Engineering Considerations
Dingir does not implement risk limits, position checks, or margin monitoring. Therefore, eqats must place a risk‑engineering layer **above** the Dingir integration:
- **Pre‑trade risk**: Validate order size, price, and exposure against eqats’ risk limits before forwarding the order to Dingir’s gRPC endpoint.
- **Post‑trade risk**: Use Dingir’s trade and balance updates to recompute margin, leverage, and VaR; trigger alerts or automatic liquidation if thresholds are breached.
- **Monitoring**: Export Dingir’s metrics (via its Prometheus endpoint if available or via gRPC health checks) into eqats’ monitoring stack for latency and throughput observability.

## Deployment Steps
1. **Dependencies**: Ensure `cmake` and `librdkafka` are installed (as per Dingir’s prerequisites).
2. **Run Dingir**: Use the provided `docker‑compose` file to launch PostgreSQL and Kafka, then start the matchengine (`cargo run --bin matchengine` or `make startall`).
3. **eqats Configuration**:
   - Set the gRPC endpoint to Dingir’s `matchengine` service (default `localhost:50051`).
   - Configure Kafka consumer groups to listen to Dingir’s `trades`, `order_events`, and `balance_updates` topics.
   - Enable the append‑only log ingestion if event sourcing is desired.
4. **Build**: eqats can continue to be built in its native language (e.g., Python/Go/Rust) while linking against the Dingir gRPC protobufs.
5. **Testing**: Follow Dingir’s example (`npx ts-node tests/trade.ts`) to verify order flow, then replace the test client with eqats’ strategy engine.

## Example Pseudocode (Rust)
```rust
// eqats strategy component
let client = MatchEngineClient::connect(\"http://localhost:50051\").await?;
let order = Order::new(...);
let response = client.create_order(order).await?;
// Listen to order state stream
let mut stream = client.order_state_stream(Empty::default()).await?;
while let Some(state) = stream.message().await? {
    // forward to eqats risk & position manager
    process_order_state(state);
}
```

## Benefits
- **Performance**: Inherit Dingir’s thousands‑of‑TPS matching engine.
- **Reliability**: Use its proven persistence and replication model.
- **Flexibility**: Decouple strategy (eqats) from execution (Dingir) via well‑defined gRPC/Kafka contracts.
- **Observability**: Re‑use Dingir’s metrics and logging for end‑to‑end monitoring.

## Caveats
- Dingir lacks built‑in risk controls; eqats must enforce them.
- The exchange does not handle crypto deposit/withdraw or KYC; those remain outside eqats’ scope or need separate adapters.
- Ensure version compatibility of protobuf definitions between eqats and Dingir releases.
