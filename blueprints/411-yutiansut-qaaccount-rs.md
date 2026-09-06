# Integration Blueprint

## Overview
Integrate the high‑performance indicator engine from qaaccount-rs into eqats as a PyO3 extension.

## Goals
- Expose a low‑latency moving‑average indicator to Python strategies.
- Leverage Rust speed for data‑engine calculations.
- Maintain compatibility with existing eqats Python workflow.

## Components
1. **Rust core** (eqats/src/indicators/rs_sma.rs) – implements SMA and PyO3 bindings.
2. **Python wrapper** (eqats/indicators/__init__.py) – imports the compiled module.
3. **Build configuration** – add pyo3 dependency and cffi‑like setup in Cargo.toml and maturin build.

## Data Flow
Python strategy → calls eqats_rs.sma(values, window) → Rust computes SMA → returns Vec<f64> to Python.

## Testing
- Unit test in Rust verifies SMA correctness.
- Python‑side import test ensures the module loads.

## Risk & Compliance
The module does not alter risk logic; it purely provides a fast data‑engine primitive.

## Future Work
Wrap additional indicators (EMA, RSI) and expose account‑level backtest primitives.