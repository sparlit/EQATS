# Integration Blueprint for nseeod into eqats

## Overview
The nseeod repository provides a lightweight downloader for National Stock Exchange (NSE) end-of-day (EOD) equity data. It can be leveraged as a data engine within eqats to feed historical price series into the strategy and risk modules.

## Key Features to Integrate
- **HTTP-based EOD fetch**: Uses `requests` to pull daily bhavcopy files from NSE's public API.
- **Incremental download**: Checks existing local files and only downloads missing dates.
- **Data normalization**: Converts raw CSV into a standardized DataFrame with columns: `date, symbol, open, high, low, close, volume`.
- **Storage options**: Saves data as CSV or Parquet partitioned by year/month for fast retrieval.
- **CLI interface**: Simple command‑line tool (`nseeod download --start 2020-01-01 --end 2023-12-31`) that can be invoked from eqats' data pipeline.

## Integration Steps
1. **Wrap as a Data Engine Plugin**
   - Create an eqats plugin `nseeod_engine.py` exposing a `load(symbols, start, end)` method.
   - Internally call the existing nseeod download function, then read the cached files into a pandas DataFrame.
   - Return data in eqats' canonical format (`pd.DataFrame` with multi‑index `[date, symbol]`).

2. **Configuration**
   - Add a `data_engines.nseeod` section in eqats config:
     ```yaml
     data_engines:
       nseeod:
         enabled: true
         storage_path: ./data/nseeod
         file_format: parquet
     ```
   - The plugin reads these settings to locate or download data.

3. **Pipeline Integration**
   - In the eqats data ingestion stage, invoke the nseeod engine before feature construction.
   - Because the downloader is incremental, subsequent runs only fetch new sessions, keeping latency low.

4. **Testing & Validation**
   - Unit test the plugin using a mock HTTP server (e.g., `responses`) to verify correct handling of missing dates and file formats.
   - Validate that the output DataFrame matches eqats' schema (required columns, proper dtypes).

## Benefits
- Provides a reliable, low‑maintenance source of Indian equity EOD data.
- Leverages existing incremental logic, reducing bandwidth and storage costs.
- Enables eqats strategies to backtest and trade NSE‑listed instruments without building a custom downloader.

## Limitations & Mitigations
- **No real‑time streaming**: nseeod only offers EOD; for intraday needs, pair with a separate feed.
- **Dependency on NSE's public endpoint**: Should include fallback to a paid provider if the endpoint changes.
- **Language mismatch**: If eqats is primarily Scala/Java, consider a thin Python subprocess or rewrite core logic in JVM language; however, the downloader is small enough to call via `py4j` or similar.

## Conclusion
Integrating nseeod as a data engine enriches eqats with Indian market historical data, supporting strategy development and risk analysis while requiring minimal code changes.