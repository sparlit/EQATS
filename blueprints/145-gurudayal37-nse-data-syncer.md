# Integration Blueprint for nse-data-syncer into eqats

## Overview
The `nse-data-syncer` repository provides a robust Python‑based pipeline for fetching daily OHLCV data for NSE stocks from Yahoo Finance and persisting it to a PostgreSQL database. Its incremental sync, handling of the `.NS` ticker suffix, and automated GitHub Actions schedule make it a valuable data‑engine component for eqats.

## Proposed Integration

### 1. Data Engine Enhancement
- Replace / augment existing market‑data ingestion with the syncer’s `app.main` module.
- Configure the syncer to write into eqats’ market‑data schema (e.g., `market_data.ohlcv`).
- Leverage its incremental‑sync logic to avoid re‑downloading existing bars, reducing API calls and latency.
- Use the `--symbols` flag to allow eqats to request data for a custom watchlist (e.g., liquid NSE futures/equities).
- The `--dry-run` flag can be used in unit tests to validate fetch logic without touching the DB.

### 2. Storage & Schema Mapping
- Map the syncer’s output columns (`date`, `open`, `high`, `low`, `close`, `volume`) to eqats’ canonical OHLCV table.
- Ensure the PostgreSQL connection string is supplied via eqats’ secret management (e.g., `DATABASE_URL` secret in GitHub Actions or Vault).
- If eqats uses TimescaleDB, the syncer’s raw inserts can be directed to a hypertable for time‑series optimizations.

### 3. Automation & Deployment
- Incorporate the existing GitHub Actions workflow (`Daily Stock Data Sync`) into eqats’ CI/CD pipeline.
- Adjust the cron to match eqats’ data‑refresh schedule (e.g., after market close at 15:30 IST).
- Store the `DATABASE_URL` secret in eqats’ repository secrets, mirroring the syncer’s approach.
- Add a workflow step that runs DB migrations or schema checks before the sync.

### 4. Extensibility
- Wrap the syncer’s core functions (`fetch_symbol_data`, `upsert_ohlcv`) into a reusable Python package that eqats can import as a dependency.
- This enables eqats to call the fetcher on‑demand (e.g., during strategy warm‑up or back‑fill).
- Add type hints and unit tests to align with eqats’ code‑quality standards.

### 5. Limitations & Next Steps
- The syncer currently lacks signal generation, execution, or risk‑management features; those remain the responsibility of eqats’ signal & execution and risk‑engineering modules.
- Future work could extend the syncer to adjust for corporate actions (splits, bonuses) or to fetch additional data feeds (e.g., index constituents, fundamentals).

## Conclusion
By integrating `nse-data-syncer` as a dedicated market‑data ingestion service, eqats gains a reliable, incremental, and automated pipeline for NSE OHLCV data, freeing up internal resources to focus on strategy development, execution, and risk management.
