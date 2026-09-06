# Integration Blueprint for MTFDB into eqats

## Overview
The MTFDB repository provides parquet-formatted snapshots and summary statistics of NSE Margin Trading Facility (MTF) financing activity. As a data‑only repository, it contains no code but offers ready‑to‑use market‑data assets that can be ingested by eqats’ data engine.

## Data Engine Integration
1. **Ingestion Pipeline**
   - Add a new connector in eqats’ data‑ingestion layer that reads Parquet files from the MTFDB snapshot location (e.g., via `pyarrow` or `pandas.read_parquet`).
   - Schedule periodic pulls (e.g., daily) to keep the local cache up‑to‑date with the latest snapshots.
   - Store the raw Parquet files in eqats’ data lake (e.g., S3 or local filesystem) under a `mtfdb/` prefix.
2. **Metadata & Catalog**
   - Register each snapshot as a dataset in eqats’ data catalog (e.g., using AWS Glue or a simple CSV manifest) with fields: snapshot_date, financing_amount, interest_rate, participant_count, etc.
   - Enable schema evolution handling for future updates.
3. **Feature Store**
   - Derive engineered features such as MTF utilization ratio, day‑over‑day change in financing, and aggregate summary statistics.
   - Publish these features to eqats’ feature store for consumption by strategies.

## Signal & Execution Logic Usage
- Although MTFDB does not contain signals, the derived features can be fed into existing eqats strategies:
   - **Liquidity‑adjusted signals**: Incorporate MTF utilization as a proxy for retail leverage pressure.
   - **Mean‑reversion or momentum**: Use day‑over‑day changes in MTF financing as a leading indicator of market sentiment.
   - **Event‑driven triggers**: Flag abnormal spikes in MTF activity for potential short‑term volatility.
- Strategies can subscribe to the MTF feature topic via eqats’ event bus (e.g., Kafka) and adjust position sizing or entry/exit logic accordingly.

## Risk Engineering Application
- The MTF financing data serves as an auxiliary risk monitor:
   - **Leverage risk**: Track aggregate MTF financing relative to total market capitalization to gauge systemic leverage.
   - **Concentration risk**: Monitor financing by individual brokers or participants if granular data is available.
   - **Risk limits**: Implement a rule that reduces equity exposure when MTF utilization exceeds a predefined threshold (e.g., 5% of free float).
   - **Stress testing**: Use historical MTF snapshots to simulate scenarios of sudden unwind and assess portfolio impact.

## Implementation Steps
1. Fork MTFDB or add it as a submodule/git‑lfs tracked data source.
2. Develop the Parquet ingestion connector (Python, using `pyarrow`).
3. Update eqats’ data catalog and feature store schemas.
4. Create a sample strategy that uses MTF utilization as a filter.
5. Add risk‑limit checks in the risk engine that reference the MTF metric.
6. Write unit tests and documentation; deploy to staging.

## Expected Benefits
- Provides alternative data source for gauging retail leverage.
- Enhances signal quality with a macro‑level financing indicator.
- Strengthens risk monitoring by adding a leverage‑specific metric.

## Maintenance
- Monitor MTFDB for updates (new snapshots).
- Adjust ingestion frequency if snapshot cadence changes.
- Keep schema versioning in sync with any changes to the Parquet structure.

---
*This blueprint assumes eqats uses a Python‑centric stack with Parquet support, a feature store (e.g., Feast), and an event‑driven architecture for signals and risk.*