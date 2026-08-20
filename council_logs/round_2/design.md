# EAQTS v5.0 Architecture & Optimization Design Specification - Round 2

## 1. Executive Summary
Round 2 focuses on hardening runtime concurrency and database durability under sustained 24x7 VPS high-frequency trading sessions.

## 2. Key Architectural Optimizations

### 2.1 Multiprocessing Process Fork Safety
- **Issue**: Standard `multiprocessing.ProcessPoolExecutor` or process forks in multi-threaded application environments (e.g. Pytest or GUI runners) issue deprecation warnings in Python 3.12 (`DeprecationWarning: This process is multi-threaded, use of fork() may lead to deadlocks in the child`).
- **Design Solution**:
  - Use explicit multiprocessing context `multiprocessing.get_context('spawn')` when instantiating process pools for strategy calculations.
  - Fallback cleanly to thread pools if process creation is unavailable or constrained.

### 2.2 Database Infrastructure WAL Auto-Checkpointing
- **Issue**: High tick rate writing to SQLite WAL files (`.db-wal`) can cause WAL growth if checkpoints are delayed during non-stop market loops.
- **Design Solution**:
  - Integrate an explicit WAL auto-checkpointing monitor within `DatabaseInfrastructure`.
  - Perform passive WAL checkpoints (`PRAGMA wal_checkpoint(PASSIVE)`) every 1,000 tick writes or 5-minute interval.
  - Prevent lock contention while keeping WAL size bounded under < 5MB.

## 3. High-Frequency Execution Flow Diagram

```
[ Market Ticks / Order Flow ]
           │
           ▼
[ DatabaseInfrastructure ] ────► (Automated PRAGMA wal_checkpoint(PASSIVE))
           │
           ▼
[ Multi-Agent Orchestrator ] ───► (mp.get_context('spawn') Process Worker Pool)
           │
           ▼
[ Autonomous Execution Engine ]
```
