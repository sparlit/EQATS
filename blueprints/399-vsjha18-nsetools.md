# NSETools Integration Blueprint for eqats

## Overview
Integrate the NSETools Python library into the eqats quantitative trading stack via PyO3, enabling Rust core components to access real‑time NSE data (stock quotes, indices, derivatives) while preserving the existing Python ecosystem.

## Domain Mapping

### Data Engines
- Stock codes retrieval
- Stock quote (price & depth) retrieval
- Index quotes and lists
- Derivatives (future) quotes
- Constituent stocks of an index
- 52‑week high/low lists

### Signal & Execution Logic
- Top gainers / losers
- Advances vs declines
- 52‑week high/low signals
- Index‑level trend extraction
- Real‑time price feeds for strategy execution

### Risk Engineering
- Price band (lower/upper CP) monitoring
- Volatility proxies via intra‑day high/low
- Exposure limits based on index constituent data

## Integration Approach
1. Create a new PyO3 crate eqats_nse.
2.
2. Expose the most valuable feature – Nse.get_quote – as a Rust‑callable Python function.
3. Re‑use the existing nsetools library via Python import inside the Rust module, avoiding re‑implementation of HTTP handling.
4. Provide thin wrappers for additional endpoints as needed.
5. Ensure error propagation from Python to Rust using PyResult.
6. Add unit tests that call the wrapper with a known symbol (e.g., "INFY") and validate the returned dictionary.

## Build & Usage
- Add eqats_nse = { path = "crates/eqats_nse" } to the workspace Cargo.toml.
- In Python: import eqats_nse; data = eqats_nse.get_quote("INFY").
- Rust components can call the same function through the PyO3 FFI.

## Safety & Compliance
- The wrapper does not alter data retrieval; it respects the NSETools disclaimer.
- All network calls remain within the original Python library, ensuring compliance with NSE’s public‑data usage policies.