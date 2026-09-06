# Fenix Integration Blueprint for eqats

## Overview
Integrate the Fenix Python broker adapter library into the eqats Rust core via PyO3 bindings, providing a unified broker interface for Indian markets.

## Steps
1. Add PyO3 dependency to eqats' Cargo.toml.
2. Create a new Rust module src/fenix_integration.rs exposing a Python class FenixBroker.
3. Use pyo3::Python::with_gil to import the fenix module and instantiate the desired broker class.
4. Wrapper methods delegate to the underlying broker (authenticate, load tokens, place orders, fetch data).
5. Translate Fenix-specific errors into eqats error types.
6. Enable paper mode by passing a flag to select the paper trading adapter.
7. Write unit tests that initialize the Python interpreter and verify basic calls.
8. Ensure proper GIL handling and avoid blocking the Rust async runtime.
9. Publish the Python module as part of eqats' Python package.

## Safety Considerations
- Rate limiting and secret redaction are inherited from Fenix.
- All calls must acquire the GIL; consider offloading to a threadpool.
- Secrets are never logged; rely on Fenix's automatic redaction.

## Future Work
- Async wrapper using tokio and pyo3-asyncio.
- Expand to support additional exchanges.
- Provide Signal & Execution Logic helpers (e.g., order sizing).
