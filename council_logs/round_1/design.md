# 🏛️ EAQTS v5.0 ARCHITECTURE & SYSTEM DESIGN SPECIFICATION

**System Name:** Elite Autonomous Quantum Trading System (EAQTS v5.0)
**Author / Lead:** Simon Peter & TSyS Labs
**Role:** DESIGNER
**Document Type:** Technical System Architecture & Multiprocessing Design Specification

---

## 1. SYSTEM OVERVIEW & DESIGN PRINCIPLES

EAQTS v5.0 is an institutional-grade, zero-exception autonomous quantitative trading platform designed for 24x7 unassisted execution across global financial markets (Forex, Metals, Commodities, Crypto, Equities). The system enforces strict decoupling between data ingestion, signal evaluation, constitution risk checking, order slicing, and broker persistence.

### Key Design Invariants:
1. **Decoupled Strategy Execution**: Strategy brains evaluate alpha signals in isolated parallel process pools (`ProcessPoolExecutor`) without blocking market data ingestion.
2. **Deterministic Risk Protection**: Every order pass must satisfy 12 System Execution Planes and 15 System Safety Invariants (`INV-001` through `INV-015`) prior to transmission to the broker.
3. **Resilient Data Persistence**: Database operations use SQLite Write-Ahead Logging (`WAL`) mode with automatic exponential retries (`_execute_with_retry`) to eliminate lock contention under high tick frequency.
4. **Cross-Platform Connectivity**: The `UniversalBrokerGateway` seamlessly abstracts MT5 Native, FIX 4.4, REST/WebSocket, IBKR, cTrader, CCXT, and Simulation protocols.

---

## 2. HIGH-LEVEL ARCHITECTURE FLOW DIAGRAM

```
===================================================================================
                       MARKET DATA & INGESTION LAYER
  +--------------------+   +-------------------+   +--------------------+
  |  MT5 Terminal EA   |   |  FIX 4.4 Protocol |   | REST / WS / CCXT   |
  +---------+----------+   +---------+---------+   +---------+----------+
            |                        |                       |
            +------------------------+-----------------------+
                                     |
                          [UniversalBrokerGateway]
                                     |
                          [Master Symbology Mapper]
=====================================+=============================================
                                     |
                                     v
===================================================================================
                       FEATURE & MICROSTRUCTURE LAYER
  +--------------------+   +-------------------+   +--------------------+
  | Technical Analytics|   | SMC FVG Ring Cache|   | Order Flow Toxicity|
  | (EMA, ATR, RSI)    |   |  (Ring-Buffer O(1))|   | (VPIN, Imbalance)  |
  +---------+----------+   +---------+---------+   +---------+----------+
=====================================+=============================================
                                     |
                                     v
===================================================================================
                 PARALLEL MULTIPROCESSING & PREDICTIVE LAYER
  +-----------------------------------------------------------------------------+
  | Multi-Agent Parallel Orchestrator (ProcessPoolExecutor across CPU cores)   |
  | [Scalper Agent]  [SMC/ICT Agent]  [Trend Agent]  [Mean Reversion Agent]     |
  +----------------------------------+------------------------------------------+
                                     |
  +----------------------------------+------------------------------------------+
  | Multi-Symbol Neural Predictive Brain (ThreadPoolExecutor Inference)         |
  | [TFT/TCN Transformer] [LSTM Ensemble] [EWMA Holt-Winters Fallback]          |
  +-----------------------------------------------------------------------------+
=====================================+=============================================
                                     |
                                     v
===================================================================================
                 SYSTEM CONSTITUTION & RISK PROTECTION LAYER
  +-----------------------------------------------------------------------------+
  | 12 System Execution Planes | 15 Safety Invariants (INV-001..INV-015)        |
  | Spread Volatility Spike Breaker | Correlation Guard | Breakeven Engine      |
  +-----------------------------------------------------------------------------+
=====================================+=============================================
                                     |
                                     v
===================================================================================
                   ORDER MANAGEMENT & PERSISTENCE LAYER
  +----------------------------------+   +--------------------------------------+
  | Execution Slicing Engine         |   | Self-Healing Database Infrastructure |
  | (TWAP / VWAP / Iceberg)          |   | (SQLite WAL Mode + Auto-Checkpoints) |
  +----------------+-----------------+   +------------------+-------------------+
                   |                                        |
                   v                                        v
          [Broker LP Execution]                 [Telemetry & Audit Logging]
===================================================================================
```

