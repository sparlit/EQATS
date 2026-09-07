# Integration Blueprint for nse-sharia-news-feed into eqats

## Overview
The `nse-sharia-news-feed` repository provides a simple Python script that scrapes news related to NSE Sharia-listed securities and outputs a structured news feed. This can be leveraged as an alternative data source within the eqats platform to enrich signal generation.

## Data Engine Integration
1. **Module Creation**
   - Create a new eqats data engine module `eqats/data_engines/nse_sharia_news.py`.
   - Reuse the existing scraping logic (requests + BeautifulSoup) to fetch news items.
   - Normalize each news item to eqats' canonical news schema: `{timestamp, source, headline, url, symbols[]}`.
   - Persist the normalized news to eqats' raw data lake (e.g., S3 bucket or TimescaleDB) using the existing `eqats.storage` abstraction.
2. **Scheduler**
   - Register the module with eqats' orchestration layer (e.g., Airflow or Prefect) to run at a configurable interval (e.g., every 15 minutes during market hours).
   - Provide a config entry in `eqats/config/data_engines.yaml` to enable/disable and set fetch frequency.
3. **Metadata & Versioning**
   - Tag each ingested batch with a git SHA of the nse-sharia-news-feed source (if vendored) for reproducibility.
   - Add schema validation using `pydantic` to ensure downstream consumers receive valid news records.

## Signal & Execution Logic
- The news feed itself does not generate trading signals. However, once the news data is persisted, eqats signal developers can:
   - Build sentiment‑based features (e.g., VADER sentiment scores) using the `eqats.feature_store`.
   - Create event‑driven signals that trigger when news mentions specific Sharia‑compliant tickers.
   - Combine with price/volume data in the existing signal pipeline.
- No changes to order execution are required; the feed is purely informational.

## Risk Engineering
- The repository does not contain risk‑related logic (position sizing, limits, monitoring).
- Risk controls remain governed by eqats' existing risk engine; the news feed should be treated as non‑market data and excluded from P&L attribution unless explicitly modeled.

## Implementation Steps
1. Fork or add the nse-sharia-news-feed repo as a submodule/vendor.
2. Write the wrapper module described above.
3. Add unit tests that mock HTTP responses and verify schema compliance.
4. Deploy the scheduler and monitor ingestion latency via eqats' observability stack (Prometheus + Grafana).
5. Document the new data source in the eqats data catalog.

## Expected Benefits
- Provides timely, Sharia‑specific news that can improve alpha generation for Sharia‑compliant strategies.
- Minimal maintenance overhead due to the lightweight nature of the scraper.
- Extensible: the same pattern can be applied to other regional news sources.

## Caveats
- The scraper relies on the structure of the source website; changes may break ingestion.
- No guarantee of news latency or completeness; treat as supplementary data.
- Ensure compliance with any usage policies of the source site.
