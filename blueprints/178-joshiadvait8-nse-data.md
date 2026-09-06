# Integration Blueprint for joshiadvait8/nse-data into eqats

## Overview
The `nse-data` repository provides a Python client to fetch live equity derivatives option chain data from the National Stock Exchange (NSE) of India. It exposes functions to retrieve the latest option chain for a given symbol, parse the JSON payload, and return a tidy pandas DataFrame.

## Proposed Integration

### 1. Data Engine Enhancement
- Replace or augment eqats' existing market data feed with the `nse-data` module for Indian equity derivatives.
- Use the provided `get_option_chain(symbol)` function to pull real‑time option chain data during market hours.
- Store the fetched DataFrames in eqats' timeseries database (e.g., InfluxDB or TimescaleDB) under a new measurement `nse_option_chain`.
- Add a scheduled job (cron or Airflow) that runs every 30 seconds to ingest fresh data, ensuring low‑latency updates.
- Optionally persist raw JSON responses to an object store (S3) for auditability.

### 2. Signal & Execution Logic
- The repository does not contain any signal generation or order execution logic; therefore no direct integration is possible.
- However, the enriched option chain data can be used as input for existing eqats strategies (e.g., volatility skew, put‑call ratio, gamma exposure).
- Develop new signal modules within eqats that consume the `nse_option_chain` table to compute indicators such as IV skew, OI change, and PCR.

### 3. Risk Engineering
- No risk‑specific features are present in `nse-data`.
- Risk limits and position sizing should continue to be handled by eqats' existing risk engine.
- The option chain data can be fed into risk calculations (e.g., margin requirements, portfolio Greeks) by extending the risk engine to query the new data source.

## Implementation Steps
1. Add `nse-data` as a dependency in `requirements.txt` (or pip install from GitHub).
2. Create a wrapper module `eqats/data_sources/nse_option_chain.py` that calls the library’s API and returns a standardized DataFrame schema.
3. Update the data ingestion DAG to include a new task that runs the wrapper and writes to the storage backend.
4. Implement unit tests using mock responses to ensure robustness against API changes.
5. Document the new data source in eqats’ data catalog and update any relevant configuration files.

## Expected Benefits
- Direct access to live NSE option chain improves the fidelity of Indian‑market‑focused quantitative models.
- Reduces reliance on third‑party vendors for this specific data stream.
- Enables rapid prototyping of volatility‑based and order‑flow signals specific to NSE derivatives.

## Limitations
- The library provides only raw option chain data; no historical data retrieval is mentioned, so backtesting would require external historical sources.
- No built-in error handling for rate limits; integration should incorporate retry logic and respect NSE’s usage policies.

---
*Integration blueprint authored by quant systems architect.*