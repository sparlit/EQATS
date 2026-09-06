# Integration Blueprint: Raderbot Position Management into eqats

## Overview
This document describes the integration of the core position‑management feature from the Raderbot Rust trading bot into the eqats quantitative trading platform. The goal is to expose Raderbot’s open/close position logic and account snapshot functionality as a PyO3‑enabled Rust library that can be used directly from Python strategies within eqats.

## Domain Mapping
- **Data Engines**: Historical kline and trade data loaders (BootstrapKlineData, BootstrapTradeData) remain outside this integration; eqats will continue to supply market data via its own data engine.
- **Signal & Execution Logic**: The position‑management API (open_position, close_position, get_account_snapshot) maps directly to eqats’ execution layer.
- **Risk Engineering**: Stop‑loss handling and robust error reporting from Raderbot are retained as risk controls.

## Integration Points
1. **Rust Library (eqats/src/raderbot_position.rs)** – Implements PositionManager with PyO3 bindings.
2. **Python Wrapper** – eqats can import raderbot_position and instantiate PositionManager.
3. **Configuration** – No external configuration required for the mock implementation; real‑world deployment would replace the placeholder entry price with a live price feed from eqats’ data engine.
4. **Testing** – Unit test demonstrates opening, snapshotting, and closing a position using the Python‑interop layer.

## Data Flow
- eqats strategy → Python call → raderbot_position::PositionManager::open_position → returns Position struct.
- Position data can be stored in eqats’ persistence layer or used for risk checks.
- To close, strategy calls close_position with the position ID.
- Periodic snapshots are obtained via get_account_snapshot.

## Safety & Reliability
- The implementation mirrors Raderbot’s stop‑loss field and error handling (via PyResult).
- All FFI boundaries are caught and translated into Python exceptions.
- The module is thread‑safe when used with the PyO3 freethreaded feature (not shown).

## Future Work
- Replace placeholder entry price with real‑time price feed from eqats’ data engine.
- Integrate with eqats’ order execution adapter to send actual orders to exchanges.
- Add leverage and margin validation against account equity.