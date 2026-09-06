# Integration Blueprint for bhavCopy into eqats

## Overview
The bhavCopy repository provides a simple Python script to fetch the latest NSE bhav copy file and compute market breadth metrics such as advance/decline counts, bull/bear ratio, and advance/decline ratio.

## Relevant Features (Data Engines)
- **Automatic Bhav Copy Retrieval**: Scans for the most recent bhav copy file starting from today's date and moving backward until a file is found.
- **Data Filtering**: Extracts only the relevant columns needed for breadth calculation.
- **Market Breadth Computation**: Calculates number of stocks advancing >5%, declining >5%, bull/bear ratio, and advance/decline ratio.

## How to Integrate into eqats
1. **Data Engine Module**: Wrap the fetching and processing logic into a reusable `NSEBhavCopyFetcher` class within eqats' data ingestion layer.
2. **Schedule**: Integrate with eqats' data pipeline to run after market close, storing the breadth metrics in a time‑series database (e.g., InfluxDB) for downstream consumption.
3. **API Exposure**: Expose the computed metrics via eqats' internal feature store or as a Prometheus endpoint for monitoring dashboards.
4. **Testing**: Use the existing sample output as a regression test to ensure the fetcher returns expected fields.

## Domains Mapping
- **Data Engines**: All features listed above.
- **Signal & Execution Logic**: None – the repo does not generate trading signals or execute orders.
- **Risk Engineering**: None – no risk limits, position sizing, or risk monitoring functionality is present.

## Benefits
- Provides a reliable, low‑latency source of NSE market breadth that can be used as a macro indicator in eqats' strategy research.
- Minimal dependencies (pure Python, standard library) simplifies deployment and maintenance.

## Future Enhancements
- Add support for sector‑wise breadth.
- Integrate with eqats' signal generation to filter trades based on extreme bull/bear ratios.
- Store raw bhav copy files for backtesting and deeper analysis.