# 📐 EQATS v5.0 SYSTEM ARCHITECTURE GUIDE

## Overview
The Elite Quantum Autonomous Trading System (EQATS v5.0) is built as a highly modular, event-driven, multi-threaded, and multi-processed quantitative trading infrastructure.

## System Layers

### 1. Ingestion Layer (`connector.py`, `symbol_mapper.py`, `universal_broker_adapter.py`)
- Interfaces with MetaTrader 5 terminal native APIs, FIX 4.4 LP sockets, REST/WebSocket interfaces, and CCXT crypto exchanges.
- Master Symbology translation layer normalizes symbol naming across brokers (e.g. `EURUSD.raw` -> `EUR_USD`).

### 2. Microstructure & Feature Engineering Layer (`indicators.py`, `smc_ict_engine.py`, `order_flow_imbalance.py`)
- Computes real-time technical indicators (EMA, ATR, RSI, MACD, Bollinger Bands).
- Maintains active $O(1)$ ring-buffer cache for Smart Money Concepts Fair Value Gaps (FVG).
- Calculates Volume Synchronized Probability of Toxicity (VPIN) and order book delta.

### 3. Strategy Brain & Multiprocessing Layer (`brain.py`, `brain_agents_orchestrator.py`, `predictive_brain.py`)
- `brain_agents_orchestrator.py`: Concurrently executes strategy agents (Scalper, SMC, Trend, Mean Reversion) across isolated CPU process workers (`ProcessPoolExecutor`).
- `predictive_brain.py`: Batch multi-symbol inference via `ThreadPoolExecutor` with EWMA and Holt-Winters statistical forecasting fallback.

### 4. Constitution & Risk Layer (`eqats_planes.py`, `release_gates.py`)
- Validates 12 System Execution Planes and 15 Safety Invariants (`INV-001` to `INV-015`).
- Enforces Spread Volatility Spike Breaker, Symbol Loss Protection Gate, and Correlation Guard.

### 5. Persistence Layer (`database.py`, `database_infrastructure.py`)
- Managed SQLite persistence with WAL mode (`PRAGMA journal_mode=WAL;`), busy timeouts, auto-checkpoints, and exponential backoff retry logic (`_execute_with_retry`).

### 6. Terminal User Interface (`gui.py`)
- Professional Institutional-style desktop application featuring 33+ specialized terminal sheets (`MAIN`, `DOM`, `SESS`, `CHART`, `BACKTEST`, `PORT`, `RISK`, etc.).
- Multi-monitor detachable floating panels (`tk.Toplevel`).
