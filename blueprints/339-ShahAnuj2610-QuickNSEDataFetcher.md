# Integration Blueprint for QuickNSEDataFetcher into eqats

## Overview
The QuickNSEDataFetcher repository provides an automated pipeline for fetching daily NSE equity data using the jugaad_data library. This blueprint outlines how to integrate its core data‑fetching capability into the eqats quantitative trading platform (Rust core with Python/PyO3 bindings).

## Data Engine Integration
- **Feature**: NSE data fetcher (jugaad_data.nse.symbol_history).
- **Integration Point**: A PyO3‑exported Rust function fetch_nse_data that wraps the Python call and returns a pandas DataFrame.
- **Location**: src/data/nse_fetcher.rs (see integration code).
- **Data Flow**: Rust (eqats) → PyO3 module → Python jugaad_data → NSE API → DataFrame → back to Rust/Python consumers.

## Signal & Execution Logic
- No signal generation or execution logic is present in the source repository; this domain remains unchanged in eqats.

## Risk Engineering
- No risk‑management features are present; this domain remains unchanged.

## Implementation Plan
1. Add the PyO3 module nse_fetcher to the eqats Rust crate.
2. Expose the function via the existing Python bindings so strategies can call eqats.data.nse.fetch_nse_data(symbol, start, end).
3. Update CI (GitHub Actions) to build and test the new Rust extension.
4. Write unit tests (as shown) and integration tests using a mock NSE response if needed.

## Testing
- Unit test included in the Rust module verifies that a call returns a non‑null DataFrame.
- Additional tests can be added in the eqats test suite to validate data schema and handling of missing symbols.

## Deployment
- The compiled PyO3 extension will be distributed as part of the eqats Python package.
- No changes to the existing GitHub Actions workflow are required beyond adding the Rust build step.

## Conclusion
By wrapping the jugaad_data NSE fetcher in a safe, typed Rust/PyO3 layer, eqats gains reliable, low‑latency access to Indian equity data while preserving the flexibility of Python‑based strategy development.
