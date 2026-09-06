# Integration Blueprint for Vyuha-LOG Charge Calculator into eqats

## Overview
Integrate the exact SEBI/broker charge calculation (0.69%) from Vyuha-LOG as a reusable Rust library with PyO3 bindings for use in eqats' Python strategies.

## Steps
1. Create a new Rust module eqats/src/charges.rs implementing charge calculation.
2. Expose a PyO3 Python module eqats_charges via #[pymodule].
3. Add unit tests in Rust and a Python-side pytest.
4. Update Cargo.toml with pyo3 dependency.
5. Build and publish as part of eqats wheel.

## Usage
python
from eqats_charges import calculate_charges
charge = calculate_charges(trade_value)
