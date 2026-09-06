# Integration Blueprint for extrema_infra into eqats

## Overview
`extrema_infra` provides a high‑performance, Rust‑based quantitative trading infrastructure that emphasizes static dispatch, zero‑copy data flow, and modular strategy composition. The following blueprint maps its most valuable components to the three eqats domains: Data Engines, Signal & Execution Logic, and Risk Engineering.

---

## 1. Data Engines

### WebSocket Ingestion
- **Public & Account WS tasks**: Separate ingestion streams for market data (trade/book/price) and private data (position/order/fill).
- **Integration point**: Replace eqats’ current WS adapters with extrema_infra’s `PUB` and `ACC` tasks, which publish to Tokio broadcast rings keyed by `TaskKey`.

### Unified Exchange Abstraction
- **Market enum & shared structs**: All exchange clients translate REST/WS payloads into a common `Market` type.
- **Integration point**: Use this abstraction layer to normalize data from Binance, OKX, Gate, Hyperliquid (or any new exchange) before it reaches eqats’ signal modules, eliminating exchange‑specific parsing duplication.

### Normalized Data Conversion
- **Single conversion before broadcast**: WS data is decoded once, then broadcast to all subscribers.
- **Integration point**: Ensures eqats’ downstream consumers receive identical, pre‑parsed market snapshots, reducing CPU overhead.

### Task‑Local Broadcast Distribution
- **Per‑TaskKey Tokio broadcast ring**: Each logical task (e.g., a symbol‑level feed) owns its own broadcast channel; multiple strategies subscribe without extra exchange I/O.
- **Integration point**: eqats can register its strategy modules as subscribers to the relevant `TaskKey` rings, achieving fan‑out with zero extra network traffic.

### Channel‑Based Concurrency
- **Tokio channels & broadcast streams**: Explicit message passing eliminates shared‑state locks.
- **Integration point**: Adopt extrema_infra’s channel topology for eqats’ internal data pipelines (e.g., feature → model → allocator → executor) to maintain latency‑sensitive, lock‑free flow.

---

## 2. Signal & Execution Logic

### Heterogeneous Strategy Registration via HList
- **Static dispatch**: Strategies are stored in an HList, preserving concrete types and avoiding `Box<dyn Strategy>` vtable overhead.
- **Integration point**: Replace eqats’ current `Vec<Box<dyn Strategy>>` with an HList‑based registry. This yields compile‑time guarantees that only types implementing the `Strategy` trait can be registered and enables monomorphisation of strategy‑specific logic.

### Feature Stream – AltTensor
- **Common dense tensor payload**: Features and model outputs are exchanged as `AltTensor`.
- **Integration point**: Define eqats’ feature vectors as `AltTensor` instances; this allows seamless hand‑off to both Python ML models (via ZeroMQ) and ONNX models running inside Rust.

### Machine Learning Integration
- **ZeroMQ bridge to Python**: Features sent over ZeroMQ to external Python models (Torch, GBM, Transformers). Predictions return asynchronously.
- **ONNX in‑process**: ONNX models can be loaded and executed directly within the Rust runtime.
- **Integration point**: 
  1. Add a ZeroMQ publisher/subscriber pair in eqats that mirrors extrema_infra’s `FEAT → M1/M2/M3` path.
  2. For low‑latency inference, integrate the `onnx` crate to run ONNX models natively, exposing the same `AltTensor` output interface.

### Model Prediction Tasks
- **Async return of AltTensor**: Predictions flow back to Rust without blocking the ingestion loop.
- **Integration point**: Model tasks subscribe to the feature broadcast ring, compute predictions, and publish to a `MPRED` broadcast ring that allocator modules consume.

### Allocator Modules
- **Input**: Model predictions (`AltTensor`), latest price, account state.
- **Output**: Allocation intent (e.g., target weights).
- **Integration point**: Implement eqats’ allocator as a strategy module that listens to `MPRED` and `ACC` rings, computes position targets, and publishes to the portfolio‑mediator ring.

### Portfolio Mediator (Risk / Constraints / OMS)
- **Function**: Receives allocator intent, applies risk limits, position constraints, and forwards cleaned orders to the planner.
- **Integration point**: eqats can reuse this mediator as a central risk gate; it already exposes `on_order_execution` for downstream consumption.

### Order Planner
- **Features**: Slice, net, reduce‑only, routing logic.
- **Integration point**: Plug eqats’ execution logic into this planner; it transforms allocator intent into executable order batches.

### Order‑Execution Modules
- **REST submission**: Default path for placing orders via exchange REST APIs.
- **WS command handle**: Optional low‑latency WebSocket order route (`CMD`).
- **Integration point**: Implement eqats’ order executor as one or more `Oi` modules that subscribe to the planner’s `OrderExecute` broadcast and either call REST endpoints or send WS commands via the provided handle.

---

## 3. Risk Engineering

### Portfolio Mediator – Risk Limits & Constraints
- **Built‑in risk checks**: The mediator enforces max exposure, leverage, and per‑symbol limits before passing orders to the planner.
- **Integration point**: Directly adopt this mediator as eqats’ risk engine; configure limits via its API or configuration struct.

### Allocator‑Level Position Sizing
- **Uses account state**: Allocator combines predictions with current positions/fills to compute size adjustments.
- **Integration point**: eqats can reuse the allocator’s sizing logic or extend it with custom sizing models (Kelly, volatility‑scaled, etc.).

### Order Planner – Slice / Net / Reduce‑Only
- **Execution‑style controls**: Allows slicing large orders, netting opposite‑side positions, and posting reduce‑only orders to minimize market impact and comply with exchange rules.
- **Integration point**: Plug eqats’ execution preferences into the planner’s configuration to automatically apply these risk‑reducing tactics.

### WS Order Command Handle
- **Low‑latency, risk‑aware path**: Provides a direct WebSocket channel for submitting orders after risk checks, bypassing REST latency while still routing through the mediator.
- **Integration point**: Use this handle for ultra‑low‑latency strategies where speed is critical, ensuring all orders still pass through the mediator’s risk gate.

---

## Summary of Integration Steps
1. **Replace WS adapters** with extrema_infra’s `PUB`/`ACC` tasks and broadcast rings.
2. **Adopt the unified `Market` enum** for all exchange data.
3. **Introduce HList‑based strategy registry** to obtain static dispatch.
4. **Standardize on `AltTensor`** for feature/model payloads.
5. **Add ZeroMQ bridge** for external Python ML and/or ONNX runtime for in‑process inference.
6. **Construct allocator, portfolio mediator, planner, and executor modules** mirroring the signal‑to‑execution flow.
7. **Configure risk limits** in the mediator and optionally tune slicing/net/reduce-only behavior in the planner.
8. **Leverage channel‑based concurrency** (Tokio channels/broadcast) throughout eqats’ data pipelines.

By mapping these components, eqats gains a battle‑tested, low‑latency, type‑safe infrastructure that cleanly separates data ingestion, signal generation, execution planning, and risk management while retaining the flexibility to plug in custom models and strategies.
