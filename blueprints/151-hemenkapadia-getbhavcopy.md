# Integration Blueprint: getbhavcopy into eqats

## Repository Overview
- **Name:** getbhavcopy
- **Purpose:** Free downloader for NSE and BSE end‑of‑day (EOD) data (equities, indices, futures).
- **Key Features:**
  - Retrieves daily and historical EOD data directly from NSE and BSE servers.
  - Exports data in formats compatible with Metastock, Amibroker, and Fcharts.
  - Provides authentic, exchange‑sourced data.

## Domain Mapping
| eqats Domain | Relevant Features from getbhavcopy |
|--------------|------------------------------------|
| **Data Engines** | - Ingestion of NSE/BSE EOD equity, index, and futures data.
- Historical data download (configurable date ranges).
- Export to standard technical‑analysis file formats (Metastock, Amibroker, Fcharts).
- Direct connection to exchange servers ensuring data authenticity.
| **Signal & Execution Logic** | *None identified.* The repository focuses solely on data acquisition; it does not contain signal generation, strategy logic, or order‑execution components.
| **Risk Engineering** | *None identified.* No risk‑limit, position‑sizing, or monitoring functionality is present.

## How to Integrate getbhavcopy into eqats

### 1. Data Engine Layer Enhancement
- Wrap the downloader as a reusable data‑source plugin within eqats’ data‑engine abstraction.
- Expose a uniform interface (e.g., `fetch_ohlcv(symbol, start_date, end_date, exchange)`) that internally calls getbhavcopy’s download functions.
- Normalize the output to eqats’ internal market‑data schema (timestamp, open, high, low, close, volume) regardless of the export format; if needed, convert Metastock/Amibroker files to CSV or Parquet for storage.

### 2. Storage & Caching
- Store downloaded raw files in eqats’ data lake (e.g., S3, local NAS) partitioned by exchange, symbol, and date.
- Implement a caching layer to avoid re‑downloading the same day's bhavcopy; getbhavcopy already checks for existing files, which can be leveraged.

### 3. Scheduling & Automation
- Integrate with eqats’ job scheduler (e.g., Airflow, Prefect, or simple cron) to trigger the getbhavcopy plugin after market close each trading day.
- For back‑testing workflows, allow on‑demand historical pulls via the same plugin.

### 4. Metadata & Data Quality
- Attach provenance metadata (source: NSE/BSE, download timestamp, authenticity flag) to each ingested record.
- Use getbhavcopy’s direct‑server connection as a quality guarantee; optionally add validation checks (e.g., OHLC consistency) before persisting.

### 5. Example Integration Sketch (Python)
```python
from eqats.data_sources import BaseDataSource
import getbhavcopy  # hypothetical installed package

class NSEBhavcopySource(BaseDataSource):
    def fetch_ohlcv(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        # getbhavcopy returns a DataFrame or writes a file; adapt as needed
        df = getbhavcopy.download_eod(
            symbol=symbol,
            exchange='NSE',
            start_date=start,
            end_date=end,
            output_format='dataframe'  # assume a mode that returns a DataFrame
        )
        # Normalize column names
        df = df.rename(columns={
            'DATE': 'timestamp',
            'OPEN': 'open',
            'HIGH': 'high',
            'LOW': 'low',
            'CLOSE': 'close',
            'VOLUME': 'volume'
        })
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        return df
```

### 6. Benefits for eqats
- **Authentic Data:** Direct exchange‑sourced EOD data eliminates reliance on third‑party vendors.
- **Cost‑Effective:** Free, open‑source downloader reduces data acquisition expenses.
- **Broad Coverage:** Equities, indices, and futures across both NSE and BSE expand the universe available for strategy research.
- **Compatibility:** Existing export formats enable quick validation with popular charting tools (Metastock, Amibroker) during development.

### 7. Considerations & Limitations
- **Frequency:** getbhavcopy provides EOD data only; intraday or tick‑level data would require additional sources.
- **Maintenance:** Monitor for changes in NSE/BSE website structures that could break the downloader; contribute fixes upstream if needed.
- **Legal:** Ensure compliance with exchange terms of use when redistributing downloaded data.

## Conclusion
By wrapping getbhavcopy as a data‑source plugin within eqats’ Data Engines domain, the project gains a reliable, zero‑cost pipeline for authentic NSE and BSE EOD market data. No direct contributions to Signal & Execution Logic or Risk Engineering are offered by this repository, but the enriched data foundation will empower those downstream components.
