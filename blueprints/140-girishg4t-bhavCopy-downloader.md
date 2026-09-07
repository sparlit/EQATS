# Integration Blueprint for eqats

## Overview
The `bhavCopy-downloader` repository provides a reliable, free source for NSE and BSE end‑of‑day (EOD) market data, including options chains. Its core strength lies in the data ingestion pipeline: configurable index definitions, automated downloads from the exchanges, and local CSV storage backed by a public API. This blueprint outlines how eqats can leverage these capabilities to enrich its data engine layer while noting that the repository does not contain signal generation, order execution, or risk‑management logic.

---

## 1. Data Engines Integration

### 1.1 Ingestion Pipeline
- **Scheduled Downloads**: Use the existing `npm start` (or a lightweight wrapper) as a cron job or Airflow DAG to pull the latest EOD CSV files for desired indexes (e.g., NIFTY50, BSE100) and options chains.
- **Index Configurability**: Reuse the `NSEIndexConfigs` and `BSEIndexConfigs` JSON files to define the constituent symbols for each index. eqats can read these configs directly to build dynamic universes without hard‑coding tickers.
- **Historical Backfill**: The tool’s ability to request arbitrary dates enables eqats to perform historical data backfills for strategy research or model training.
- **Options Data**: Activate the OPTIONS download feature to populate an options‑chain dataset (strikes, expiries, IV, etc.) for volatility‑based signals.

### 1.2 Storage & Format
- **Landing Zone**: Store the raw CSV downloads in eqats’ data lake under `raw/bhavcopy/<exchange>/<date>/`.
- **Normalization**: Implement a lightweight ETL step (Python/Polars) to read the CSVs, standardize column names (e.g., `symbol`, `date`, `open`, `high`, `low`, `close`, `volume`, `delivered_qty`, `delivered_qty_pct`), and convert to Parquet for efficient querying.
- **Metadata**: Preserve the source index name and download timestamp as partition columns or metadata fields to support traceability.

### 1.3 API Consumption (Alternative)
- Instead of running the downloader locally, eqats can call the public endpoint `https://bhavcopy-backend.fly.dev/` with query parameters for exchange, index, and date to stream CSV directly into processing jobs, reducing infrastructure overhead.

### 1.4 Benefits
- **Authenticity**: Data is fetched straight from NSE/BSE servers, ensuring accuracy.
- **Cost‑Effective**: Free service eliminates vendor data fees for EOD Indian equities.
- **Flexibility**: Custom index definitions allow eqats to create sector‑specific or strategy‑specific universes on the fly.

---

## 2. Signal & Execution Logic

The `bhavCopy-downloader` repository does **not** contain any components for signal generation, strategy backtesting, or order execution. Consequently, there are no direct features to map into eqats’ Signal & Execution Logic domain. If eqats requires such capabilities, they must be sourced from other modules or developed in-house.

---

## 3. Risk Engineering

Similarly, the project lacks risk‑limit checks, position‑sizing algorithms, or real‑time risk monitoring tools. No risk‑engineering features are available for integration.

---

## 4. Implementation Steps for eqats

1. **Clone & Configure**
   ```bash
   git clone https://github.com/girishg4t/bhavCopy-downloader.git
   cd bhavcopy-downloader
   # Adjust NSEIndexConfigs/BSEIndexConfigs as needed
   ```
2. **Create a Scheduler** (e.g., using cron, Airflow, or Prefect) to run:
   ```bash
   npm start -- --exchange NSE --index NIFTY50 --date $(date -d yesterday +%d-%m-%Y)
   ```
   (Adapt flags based on the tool’s CLI; if none exist, modify the frontend to accept command‑line arguments or call the public API directly.)
3. **Ingest CSVs** into eqats’ data lake with a simple Python script that:
   - Reads the CSV.
   - Adds metadata (source, index, download timestamp).
   - Writes to Parquet partitioned by `exchange`, `index`, `date`.
4. **Optionally**, set up a downstream dbt or SQL model to create cleaned views (`eqats.market_data.nse_eod`, `eqats.market_data.bse_options`).
5. **Monitor** the ingestion job for failures and set up alerts (e.g., via eqats’ existing observability stack).

---

## 5. Conclusion

By integrating the data‑download capabilities of `bhavCopy-downloader`, eqats can obtain high‑quality, cost‑free EOD Indian equity and options data, enriching its historical dataset and enabling more robust strategy research. The repository’s lack of signal, execution, and risk features means those domains must be addressed elsewhere within eqats’ architecture.
