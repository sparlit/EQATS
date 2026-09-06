# Integration Blueprint for NSE Option Chain Analyzer into eqats

## Overview
Integrate the real-time option chain data fetching and analysis module from the Python-NSE-Option-Chain-Analyzer into the eqats trading system as a Rust data engine exposed via PyO3 bindings.

## Components
- **Rust Library (src/nse_option_chain.rs)**: Implements HTTP client to NSE option chain endpoint, parses JSON, computes key metrics (OI change, PCR, ITM flags).
- **Python Bindings**: Expose get_option_chain(symbol: str) -> List[Dict] and compute_metrics(data) -> Dict for use in eqats' Python strategies.
- **Configuration**: Reuse config persistence for refresh interval, symbols, etc.
- **Testing**: Unit tests with mocked HTTP responses.

## Data Flow
1. eqats Python layer calls the PyO3 function with symbol (e.g., "NIFTY").
2. Rust fetches latest option chain JSON from NSE.
3. Data is transformed into a vector of records with strike, call/put OI, volume, IV, etc.
4. Optional metrics (PCR, max pain, trend) are computed and returned.
5. Python strategy consumes the data for signal generation or risk checks.

## Safety & Reliability
- Retry mechanism on network failures.
- Stale data detection (>5 min) returns error.
- Graceful handling of missing fields (default to 0).
- No GUI dependencies; suitable for headless operation.

## Future Extensions
- Add websocket streaming if NSE provides.
- Incorporate additional technical indicators (e.g., IV skew).
- Export to eqats' internal time-series database.
