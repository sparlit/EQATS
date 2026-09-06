# Integration Blueprint for NSE Live Data Extraction into eqats

## Overview
The NSE_Livedata_from_excel_extraction repository provides a Python‑based utility that pulls live market data from the National Stock Exchange (India) and writes it into an Excel workbook via xlwings. This capability can be leveraged as a real‑time market‑data connector within the eqats trading platform.

## Valuable Features
- Live Market Data – NIFTY indices, sectoral indices, etc.
- Pre‑Market Data – Auction/open‑interest style data.
- F&O Market Data – Futures & Options segment.
- Symbol Lists & Holiday Calendars – Reference data for universe construction.
- Excel Automation – Uses xlwings to push data into a familiar spreadsheet interface.
- Executable Distribution – Built with PyInstaller for easy deployment on Windows.

## How to Integrate into eqats

### 1. Data Engine Layer
- Create a new eqats connector module `eqats.connectors.nse_excel`.
- Reuse the existing data‑fetching functions (e.g., `get_live_market()`, `get_pre_market()`, `get_fno_data()`, `get_symbol_list()`, `get_holidays()`).
- Replace the Excel‑write step with a write to eqats’ internal time‑series store (e.g., a Redis‑backed tick database or a TimescaleDB table).
- Keep the xlwings‑based Excel output as an optional debug mode (controlled by a flag) so analysts can still view raw data in Excel.

### 2. Scheduling & Execution
- Wrap the connector in an eqats `DataEngine` service that runs on a configurable interval (e.g., every 5 seconds during market hours).
- Use eqats’ existing service manager to start/stop the connector alongside other data feeds.
- Provide a health‑check endpoint that reports last successful fetch timestamp.

### 3. Configuration
- Extend eqats’ YAML config with an `nse_excel` section:
  ```yaml
  data_engines:
    nse_excel:
      enabled: true
      fetch_interval_sec: 5
      excel_output: false   # set true for debug
      symbols: ["NIFTY 50", "BANKNIFTY"]   # optional filter
  ```
- The connector reads this config and adapts its requests accordingly.

### 4. Testing & Validation
- Unit‑test each fetch function using mocked NSE responses.
- Integration test: run the connector against a local eqats instance and verify that ticks appear in the market‑data stream.
- Validate that holiday calendar is used to pause fetching on non‑trading days.

### 5. Risk Engineering Hook (Optional)
- Although the repo does not contain risk logic, the ingested data can feed eqats’ risk modules:
  - Real‑time volatility calculations from live index ticks.
  - Pre‑market auction imbalance metrics for opening‑range strategies.
  - F&O open‑interest changes for margin monitoring.

## Benefits
- Low‑latency access to NSE data without needing a costly API subscription.
- Familiar Excel fallback for traders who prefer spreadsheet analysis.
- Reusable, container‑friendly Python code that fits eqats’ microservice architecture.

## Caveats
- The repository targets Windows (xlwings requires Excel). For Linux/macOS deployments, consider replacing xlwings with direct CSV/JSON output or using `openpyxl` for file‑based Excel generation.
- Ensure compliance with NSE’s data usage terms when redistributing live data.

## Next Steps
1. Fork the repository and extract the core fetching logic into a standalone Python package.
2. Add the eqats connector wrapper as described.
3. Submit a pull request to the eqats main repo under `contrib/connectors/nse_excel`.
4. Deploy in a staging environment and monitor latency and data quality.
