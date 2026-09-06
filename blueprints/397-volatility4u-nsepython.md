# Integration Blueprint for nsepython into eqats

## Overview
The nsepython library provides convenient access to National Stock Exchange (NSE) India market data, including equity quotes, historical prices, option chains, indices, and derivatives. Integrating this library into eqats will enhance the **Data Engines** domain by providing a reliable Python‑sourced data feed that can be called from Rust via PyO3 bindings.

## Components
1. **Rust PyO3 Module** (nse_bindings.rs) – exposes functions:
   - get_quote(symbol: &str) -> PyResult<f64>
   - get_historical(symbol: &str, start: &str, end: &str) -> PyResult<Vec<f64>>
   - get_option_chain(symbol: &str) -> PyResult<String> (returns JSON)
   - get_index_data(index: &str) -> PyResult<f64>
2. **Python side** – relies on the existing nsepython package; no modifications needed.
3. **Error handling** – PyO3 propagates Python exceptions as Rust Err.

## Data Flow
- Eqats Rust core calls the exposed PyO3 functions.
- Each function imports nsepython internally and invokes the appropriate function.
- Returned data is converted to Rust types (f64, Vec<f64>, String) and passed back to the caller.
- Optionally, the String JSON can be deserialized by eqats' data processing pipeline.

## Testing
- Unit tests use pyo3::prepare_freethreaded_python to initialize the interpreter and call the bindings, asserting non‑empty results for known symbols (e.g., "RELIANCE").

## Benefits
- Immediate access to live NSE data without building custom scrapers.
- Leverages mature, community‑maintained nsepython.
- Keeps eqats core language‑agnostic; the binding layer isolates Python dependency.
