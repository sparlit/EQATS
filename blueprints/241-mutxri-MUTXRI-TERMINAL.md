# Integration Blueprint for MUTXRI TERMINAL into eqats

## Overview
The MUTXRI TERMINAL repository provides a static snapshot of African market data (NSE Kenya, NGX Nigeria, JSE South Africa, EGX Egypt) consisting of end‑of‑day listings, heatmaps, indices, and per‑security candlestick history stored as JSON files. While the UI is HTML‑based and does not offer live endpoints, the underlying data can be repurposed as a historical data source for eqats, particularly for backtesting and reference purposes.

## Data Engines Integration
- **Static Data Ingestion**: eqats can ingest the JSON files located at `static_data/history/<SYM>.json` as part of its historical data pipeline. A simple parser can convert each file into eqats' internal bar format (timestamp, open, high, low, close, volume).
- **Snapshot Utilization**: The 2026-09-06 snapshot serves as a fixed reference dataset for unit testing, strategy development, and scenario analysis where real‑time feeds are unavailable.
- **Coverage**: JSE and EGX symbols include one year of daily bars sourced from Yahoo Finance; NGX and NSE lack historical data in this snapshot, so they can be marked as having limited history.
- **Metadata**: The snapshot also includes listings, heatmaps, and index values that can be used to populate eqats' universe definition and benchmark calculations.

## Signal & Execution Logic
The repository does not contain any signal generation, strategy code, or order execution logic. Consequently, there are no direct components to integrate into eqats' signal & execution domain. If desired, the static UI could serve as a inspiration for building a custom African‑market dashboard within eqats, but no functional code is available for reuse.

## Risk Engineering
No risk‑management modules, position‑sizing algorithms, or monitoring tools are present in the repository. Hence, there are no risk‑engineering features to integrate. eqats should rely on its existing risk framework when trading African securities using data sourced from this snapshot.

## Implementation Steps
1. **Data Connector**: Develop a connector in eqats that reads the `static_data/history` directory, maps each `<SYM>.json` to the appropriate exchange and symbol, and loads the bars into eqats' historical store.
2. **Validation**: Verify data integrity (e.g., no missing timestamps, correct OHLCV ranges) and flag NGX/NSE symbols as having limited history.
3. **Universe Building**: Use the static listings to extend eqats' tradable universe to include African equities, assigning appropriate currency and timezone metadata.
4. **Backtesting**: Run existing eqats strategies against the snapshot data to evaluate performance on African markets, noting the static nature (no look‑ahead bias beyond the snapshot date).
5. **Documentation**: Record the data source, snapshot date, and limitations in eqats' data catalog to inform users about the static nature of the African market dataset.

## Conclusion
While MUTXRI TERMINAL offers no executable trading logic, its curated static data snapshot provides a valuable historical foundation for eqats to expand into African markets. By integrating the JSON‑based history files, eqats can enable backtesting, universe expansion, and research on NSE, NGX, JSE, and EGX securities, complementing its existing data engines with a new geographic focus.