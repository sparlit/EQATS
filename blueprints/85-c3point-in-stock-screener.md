# Integration Blueprint for c3point/in-stock-screener into eqats

## Overview
The repo provides Python scripts to ingest AMFI caps, ISIN lists, screener ratios, Morningstar data, dividend/bonus histories, and user plan/demat CSVs, producing reference tables and reports (buy/sale rankings, plan-vs-demat diffs, cap distribution).

## Data Engines
- Build ingestor classes for each source (AMFI, ISIN, screener, Morningstar, dividend/bonus) that read the CSV files and write normalized Parquet/CSV to eqats/data/raw/.
- Implement a scheduler (Airflow/Prefect) to refresh AMFI/ISIN semi-annually and screener/Morningstar daily.
- Join all reference tables on ISIN to create an instrument_reference feature store.
- Add adapters for plan-data and demat-data to bring user weights and holdings into eqats.

## Signal & Execution Logic
- Encapsulate the TBD scoring logic in a SignalGenerator that computes a company price score from fundamentals, moat, dividend yield, and plan weights, outputting buy- and sale-ranked DataFrames.
- Convert plan-data weights into target portfolio weights; compute order deltas versus current demat holdings and feed to eqats' execution adapter.
- Schedule a daily job: refresh data -> generate signals -> build orders -> execute.

## Risk Engineering
- Use plan-report cap-distribution summaries to monitor large/mid/small cap exposure vs policy bands.
- Implement pre-trade weight limits (max per-stock, sector, cap-bucket) derived from plan-data columns.
- Treat demat-plan diff reports as risk signals: large mismatches trigger rebalancing alerts.
- Integrate dividend-income reports for cash-flow forecasting.

## Implementation Steps
1. Copy src/ modules into eqats/contrib/in_stock_screener/.
2. Wrap each shell script in a Python entry-point calling the corresponding ingestor.
3. Add unit tests with sample CSV fixtures.
4. Register new sources in eqats' data_catalog.yaml.
5. Implement TDDSignalGenerator and plug into eqats/signals/.
6. Create risk-check plugins for weight limits and cap-distribution monitoring.
7. Update scheduler to run ingestion, signal generation, and risk checks.
8. Document the integration in eqats' ADRs.