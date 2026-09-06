# Integration Blueprint: nseindia_reformat for eqats

## Repository Overview
- **Purpose**: Reformat and analyze Indian National Stock Exchange (NSE) equity order/trade data.
- **Language**: Python 2.7+
- **Key Library**: Pandas (>=0.10)
- **Core Features**:
  1. Parses raw NSE order and trade files into standardized CSV format.
  2. Performs basic descriptive analysis (trade counts, volume, price statistics) on the parsed data.
  3. Outputs CSV files ready for downstream consumption.

## Data Engines Domain Integration
The parser directly addresses the **Data Engines** need for ingesting heterogeneous market data sources.
- **Ingestion**: Replace or supplement eqats' current CSV/JSON ingestors with the `nseindia_reformat` parsing scripts to handle NSE's proprietary order/trade feeds.
- **Storage**: The script already writes cleaned CSV files; these can be landed into eqats' data lake (e.g., S3, HDFS) or directly loaded into the feature store.
- **Extensibility**: The parsing logic is modular; eqats can wrap it in a reusable adapter that normalizes column names to the internal schema (timestamp, symbol, side, quantity, price, trade_id, etc.).
- **Example Integration**:
  ```python
  from nseindia_reformat import parse_order_file, parse_trade_file
  import pandas as pd

  def ingest_nse(order_path, trade_path):
      orders = parse_order_file(order_path)
      trades = parse_trade_file(trade_path)
      # Optionally merge or store separately
      orders.to_csv('eqats_data/orders_nse.csv', index=False)
      trades.to_csv('eqats_data/trades_nse.csv', index=False)
      return orders, trades
  ```

## Signal & Execution Logic Domain
The repository does **not** contain explicit signal generation or order execution logic. However, the analytical output (e.g., volume-weighted average price, trade frequency) can serve as **feature inputs** for eqats' signal engine.
- **Potential Features**:
  - Intraday liquidity metrics (trade count per minute, average trade size).
  - Price impact estimates derived from order-book imbalance.
  - These can be computed post-ingestion and fed into eqats' feature pipeline to enrich signals.
- **Integration Path**:
  1. Run the parser to obtain cleaned CSV.
  2. Apply eqats' feature engineering module to compute indicators.
  3. Feed resulting feature set into strategy modules.

## Risk Engineering Domain
No native risk-limit, position-sizing, or monitoring components are present. Risk management would need to be implemented separately in eqats, using the ingested NSE data as one of many market feeds.
- **Considerations**:
  - Monitor data latency and completeness from the NSE feed via eqats' existing data-quality checks.
  - Apply position-sizing rules after signal generation, independent of the parsing step.

## Implementation Steps for eqats
1. **Fork or submodule** the `nseindia_reformat` repository into eqats' vendor directory.
2. Create an adapter (`eqats/ingest/nse_adapter.py`) that calls the parser and maps outputs to eqats' canonical schema.
3. Add unit tests verifying that sample NSE files produce expected CSV columns.
4. Deploy the adapter in eqats' data ingestion DAG (e.g., Airflow, Prefect) to run on schedule or via file-watcher.
5. Validate that the landed CSV passes eqats' data-validation schema before being made available to the feature store.
6. Optionally extend the parser to compute basic analytics (VWAP, trade intensity) and store them as derived features.

## Conclusion
The `nseindia_reformat` project offers a solid, battle-tested foundation for ingesting NSE equity order/trade data into eqats. By wrapping its parser in a thin adapter, eqats gains reliable access to a major Indian market data source, enabling richer signal development while keeping risk and execution logic concerns within eqats' existing frameworks.