---

## 3. MULTIPROCESSING & PARALLEL PIPELINE DESIGN

### 3.1 Multi-Agent Strategy Pool (`brain_agents_orchestrator.py`)
- Evaluates multi-agent trading setups concurrently across isolated CPU process workers using `concurrent.futures.ProcessPoolExecutor`.
- Prevents single-threaded Python GIL bottlenecks during heavy multi-indicator computations across dozens of active symbols.

### 3.2 Parallel Neural Prediction Pipeline (`predictive_brain.py`)
- Executes batch neural network prediction requests for multiple symbols simultaneously via `ThreadPoolExecutor`.
- Implements statistical cold-start fallbacks (EWMA and Holt-Winters exponential smoothing) to guarantee real-time predictions even during model warm-up phases.

### 3.3 Parallel Backtesting Engine (`backtest_engine.py`)
- Distributes parameter grid search tasks across CPU cores using `walk_forward_optimization`, achieving >3x speedup over sequential backtesting.

---

## 4. DATA MODELS & SCHEMA SPECIFICATION

### 4.1 SQLite Database Schema (`scalper_brain.db`)

#### Table: `orders`
```sql
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket INTEGER UNIQUE,
    symbol TEXT NOT NULL,
    order_type TEXT NOT NULL,
    lots REAL NOT NULL,
    open_price REAL NOT NULL,
    close_price REAL DEFAULT 0.0,
    stop_loss REAL DEFAULT 0.0,
    take_profit REAL DEFAULT 0.0,
    profit REAL DEFAULT 0.0,
    status TEXT NOT NULL,
    opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP
);
```

#### Table: `broker_credentials`
```sql
CREATE TABLE IF NOT EXISTS broker_credentials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker_name TEXT NOT NULL,
    account_number TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    server TEXT NOT NULL,
    leverage TEXT DEFAULT '1:100',
    terminal_path TEXT,
    protocol_type TEXT DEFAULT 'MT5',
    api_key TEXT,
    api_secret TEXT,
    rest_url TEXT,
    ws_url TEXT,
    extra_params TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### Table: `users`
```sql
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    pin_hash TEXT,
    role TEXT DEFAULT 'operator',
    mfa_secret TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 5. RISK MANAGEMENT & CIRCUIT BREAKERS

1. **Spread Volatility Spike Breaker**: Automatically rejects incoming buy/sell setups if `current_spread > 2.5 * rolling_20_period_avg_spread`.
2. **Symbol Loss Protection Gate**: Prevents opening new positions on any symbol if existing open trades on that symbol are in floating loss (`profit < 0`).
3. **Breakeven Lock & Trailing Stop Engine**: Automatically moves stop loss to entry price plus spread buffer once floating profit hits 1:1 Risk-Reward or 1.0x ATR distance.
4. **Hard Account Drawdown Kill Switch**: Instantly cancels pending orders and closes all floating positions if equity drawdown exceeds maximum risk thresholds.

---

## 6. OPTIMIZED DIRECTORY STRUCTURE

```
.
├── config.py                         # System configuration parameters
├── main.py                           # Scalper main loop & headless execution manager
├── brain.py                          # Strategy decision brain & signal aggregator
├── brain_agents_orchestrator.py     # Multiprocessing parallel strategy orchestrator
├── predictive_brain.py              # Parallel neural & statistical predictive brain
├── indicators.py                     # Volatility & technical indicator calculations
├── connector.py                      # Universal Broker Adapter & MT5 Connector router
├── database.py                       # High-level database context wrappers
├── database_infrastructure.py        # Database Infrastructure, WAL mode & migrations v1-v7
├── eaqts_planes.py                   # 12 System Execution Planes & Constitution Hierarchy
├── release_gates.py                  # Gate 28 zero-stub audit enforcement
├── gui.py                            # EQATS Quantum Terminal Desktop GUI
├── supervisor_agent.py               # AI supervisory monitoring agent
├── telegram_bot.py                   # Alert dispatcher (Telegram & Discord webhooks)
├── symbol_mapper.py                  # Master Symbology translation adapter
├── ScalperBrainEA.mq5                # MT5 EA Bridge Source
├── institutional_integrations/       # Advanced institutional engine modules
├── docs/                             # System Architecture, Runbook, and Deployment guides
├── council_logs/                     # Council round audit transcripts and JSON logs
└── test_*.py                         # Comprehensive Pytest test suites
```
