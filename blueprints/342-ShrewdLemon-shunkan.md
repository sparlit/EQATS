# Integration Blueprint: Shunkan Exchange-Priced Margin into eqats

## Overview
Integrate Shunkan's exchange-priced margin calculation (which uses official exchange margin formulas and never fabricates numbers) into the eqats risk engineering subsystem.

## Components
- **Data Engine**: Shunkan's Kite Connect client fetches real option chain and instrument data.
- **Risk Engine**: Shunkan's margin calculator computes SPAN-style margin per leg using exchange-provided parameters.
- **Execution Layer**: eqats will call the margin calculator via PyO3 bindings to adjust position sizing and risk limits.

## Steps
1. Expose Shunkan's margin logic as a Rust library with a clear API (calculate_margin(leg_params) -> Option<f64>).
2. Generate PyO3 bindings so the eqats Python layer can invoke the Rust function.
3. In eqats' risk engine, replace the placeholder margin model with a call to the Shunkan-derived function, propagating None when data missing (respecting no-fabricated-numbers rule).
4. Add unit tests that compare outputs against known exchange margin samples.
5. Ensure error handling surfaces missing data sources to the UI, mirroring Shunkan's transparent failure reporting.

## Safety Guarantees
- No synthetic fallback: if margin data unavailable, return None and log missing source.
- Credentials remain local: reuse Shunkan's credential storage (~/.shunkan/credentials.json).
- Thread-safe: Rust core ensures no data races.

## Files
- eqats/risk_engineering/src/shunkan_margin.rs – Rust implementation.
- eqats/risk_engineering/src/lib.rs – PyO3 module definition.
- eqats/python/eqats/risk/margin.py – Python wrapper