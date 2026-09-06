# Integration Blueprint: ShortCircuit Features into eqats

## Overview
ShortCircuit provides a tightly‑coupled, production‑grade intraday execution engine for NSE equities. Its clean separation of "Brain" (strategy) and "Muscle" (runtime) makes it a strong candidate for modular adoption into the eqats framework. Below is a concrete plan to map ShortCircuit’s notable features onto eqats’ three domains: Data Engines, Signal & Execution Logic, and Risk Engineering.

---

## Data Engines Integration

### 1. WebSocket‑First Quote Cache with Freshness Tracking
- **What to adopt:** Implement a quote cache that tracks per‑symbol freshness states (UNINITIALIZED → PRIMING → READY → DEGRADED → REPRIME/RECOVER).
- **How to integrate:** Replace or augment eqats’ current market‑data subscriber with a wrapper that:
  - Seeds the cache via REST (e.g., NSE/BSE snapshot).
  - Updates freshness on each WebSocket tick.
  - Blocks strategy evaluation until the cache reaches READY.
  - Allows automatic reprieve on DEGRADED state.

### 2. NSE‑EQ Scanner Universe
- **What to adopt:** The universe builder that scans thousands of NSE symbols each session, filtering by liquidity, price, and sector constraints.
- **How to integrate:** Plug the scanner into eqats’ symbol‑universe generator, exposing a configurable list (e.g., top 500 by avg daily volume) that can be refreshed intraday.

### 3. Parquet‑Based ML Feedback Loops
- **What to adopt:** Logging of features, signals, and outcomes to partitioned Parquet files for offline model training.
- **How to integrate:** Extend eqats’ existing data‑lake writer to append tick‑level feature vectors (VWAP, RSI, volume fade, ATR, etc.) and trade outcomes to a Parquet dataset partitioned by date/symbol.

### 4. PostgreSQL Audit Trail & EOD Reporting
- **What to adopt:** Structured audit of every signal, order, fill, and state change.
- **How to integrate:** Use eqats’ PostgreSQL connector (or add one if missing) to store:
  - Signal events (gate passes, brain decisions).
  - Order lifecycle (sent, acknowledged, filled, rejected).
  - Reconciliation discrepancies.
  - Generate EOD reports via SQL queries or a lightweight reporting script.

### 5. Broker/DB Reconciliation
- **What to adopt:** A reconciliation process that compares local position/order state with broker reports and resolves breaks.
- **How to integrate:** Adapt ShortCircuit’s `state/reconciliation.py` into eqats’ risk‑monitoring service, scheduling it to run every few minutes during market hours and at EOD.

---

## Signal & Execution Logic Integration

### 1. Brain/Muscle Architecture & Strategy Isolation
- **What to adopt:** Enforce that strategy modules import no runtime‑specific libraries (broker, websocket, file I/O).
- **How to integrate:** Add a unit test (similar to `tests/unit/test_brain_isolation.py`) to eqats’ CI that parses the AST of all strategy files and flags prohibited imports.

### 2. BackToVWAPShort Strategy
- **What to adopt:** The single exhaustion‑mean‑reversion strategy that combines:
  - Intraday gain extension.
  - VWAP‑standard‑deviation stretch.
  - Value‑Area‑High (VAH) rejection.
  - Volume fade after surge.
  - Higher‑timeframe stall/fail‑open guard.
  - Structural trigger (break of entry level).
- **How to integrate:**
  - Copy `strategy/back_to_vwap.py` and its dependencies (`features.py`, `market_profile.py`, `market_context.py`, `htf_confluence.py`) into eqats’ `strategies/` directory.
  - Expose the strategy via eqats’ strategy registry (e.g., `eqats.strategies.BackToVWAPShort`).
  - Ensure the strategy receives only a feature‑vector (pre‑computed by the Data Engine) and returns a signal enum (e.g., `ENTER_SHORT`, `EXIT`, `HOLD`).

### 3. Sequential Gate Validation Pipeline
- **What to adopt:** A multi‑stage gate system (structure → momentum → volume → profile → HTF) that must all pass before a trade is considered.
- **How to integrate:** Implement a `GateEngine` class in eqats that:
  - Takes the raw market data snapshot.
  - Applies each gate as a pure function (no side‑effects).
  - Returns a gate‑pass flag and optional debug info.
  - Can be configured to enable/disable specific gates.

### 4. Analyzer Orchestrator & Order Manager
- **What to adopt:** `execution/analyzer.py` (calls the Brain) and `execution/order_manager.py` (handles broker interaction).
- **How to integrate:**
  - Create an eqats `ExecutionEngine` that:
    1. Receives a signal from the strategy.
    2. Checks risk limits (see Risk Engineering).
    3. Delegates order creation to a broker‑agnostic `OrderManager`.
    4. Uses a broker‑specific adapter (e.g., Fyers) for order submission and fill verification.

