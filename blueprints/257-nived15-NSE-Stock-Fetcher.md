# Integration Blueprint for NSE Stock Fetcher into eqats

## Overview
The NSE Stock Fetcher provides robust bulk download of NSE equity EOD OHLCV data via yfinance, with incremental updates, retry logic, and Parquet/CSV support. This blueprint outlines how to incorporate its capabilities as a data engine within the eqats quantitative trading platform.

## Data Engine Integration
- **Historical Data Ingestion**: Wrap the downloader's core logic into a Python module (`eqats.data.nse_fetcher`) exposing functions like `fetch_nse_universe(years=20, suffix='.NS', series=['EQ','BE'])` and `update_symbols(symbols, outdir)`.
- **Incremental Updates**: Leverage the `--update` flag to append only new trading days, ensuring eqats' data lake stays current without re-downloading existing history.
- **Resumable & Fault‑Tolerant**: Use the built‑in batching, exponential backoff, and `failures.csv` logging to create a reliable ingestion pipeline that can be retried after transient Yahoo Finance throttling.
- **Storage Format**: Support both CSV and Parquet; recommend Parquet for columnar efficiency in eqats' analytics workloads. The `--format parquet` option maps directly to eqats' preferred storage layer.
- **Combined Dataset**: The `--combine` flag produces a long‑format file (`nse_all_eod.parquet`) suitable for factor‑construction workflows; eqats can consume this as a unified panel.
- **Symbol Universe Management**: Reuse the `--symbols-file` and `--series` options to allow eqats to define custom watchlists or sector filters while falling back to the official NSE list when needed.
- **Rate‑Limit Handling**: The downloader’s `batch-size`, `sleep`, and `retries` parameters provide a configurable throttling mechanism that can be tuned to eqats’ SLA with Yahoo Finance.

## Signal & Execution Logic
The NSE Stock Fetcher does not generate trading signals or execute orders. No direct integration points exist in this domain; eqats should continue to rely on its own signal generators and execution adapters.

## Risk Engineering
Similarly, the repository contains no risk‑limit, position‑sizing, or monitoring features. Risk controls remain the responsibility of eqats’ risk engine.

## Implementation Steps
1. **Extract Library Code**: Move the download logic from `nse_eod_downloader.py` into an importable package (e.g., `eqats/data/nse_fetcher/__init__.py`).
2. **Expose a Clean API**:
   ```python
   def fetch_nse_data(symbols=None, years=20, outdir='./nse_data',
                      format='parquet', update=False, combine=False,
                      batch_size=25, sleep=1.5, retries=3, threads=0):
       ...
   ```
3. **Configure eqats**: Add a configuration block in eqats’ `config.yaml` to set the NSE data directory, preferred format, and update schedule.
4. **Schedule Ingestion**: Use eqats’ existing job scheduler (e.g., Apache Airflow or Prefect) to run the fetch function daily after market close, invoking the update mode.
5. **Validate & Test**: Compare a sample of downloaded Parquet files against known good CSVs; ensure manifest and failure logs are correctly written.
6. **Monitor**: Hook the downloader’s log file (`download.log`) into eqats’ logging infrastructure for observability.

## Benefits
- Immediate access to ~20 years of clean NSE equity EOD data.
- Reduced engineering effort for data maintenance.
- Fault‑tolerant, rate‑limit‑aware downloads that scale to the full NSE universe.
- Seamless storage in Parquet, aligning with eqats’ analytical stack.

## Caveats
- The tool relies on yfinance, which is subject to Yahoo Finance’s terms of service; eqats should review compliance.
- For ultra‑low‑latency tick‑by‑tick data, a different feed would be required; this solution is strictly end‑of‑day.
