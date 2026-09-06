# Integration Blueprint for NSE-Data-bank into eqats

## Overview
The NSE-Data-bank repository offers daily historic and latest NSE Equity Bhavcopy files (CSV) covering over two decades of Indian equity data. While the data is valuable, direct integration into eqats faces challenges due to the NSE website's anti-bot protections (required cookies, dynamic User-Agent, and potential JavaScript-generated download links).

## Domain Mapping
- **Data Engines**: Ideal role would be to automate download, caching, and parsing of Bhavcopy CSV files. In practice, a simple HTTP GET often fails without maintaining a valid session, making a reliable data engine difficult to implement without a headless browser or official API.
- **Signal & Execution Logic**: Strategies depend on clean, timely price and volume data. Unreliable data ingestion would introduce gaps and look-ahead bias, so the repository cannot safely serve as a signal-generation feed without additional robustness measures.
- **Risk Engineering**: Risk calculations (volatility, VaR, drawdown) require complete, gap-free historical series. Missing or corrupted downloads would compromise metric accuracy, thus the repository is not suitable as a sole source for risk engineering.

## Recommended Approach
1. Use the NSE-Data-bank as a **reference** for data format and schema.
2. Implement a thin wrapper around NSE’s official FTP/API (if available) or employ a headless browser (e.g., Playwright) to authenticate and download the Bhavcopy.
3. Cache the resulting CSV files locally, organized by year/month as suggested in the source repository.
4. Expose the cached data via Rust core and PyO3 bindings for use in signal and risk modules.

## Future Work
- Monitor NSE for changes to download mechanism and update the integration accordingly.
- Add metadata tracking for missing data dates and holidays.
- Extend to derivative Bhavcopy files.