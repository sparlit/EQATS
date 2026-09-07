# Integration Blueprint for Solana Copytrading Bot Features into eqats

## Overview
The Solana Copytrading Bot demonstrates a high‑performance copy‑trading pipeline on Solana DEXs. Its most valuable components are:
- Low‑latency transaction ingestion via gRPC/Geyser RPC
- Direct DEX swap execution (bypassing aggregators)
- Ultra‑fast confirmation services (Jito, NextBlock)
- Configurable slippage and position sizing
- Modular Rust architecture separating data ingestion, signal logic, execution, and risk.

These concepts can be mapped onto the eqats domains as follows.

## 1. Data Engines
**Feature:** GRPC‑based transaction fetching and wallet monitoring.
**Integration:**
- Replace or augment eqats’ market‑data feed with a gRPC client that subscribes to Solana Geyser RPC (or equivalent) for real‑time transaction streams.
- Implement a parser similar to `monitor.rs` to decode raw transactions into swap events (token in/out, amounts, DEX program ID).
- Store incoming events in eqats’ existing ingestion pipeline (e.g., Kafka topic or internal buffer) for downstream processing.
- Reuse the `targetlist.rs` pattern to maintain a whitelist of source wallets to monitor.
- Centralise configuration (RPC URLs, gRPC endpoints, constants) in eqats’ config module, mirroring `common/config.rs` and `common/constants.rs`.

## 2. Signal & Execution Logic
**Feature:** Copy‑trade signal generation and direct DEX swap execution.
**Integration:**
- **Signal Layer:** Create a strategy module that watches the ingested transaction stream for swap events from target wallets. When a swap is detected, emit a trading signal (e.g., `BUY token X amount Y` or `SELL`). This mirrors the detection logic in `engine/monitor.rs`.
- **Execution Layer:** Instead of routing through an aggregator (like Jupiter), implement direct swap handlers for each supported DEX (Raydium, Meteora, Pumpfun, Pumpswap) akin to `engine/swap.rs` and the dex‑specific files. Each handler builds and sends the appropriate Solana transaction using the wallet’s keypair.
- **Confirmation:** Integrate Jito and NextBlock services (as in `services/jito.rs` and `services/nextblock.rs`) to attach priority fees and bundle transactions for ultra‑fast inclusion, reducing latency from ~300‑500 ms to ~50‑100 ms.
- **Parameterisation:** Make slippage, token percentage, and DEX choice configurable via environment variables or eqats’ config system, just as the bot uses `SLIPPAGE` and `TOKEN_PERCENTAGE`.

## 3. Risk Engineering
**Feature:** Slippage control, position sizing, and fee management.
**Integration:**
- Apply the `SLIPPAGE` environment variable as a max slippage tolerance in eqats’ order‑builder, reverting trades if price impact exceeds the threshold.
- Use `TOKEN_PERCENTAGE` to define the fraction of available capital to allocate per copied trade, providing a simple fixed‑fraction position‑sizing rule.
- Leverage Jito tip settings (`JITO_TIP_PERCENTILE`, `JITO_TIP_VALUE`) to dynamically set priority fees, balancing confirmation speed against cost—a form of transaction‑cost risk management.
- Add monitoring hooks (similar to `common/logger.rs`) to log slippage, actual fees paid, and execution latency for post‑trade risk analysis.

## Implementation Steps
1. **Data Ingestion**
   - Add gRPC client dependency.
   - Implement Geyser RPC subscription for `confirmed` or `finalized` transactions.
   - Parse transaction logs to identify swap instructions on target DEX programs.
   - Publish parsed events to eqats’ signal bus.
2. **Signal Generation**
   - Develop a strategy that filters events by whitelisted wallets (`targetlist.txt` equivalent).
   - Convert each swap event into a signal object (direction, token, amount).
3. **Execution Engine**
   - Build DEX‑specific transaction constructors (Raydium, Meteora, Pumpfun, Pumpswap) using Solana SDK.
   - Integrate Jito/NextBlock for fee bundling and fast confirmation.
   - Execute signals with slippage checks and position sizing derived from config.
4. **Risk Controls**
   - Enforce max slippage and max position size per trade.
   - Log transaction metadata (signature, latency, fee) for audit and risk reporting.
5. **Configuration & Observability**
   - Centralise RPC URLs, gRPC endpoints, DEX program IDs, slippage, token percentage, Jito settings in eqats’ config module.
   - Use a logger akin to `common/logger.rs` for structured output.

By adopting these patterns, eqats can achieve low‑latency, direct‑DEX copy trading with robust risk controls, mirroring the strengths of the Solana Copytrading Bot while staying within its existing architecture.