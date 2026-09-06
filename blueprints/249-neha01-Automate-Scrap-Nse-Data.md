# Integration Blueprint for eqats

## Overview
The Automate-Scrap-Nse-Data repository provides a ready‑made pipeline for collecting Nifty50 constituent lists and their historical price data from public sources (Wikipedia and NSE). This capability can be plugged into the Data Engines layer of eqats to feed the rest of the system with clean, up‑to‑date market data.

## Data Engine Integration
1. **Constituent Acquisition**
   - Replace eqats’ static universe loader with the Wikipedia scraping function (uses requests + BeautifulSoup).
   - Output a CSV (or directly a DataFrame) that eqats can ingest into its symbol registry.
2. **Historical Price Download**
   - Reuse the Selenium‑driven navigation of NSE’s Stock’s archive section to pull 12‑month OHLCV CSV files for each symbol.
   - Store the files in eqats’ data lake under data/raw/nse/<symbol/>.
   - Optionally convert CSVs to eqats’ preferred format (e.g., Parquet) during ingestion.
3. **Data Validation & Storage**
   - Add a lightweight validation step (check for expected columns, date ranges) before persisting.
   - Metadata (download timestamp, source URL) can be recorded in eqats’ catalog.
4. **Visualization Helper**
   - The existing candlestick plotting routine (matplotlib) can be exposed as a utility for eqats’ research notebooks or dashboard components.

## Signal & Execution Logic
The repository does not contain any alpha‑generation or order‑execution code. Consequently, no direct integration points exist for eqats’ Signal & Execution Logic domain. If desired, the downloaded historical data can serve as input for eqats’ existing strategy modules.

## Risk Engineering
Similarly, there are no risk‑limit, position‑sizing, or monitoring features to integrate. The data pipeline can, however, feed eqats’ risk engine with the needed price time‑series for VaR, exposure, and liquidity calculations.

## Implementation Steps
1. Fork the repository and extract the two core functions:
   - get_nifty50_list() → returns list of symbols.
   - download_historical_data(symbol) → saves CSV.
2. Wrap them in eqats‑compatible service classes (e.g., Nifty50UniverseProvider, NSEHistoricalDataFetcher).
3. Add unit tests using eqats’ testing framework, mocking web requests where appropriate.
4. Deploy as a scheduled job (e.g., Airflow DAG or eqats’ cron‑like scheduler) to keep the universe and price data fresh.

## Benefits
- Eliminates manual data collection for Indian equities.
- Provides a reliable, automated source of Nifty50 historical data for backtesting and live trading.
- Leverages mature, well‑tested libraries (Selenium, pandas, BeautifulSoup) already present in the eqats environment.

## Caveats
- Selenium requires a compatible ChromeDriver; eqats must provision this in its execution environment.
- The script targets the NSE website layout; any changes to NSE’s archive page may break the scraper and will need updates.
- No built‑in error‑retry logic; consider wrapping calls with eqats’ retry/resilience patterns.

## Conclusion
By incorporating the data‑collection components of Automate-Scrap-Nse-Data into eqats’ Data Engines, the platform gains a robust, automated pipeline for Nifty50 market data, enabling downstream signal generation, execution, and risk analysis without reinventing the wheel.