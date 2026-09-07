# Integration Blueprint for xcrypto Features into eqats

## Overview
xcrypto provides a high‑performance Rust‑Tokio trading gateway with a Python strategy layer (pyalgo). The following features can be leveraged to enhance eqats.

## Data Engines
- **WebSocket market data ingestion** – xcrypto subscribes to Binance depth and kline streams and forwards quotes to strategies via WebSocket. eqats can adopt a similar Tokio‑based WebSocket client to normalize exchange data and distribute it to multiple strategy instances.
- **Session‑scoped position store** – each strategy session maintains its own position record (persisted via SQLite, as indicated by the sqlite3 prerequisite). eqats could introduce a session‑id keyed SQLite table to store and query positions, enabling isolated P&L tracking.
- **High concurrency** – the system supports up to 65 536 concurrent strategies thanks to Tokio’s async runtime. eqats can increase its own strategy capacity by moving blocking I/O to async tasks and using a similar task‑per‑session model.

## Signal & Execution Logic
- **Python strategy framework (pyalgo)** – strategies are written in Python using Engine, Session, and callbacks (`on_depth`, `on_order`). eqats can expose a comparable Python API (e.g., via PyO3/maturin) that allows users to define strategy classes with lifecycle hooks.
- **SmartOrder abstraction** – provides `send` and `kill` methods with parameters for price, quantity, side, order type, and time‑in‑force. Integrating a similar order‑builder would simplify order creation in eqats strategies.
- **Phased trading logic** – sessions can define time‑based phases (OPEN/CLOSE) that drive strategy behavior. eqats could add a phase manager to enable time‑windowed strategy activation/deactivation.
- **Order feedback loop** – order status updates are delivered back to the strategy via the `on_order` callback, enabling reactive risk checks.

## Risk Engineering
- **Position‑mode flag** – xcrypto requires setting the account to Single‑Side Position mode before running. eqats can enforce a similar pre‑run check or configure the exchange API accordingly.
- **Margin vs spot toggle** – a boolean `margin` in the configuration selects spot or cross‑margin futures. eqats could add a configuration switch to route orders to the appropriate account type.
- **Trading‑disable switch** – when creating a Session with `trading=False`, the strategy receives market data but cannot send orders. This provides a safe read‑only mode for research or risk‑off periods; eqats can implement an equivalent flag.
- **Authentication via API key & private key** – xcrypto loads an API key and a PEM file for signed requests. eqats can adopt the same pattern to secure exchange connectivity.
- **Logging level** – the `-l=info` argument controls verbosity; eqats can expose a similar log‑level switch for runtime monitoring.

## Integration Steps
1. **Add Tokio‑based WebSocket client** for exchange market data, mirroring xcrypto’s forwarding mechanism.
2. **Introduce a Session abstraction** that holds an ID, subscribes to data streams, and stores positions in a SQLite table keyed by session_id.
3. **Expose a Python strategy SDK** (using PyO3/maturin) with Engine, Session, `on_depth`/`on_order` callbacks, and a SmartOrder‑like order builder.
4. **Implement phase‑based activation** (e.g., OPEN/CLOSE) to allow time‑windowed strategy logic.
5. **Add risk‑control flags**: single‑side position check, margin/spot toggle, trading‑disable per session, and API‑key/PEM authentication.
6. **Configure logging** via command‑line argument to match xcrypto’s `-l=` option.
7. **Test** by running the compiled binary with a configuration file (spot.json/usdt.json) and a simple Python strategy that subscribes to depth and sends limit orders, verifying order feedback and position updates.

By incorporating these components, eqats can achieve comparable low‑latency, high‑concurrency trading capabilities while retaining a user‑friendly Python strategy development experience.