### 5. Telegram Command & Control
- **What to adopt:** Real‑time control via Telegram commands (e.g., `/mode buy`, `/status`, `/stop`).
- **How to integrate:** Leverage eqats’ existing notification module or add a lightweight Telegram bot that:
  - Accepts authenticated commands.
  - Triggers strategy mode changes, kill‑switches, or status queries.
  - Sends P&L, open‑position, and system‑health updates.

### 6. Single‑Position Capital Slot & Broker‑Verified Stops
- **What to adopt:** At most one active position per symbol, with stop‑loss placed and verified on the broker side.
- **How to integrate:**
  - Enforce a global max‑positions‑per‑strategy limit in the Risk Engine.
  - On order submission, attach a stop‑loss order and poll the broker until the stop is acknowledged (or reject the trade).

---

## Risk Engineering Integration

### 1. Capital‑Aware Position Sizing
- **What to adopt:** Position size derived from available capital, volatility (ATR), and risk‑per‑trade.
- **How to integrate:** Replace eqats’ fixed‑fraction sizing with a function:
  ```python
  size = (capital * risk_per_trade) / (ATR * stop_multiple)
  ```
  Ensure the result respects lot‑size and leverage constraints.

### 2. Higher‑Timeframe Risk Gates
- **What to adopt:** HTF confluence module that blocks trades when the higher‑timeframe trend is adverse or shows fail‑open conditions.
- **How to integrate:** Call the HTF gate as part of the sequential gate validation; treat a HTF fail as a hard risk reject.

### 3. State/Reconciliation Immune System
- **What to adopt:** Continuous verification of local state (positions, orders) against broker reports.
- **How to integrate:** Run the reconciliation loop as a background task; on mismatch, trigger:
  - Automatic cancel/replace of stale orders.
  - Alert via Telegram/log.
  - Optional pause of new signal generation until resolved.

### 4. Single‑Position Exposure Limit
- **What to adopt:** Enforce that only one position (long or short) can be open per symbol/strategy.
- **How to integrate:** Maintain a position map in the Risk Manager; reject new entry signals if an open position exists for the same symbol.

### 5. EOD Risk Reporting
- **What to adopt:** End‑of‑day summary of P&L, max drawdown, trade counts, and reconciliation breaks.
- **How to integrate:** Generate a report from the PostgreSQL audit table and distribute via email/Telegram.

---

## Implementation Steps

1. **Setup Environment**
   - Ensure Python 3.11+.
   - Add required libraries: `fyers-api`, `websockets`, `pandas`, `numpy`, `sqlalchemy`, `python-telegram-bot`, `pyarrow`.

2. **Data Engine Layer**
   - Implement the freshness‑aware quote cache.
   - Build the NSE‑EQ scanner universe.
   - Add Parquet logger and PostgreSQL audit hooks.
   - Wire the reconciliation task.

3. **Signal & Execution Layer**
   - Add strategy isolation test to CI.
   - Port BackToVWAPShort and its feature/market‑profile modules.
   - Create the GateEngine and ExecutionEngine.
   - Implement Telegram bot for C&C.
   - Develop the OrderManager with broker‑verified stop placement.

4. **Risk Engineering Layer**
   - Implement capital‑aware sizing function.
   - Integrate HTF gate into GateEngine.
   - Activate position‑limit checks.
   - Deploy reconciliation immune system.
   - Add EOD reporting job.

5. **Testing & Validation**
   - Run unit tests for strategy isolation.
   - Simulate market‑data replay to verify gate logic.
   - Perform paper‑trading runs on historical NSE intraday data.
   - Validate reconciliation breaks are detected and resolved.

---

## Considerations

- **Broker Agnosticism:** While ShortCircuit uses Fyers, the adapter pattern lets eqats plug in any broker (e.g., Zerodha, Upstox) by implementing a common interface.
- **Configurability:** All thresholds (VWAP‑stretch, volume‑fade, ATR multiples, risk‑per‑trade) should be externalized to YAML/JSON files for easy tuning.
- **Latency:** The WebSocket‑first cache ensures low‑latency decision making; ensure the gate pipeline is optimized (pure functions, minimal allocations).
- **Regulatory Compliance:** Maintain audit logs per exchange requirements; the PostgreSQL trail satisfies this.

By following this blueprint, eqats can leverage ShortCircuit’s battle‑tested market‑data engine, disciplined signal‑generation pipeline, and robust risk controls while preserving its own modular architecture.
