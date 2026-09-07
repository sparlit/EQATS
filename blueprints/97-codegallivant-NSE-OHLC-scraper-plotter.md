# Integration Blueprint: NSE OHLC Scraper‑Plotter into eqats

## Overview
The `NSE-OHLC-scraper-plotter` repository scrapes OHLC data from the National Stock Exchange of India (NSE) and plots candlestick charts. Its core value for eqats lies in the **data ingestion** component: retrieving reliable, up‑to‑date OHLC series for Indian equities and indices.

## Proposed Integration

### 1. Data Engine Wrapper
- Create a new eqats data‑engine module, e.g., `eqats.data_engines.nse_ohlc`.
- Encapsulate the existing scraping logic (HTTP request to NSE, HTML parsing with BeautifulSoup, conversion to pandas DataFrame) into a function:
  ```python
  def fetch_nse_ohlc(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
      # ... scraping implementation ...
      return df  # columns: ['Date','Open','High','Low','Close']
  ```
- Add optional caching (e.g., using `joblib.Memory` or a simple file‑based cache) to avoid repeated network calls for the same symbol/date range.
- Ensure the module conforms to eqats’ data‑engine interface (e.g., inherits from `BaseDataEngine` and implements `get_data(symbol, timeframe, start, end)`).

### 2. Configuration & Discovery
- Expose the new engine via eqats’ plugin system: add an entry point in `setup.py` or `pyproject.toml` so that eqats can discover `nse_ohlc` as a available data source.
- Provide a configuration snippet for users:
  ```yaml
  data_engines:
    nse_ohlc:
      enabled: true
      cache_dir: ~/.eqats/cache/nse_ohlc
  ```

### 3. Usage in eqats Workflows
- In strategy development, users can request NSE OHLC data just like any other market data source:
  ```python
  data = eqats.get_data('nse_ohlc', symbol='RELIANCE.NS', timeframe='1d', start='2023-01-01', end='2023-12-31')
  ```
- The returned DataFrame can feed directly into eqats’ signal generation, backtesting, or live trading pipelines.

### 4. Extending Visualization (Optional)
- The original plotting code (matplotlib + tkinter) can be reused as a utility for quick exploratory analysis within eqats’ notebooks or dashboards.
- Consider wrapping the candlestick plot in a helper function `plot_ohlc(df)` that eqats’ UI can call.

### 5. Testing & Reliability
- Write unit tests that mock the HTTP responses to ensure the parser works with sample NSE HTML.
- Add integration tests that hit the live NSE endpoint (guarded by an environment variable) to detect breaking changes in the website layout.
- Handle common error cases: invalid symbol, network failures, missing data, and raise eqats‑compatible exceptions.

## Benefits
- **Local Market Coverage**: Adds Indian equity data to eqats, which currently may focus on other exchanges.
- **Low Dependency Overhead**: Uses widely‑available Python packages (requests, beautifulsoup4, pandas, matplotlib).
- **Reusable Caching**: Reduces latency and avoids hitting NSE rate limits.

## Limitations & Mitigations
- **Website Structure Risk**: If NSE changes its HTML layout, the scraper may break. Mitigation: monitor for updates, implement fallback to a public API (e.g., NSE’s official API if available) or a secondary data source.
- **No Real‑Time Streaming**: The scraper provides end‑of‑day or historical data. For real‑time tick data, additional modules would be needed.

## Conclusion
By extracting the scraping logic into a pluggable data engine, eqats gains a straightforward way to ingest NSE OHLC data, expanding its asset coverage and enabling quantitative strategies on Indian securities without reinventing the wheel.