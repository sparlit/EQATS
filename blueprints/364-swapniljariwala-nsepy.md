# Integration Blueprint for nsepy into eqats

## Overview
Integrate the nsepy Python library as a data engine within the eqats quantitative trading system. This enables Rust core components to fetch Indian market data (equities, indices, derivatives) via PyO3 bindings.

## Components
- **Rust crate**: eqats_nsepy providing PyO3 wrapper.
- **Python dependency**: nsepy (via pip).
- **Exposed API**: get_history(symbol, start, end, index=False, derivatives=False) returning a pandas DataFrame.

## Data Flow
1. Rust code calls the PyO3-exposed function.
2. PyO3 invokes nsepy.get_history, which performs HTTP requests to NSE website.
3. The resulting pandas DataFrame is returned as a PyObject to Rust.
4. Rust can convert the DataFrame to Arrow, Polars, or raw numeric arrays for further processing.

## Usage Example (Rust)
rust
use eqats_nsepy::{get_history, Python};
use chrono::NaiveDate;

let py = Python::acquire_gil().python();
let df = get_history(
    py,
    "SBIN",
    NaiveDate::from_ymd_opt(2015, 1, 1).unwrap(),
    NaiveDate::from_ymd_opt(2015, 1, 10).unwrap(),
    false,
    false,
)?;
let close_series: Vec<f64> = df
    .getattr(py, "Close")?
    .extract(py)?
    .iter()
    .collect();


## Testing
Unit tests are provided that fetch a small sample and verify the DataFrame shape.

## Risk & Signal Considerations
The data engine supplies raw market data; signal generation and risk modules can consume the output directly.
