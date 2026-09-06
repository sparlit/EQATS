# Integration Blueprint for eod2_data into eqats

## Overview
The `eod2_data` repository supplies clean, weekly‑updated End‑of‑Day (EOD) CSV files for NSE equities:
- `daily/` – OHLCV series adjusted for bonuses and splits.
- `delivery/` – daily delivery volumes.

These files can be consumed directly by the **Data Engines** layer of eqats to build a historical market‑data store.

## Data Engine Integration
1. **Ingestion** – Add a lightweight CSV connector in eqats’ data‑pipeline (e.g., using `pandas.read_csv` or Polars) that points to the `daily/` and `delivery/` folders (either via a cloned repo or HTTP raw URLs).
2. **Storage** – Persist the raw CSVs into eqats’ data lake (e.g., Parquet partitioned by date and symbol) preserving the adjustment for corporate actions.
3. **Metadata** – Attach source metadata (NSE, weekly update cadence) to enable data‑versioning and lineage tracking.
4. **Feature Generation** – Use the OHLCV series for technical indicators, volatility estimates, and the delivery data for liquidity‑adjusted signals.

## Signal & Execution Logic
The repository contains no executable logic; therefore, no direct integration points exist for strategy or order‑execution modules. Signals can be derived upstream in eqats using the ingested data.

## Risk Engineering
No risk‑related features are present. Risk controls (position limits, VaR, stress testing) should be applied in eqats’ risk engine after signals are generated, using the same data as any other market‑data source.

## Operational Considerations
- **Update Frequency** – Since data is refreshed weekly, schedule a weekly sync job (e.g., cron or Airflow) to pull the latest CSVs and append to the historical store.
- **Data Quality** – Validate CSV schema (date, open, high, low, close, volume) and check for missing symbols; flag any discrepancies before persisting.
- **Scalability** – The CSV format is straightforward; for large universes consider converting to a columnar format (Parquet) during ingestion to improve query performance.

## Summary
`eod2_data` serves as a reliable, low‑maintenance source of adjusted NSE EOD data. By plugging its CSV outputs into eqats’ data‑engine layer, the strategy and risk modules gain access to high‑quality historical prices and delivery volumes without altering existing codebases.