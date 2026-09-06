# Integration Blueprint: rscreener → eqats

## Overview
rscreener is a zero-cost fundamentals screener for NSE/BSE equities. Its core strength is a nightly-driven data pipeline that pulls data from free sources (NSE, BSE, Yahoo Finance via yfinance), stores it in a rich SQLite schema, runs publish-guard quality checks, and exports static JSON for a Next.js frontend. While rscreener does not generate trading signals or manage risk, its data engine and validation machinery can be directly repurposed to feed eqats's strategy research and execution layers.

## Data Engine Integration
1. **Unified Ingestion Pipeline**
   - Adopt the pipeline/ folder structure: separate fetchers for universe, fundamentals, prices, results history, shareholding, corporate actions, and documents.
   - Replace source-specific calls with eqats's preferred providers (e.g., NSE/BSE APIs, Polygon, Tiingo) while keeping the same Python script signatures.
   - Schedule the pipeline via GitHub Actions (or eqats's CI) using the nightly.yml as a template: restore a released DB asset, run fetchers, run guards, rebuild artifacts, and push the updated DB back as a release.

2. **Storage Layer**
   - Reuse the SQLite schema (data/rscreener.db) as a local cache or development sandbox. The tables (universe, fundamentals, statements, results_history, prices, shareholding, corporate_actions, documents, filing_dates, *_fetch_log) map cleanly onto eqats's canonical data model.
   - For production, mirror the schema into eqats's preferred warehouse (PostgreSQL or ClickHouse) by exporting each table after the nightly run.

3. **Export Artifacts**
   - Keep export_json.py to produce data.json (screener-wide snapshot) and index.json (search index) for fast UI look-ups.
   - Keep export_company_json.py to generate per-company JSON files (companies/<SYM>.json) that eqats's microservices can consume directly without hitting the DB.

4. **Publish Guards**
   - Integrate the four guard scripts (check_prices.py, check_sources.py, check_depth.py, scorecard.py) into eqats's pre-deployment workflow.
   - Configure tolerances to match eqats's data-quality SLAs; guards will block deployment if, for example, price staleness exceeds thresholds or fundamental-source divergences appear.
   - Extend scorecard.py to emit metrics (completeness, correctness, freshness, depth) to eqats's monitoring dashboard.

## Signal & Execution Logic
- rscreener does not contain signal generation or order-execution code. Consequently, there are no direct components to reuse in this domain. eqats should continue to develop its own strategy engines, signal calculators, and execution adapters, using the cleaned data provided by the integrated pipeline.

## Risk Engineering
- Likewise, rscreener lacks risk-limit, position-sizing, or risk-monitoring modules. No direct risk-engineering assets can be transplanted. eqats can, however, leverage the pipeline's data-quality guarantees (via the guards) as a foundational input to its risk models, ensuring that risk calculations are built on verified, fresh fundamentals and price histories.

## Operational Benefits
- Zero-cost data sourcing – reuse the same free providers to keep operating expenses low.
- Nightly refresh with automatic rollback – the GitHub Actions workflow stores the DB as a release asset, enabling instant rollback if a guard fails.
- Static-site fallback – the exported JSON can serve as a read-only API for eqats's frontend or microservices, reducing DB load during market hours.
- Extensible guard framework – adding new quality checks (e.g., alternate-data consistency) follows the existing pattern.

## Next Steps for eqats
1. Fork the pipeline/ directory and adapt fetchers to eqats's data contracts.
2. Mirror the SQLite schema into eqats's warehouse, preserving table names and column meanings.
3. Insert the guard scripts into eqats's CI/CD pipeline, configuring alerting on failures.
4. Schedule the nightly workflow (or equivalent) to rebuild and publish the data assets.
5. Use the exported JSON files as the primary data source for eqats's research notebooks and live trading gateways, falling back to the warehouse for deep historical queries.

By plugging rscreener's battle-tested data engine into eqats, the team gains a reliable, audited fundamentals and price feed without building the ingestion infrastructure from scratch, allowing more focus on signal generation, execution, and risk management.