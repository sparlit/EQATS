# Integration Blueprint: stocks-dashboard → eqats

## Overview
The stocks-dashboard repository provides a robust, automated pipeline for collecting and publishing NSE/BSE and mutual-fund market data. It uses GitHub Actions to refresh data daily at 8 PM IST, stores the results in the docs/ folder, and serves them via GitHub Pages. A status page monitors pipeline health.

## Data Engines – What to Reuse in eqats
1. **Scheduled Data Ingestion Workflow**
   - Copy the GitHub Actions workflow (.github/workflows/data-refresh.yml) into eqats.
   - Adjust the cron to match eqats' desired frequency (e.g., every 15 min during market hours).
   - Replace the NSE/BSE fetch calls with eqats' preferred data providers (e.g., Polygon, Tiingo, or NSE API) while keeping the same step structure: fetch -> validate -> store.
2. **Data Runbook (scripts/DATA_RUNBOOK.md)**
   - Adopt the runbook as a template for eqats' own data-engine SOP.
   - Populate sections for fetching, refreshing, backfilling, building, and deploying with eqats-specific commands (e.g., python -m eqats.ingest, python -m eqats.feature_store).
   - Include the "gotchas" section to capture lessons learned from the stocks-dashboard pipeline.
3. **Storage & Publication Pattern**
   - Keep the raw/processed data as version-controlled artifacts (CSV/Parquet) in a dedicated data/ branch or as GitHub-Artifacts.
   - If a public data feed is desired, mirror the GitHub Pages approach: publish processed datasets to a gh-pages branch and serve via a lightweight dashboard (e.g., Streamlit, FastAPI) for internal monitoring.
4. **Health Monitoring**
   - Replicate the status.html page: a simple JSON endpoint that reports last run timestamp, success/failure, and data-freshness metrics.
   - Hook this into eqats' observability stack (Prometheus/Grafana) or keep as a lightweight status page for quick checks.

## Signal & Execution Logic
The stocks-dashboard repo does not contain any signal generation, strategy backtesting, or order-execution components. Consequently, there are no direct features to map into eqats' Signal & Execution Logic domain. If eqats wishes to add a visualizer for signals, the dashboard's front-end (HTML/CSS/JS in docs/) could be repurposed as a starting point, but the core logic would need to be built from scratch.

## Risk Engineering
Similarly, the repository lacks risk-limit checks, position-sizing algorithms, or real-time risk monitoring. No risk-engineering features are available for direct integration. Eqats can, however, leverage the same data-pipeline foundation (ingestion, storage, health checks) to feed its own risk-engine modules.

## Integration Steps Summary
1. Fork or clone stocks-dashboard.
2. Extract the GitHub Actions workflow and adapt it to eqats' data sources.
3. Copy scripts/DATA_RUNBOOK.md and customize it for eqats' pipelines.
4. (Optional) Re-use the static-site front-end as a baseline for an internal data-visibility tool.
5. Implement eqats-specific signal, execution, and risk modules on top of the reliable data foundation established by the adapted pipeline.

---
*This blueprint focuses on the concrete, reusable assets found in stocks-dashboard (data ingestion automation, documentation, and health monitoring) and explicitly notes the absence of signal/execution and risk-engineering components.*