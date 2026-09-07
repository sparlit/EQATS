# Integration Blueprint: geger → eqats

## Overview
[geger](https://github.com/day0market/geger) is a lightweight, event‑driven algorithmic trading framework written in Rust. Its core strengths lie in a clean separation of concerns: market data ingestion (EventProvider), event distribution (EventLoop), user‑defined logic (Actors), and flexible inter‑component messaging (MessageBus). While it does not provide sophisticated risk‑management primitives, its extensible Actor model makes it straightforward to embed risk checks, position sizing, and monitoring as additional components.

## Mapping geger Features to eqats Domains

### Data Engines
- **EventProvider abstraction** – eqats can adopt a similar pluggable provider interface to support multiple data sources (live feeds, historical CSV/Databases, simulated environments).
- **SimulatedEnvironment for backtesting** – eqats already has a backtesting harness; integrating geger’s simulated provider would allow reuse of its latency‑emulation (wire & internal) per exchange, enhancing realism.
- **Market data event model** – geger’s `Event` enum (trades, quotes, order updates, exchange responses) maps directly onto eqats’ market‑data message types; eqats could expose a unified `MarketEvent` that mirrors this structure.
- **Multi‑symbol / multi‑exchange support** – geger’s ability to route events for any symbol/exchange to any Actor aligns with eqats’ portfolio‑level design; eqats can leverage this to simplify subscription management.

### Signal & Execution Logic
- **Actor trait (`on_event`)** – eqats’ strategy interface can be refactored to resemble geger’s Actor, where each strategy receives market events and has access to an execution context.
- **ActionsContext** – provides order submission, cancellation, and custom messaging. eqats can expose an equivalent `ExecutionContext` with methods `send_order`, `cancel_order`, and `send_signal`.
- **Message trait & MessageBus** – geger’s user‑defined messaging system (topic‑based, async) is a perfect fit for eqats’ signal bus. eqats could replace its current pub‑sub with a MessageBus that routes `Message` implementations (e.g., `PnLUpdate`, `RiskAlert`) to interested Actors.
- **Order model** – geger’s `NewOrderRequest`/`CancelOrderRequest` structs (including `client_order_id`, `exchange_order_id`, `timestamp`, `price`, `quantity`, `side`, `time_in_force`) can be adopted as the canonical order request in eqats, ensuring compatibility with simulated and live adapters.
- **GTC limit orders** – while geger’s simulation currently only supports GTC limits, eqats can keep this as the default order type in backtest mode and extend to other types (IOC, FOK, market) for live trading.

### Risk Engineering
- **No native risk modules** – geger does not ship risk‑limit engines, position‑sizing algorithms, or real‑time monitors. eqats should therefore implement its own risk layer as a set of specialized Actors:
  - *Pre‑trade risk Actor*: validates incoming orders against limits (max notional, leverage, concentration) before forwarding to `ExecutionContext`.
  - *Post‑trade monitoring Actor*: listens to `OrderUpdate` events and custom messages (e.g., `PnLUpdate`) to enforce stop‑loss, drawdown, or VaR limits.
  - *Position‑sizing Actor*: consumes signals (e.g., `SignalStrength`) and computes order quantities based on volatility or Kelly criteria, then emits a `NewOrderRequest` via the `ActionsContext`.
- Because geger’s `MessageBus` already supports custom topics, risk Actors can subscribe to topics like `risk/limits`, `pnl/updates`, and publish actions on `risk/alerts` or `orders/new`.

## Integration Steps
1. **Define a common `MarketEvent` enum** in eqats that mirrors geger’s `Event` (trade, quote, order update, exchange response).
2. **Implement an `EventProvider` trait** with a `next_event()` method; provide concrete implementations for live feeds (WebSocket/FIX) and a `SimulatedEnvironment` that reproduces geger’s latency model.
3. **Create an `Actor` trait** (`fn on_event(&mut self, event: &MarketEvent, ctx: &mut ExecutionContext)`) and a generic `ActorRunner` that spawns each Actor in its own thread (or async task) and feeds it events from the shared `EventLoop`.
4. **Build an `ExecutionContext`** exposing:
   - `send_order(NewOrderRequest) -> Result<(), ExecutionError>`
   - `cancel_order(CancelOrderRequest) -> Result<(), ExecutionError>`
   - `send_message(M: Message) -> Result<(), ExecutionError>`
   where `NewOrderRequest`/`CancelOrderRequest` are taken from geger’s definitions.
5. **Develop a `Message` trait** (`get_topic()`, `is_stop()`, `new_stop()`) and a `MessageBus` that runs on a dedicated thread, routing messages to Actors that have subscribed to the topic.
6. **Port example strategy** from geger’s `examples/strategy.rs` into eqats, showing how an enum of Actors can be used to host multiple strategy types within a single engine.
7. **Add risk‑engine Actors** (pre‑trade, post‑trade, sizing) as described above, demonstrating how eqats can achieve full risk‑engineered workflows without modifying the core engine.
8. **Update configuration** to allow users to select the data provider, enable/disable the MessageBus, and compose a list of Actors (strategies + risk modules) at startup.

## Expected Benefits
- **Modularity**: Clear separation between data ingestion, strategy logic, execution, and risk management.
- **Reusability**: geger’s tested event loop and messaging infrastructure reduce boilerplate in eqats.
- **Realism**: Latency emulation and multi‑exchange support improve backtest fidelity.
- **Extensibility**: Adding new data sources, order types, or risk rules only requires implementing the respective provider or Actor trait.

By incorporating geger’s event‑driven core and messaging system, eqats gains a battle‑tested, highly composable foundation while retaining the flexibility to plug in its own advanced analytics, machine‑learning signals, and sophisticated risk controls.
