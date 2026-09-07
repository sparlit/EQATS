# Integration Blueprint for NSEFinance-Python in eqats

## Overview
The NSEFinance-Python library provides a simple interface to retrieve end‑of‑day equity data from the National Stock Exchange (NSE) of India. It exposes two core methods:
- `get_daily_list()` – returns OHLCV and volume for all symbols traded on a given day.
- `get_by_symbol(symbol, date=None)` – returns a time‑series of daily bars for a specific symbol; if a date is supplied it returns the bar for that day.

## Domain Mapping
- **Data Engines** – The library is a pure market‑data fetcher, fitting squarely into eqats’ data‑engine layer.
- **Signal & Execution Logic** – No built‑in signal generation or order‑routing capabilities.
- **Risk Engineering** – No risk‑limit, position‑sizing, or monitoring features.

## Integration Steps
1. **Wrap the library** in an eqats‑compatible data‑source plugin (e.g., `NSEFinanceSource`) that implements the `fetch_ohlcv(symbol, start, end, timeframe)` interface.
2. **Normalize field names** to eqats’ canonical schema (`timestamp`, `open`, `high`, `low`, `close`, `volume`). The library already provides `date`, `open`, `high`, `low`, `close`, `units` (volume) and `value` (turnover) which can be mapped.
3. **Schedule ingestion** via eqats’ data‑engine orchestrator (e.g., Airflow or Prefect) to pull daily bars for the watchlist of Indian equities.
4. **Store the raw bars** in eqats’ feature store (e.g., TimescaleDB or S3) using the existing `MarketDataWriter` component.
5. **Optional enrichment** – combine with corporate‑action data or adjust for splits/dividends using eqats’ existing adjustment pipelines.
6. **Consumption** – downstream signal modules can read the NSE data just like any other market‑data source, enabling strategies that trade NSE‑listed stocks.

## Benefits
- Immediate access to free, reliable NSE end‑of‑day data without building a custom scraper.
- Leverages eqats’ modular architecture: plug‑in, configure, and go.
- Enables expansion of eqats’ coverage to Indian equities, diversifying the universe for research and live trading.

## Considerations
- The library provides only daily frequency; for intraday or higher‑resolution data an alternative source would be needed.
- Rate limits and data‑usage policies of NSEFinance.com should be respected; implement caching or throttling as needed.
- No built‑in error handling for missing symbols; the wrapper should translate HTTP errors into eqats‑standard exceptions.