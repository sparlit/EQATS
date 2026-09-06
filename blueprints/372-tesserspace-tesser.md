# Tesser Integration Blueprint for eqats

## Overview
This document outlines the integration of the **tesser-indicators** crate into the eqats quantitative trading platform. The goal is to expose Tesser's high‑precision, zero‑cost technical indicators as a native Python extension via PyO3, enabling strategy developers to use Rust‑level performance directly from Python.

## Domain Classification
- **Data Engines** – (none directly contributed by this integration)
- **Signal & Execution Logic** – Technical indicators (SMA, EMA, RSI, …) implemented in tesser-indicators are now accessible as PyO3 classes.
- **Risk Engineering** – (none directly contributed)

## Integration Points
1. **Rust Library** – src/tesser_indicators.rs defines a PyO3 module tesser_indicators containing the SimpleSMA class as a proof‑of‑concept. Additional indicators can be added following the same pattern.
2. **Python Bindings** – The module is built with maturin or setuptools-rust and imported in Python as import tesser_indicators.
3. **Usage Example** – Strategies can instantiate SimpleSMA(period) and call update(price) to receive the latest SMA value.

## Build & Test
- Ensure Rust toolchain and Python development headers are installed.
- Run maturin develop to build and install the module into the active Python environment.
- Execute the unit test suite with cargo test to verify correctness of the Rust core.
- Run the provided Python‑side test in tests/test_indicators.py to confirm the PyO3 bridge works.

## Future Work
- Wrap the full tesser-indicators crate (EMA, RSI, Bollinger Bands, etc.) using the same PyO3 pattern.
- Expose the event‑bus (tesser-events) for low‑latency signal propagation.
- Provide optional NumPy‑array based batch updates for vectorised workflows.