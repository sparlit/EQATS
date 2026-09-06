# Integration Blueprint for NSE India All Stocks Tickers Data

## Repository Overview
- Provides daily OHLCV and adjusted close prices for all NSE-listed stocks (Jan 1 2015 – Jan 15 2021) in CSV files packed inside zip archives.
- Includes a reference CSV that maps NSE ticker symbols to their Yahoo Finance equivalents.

## Data Engines Integration
1. **Ingestion Pipeline**
   - Extend eqats’ market‑data ingestor to unzip the archives and read the CSV files into a unified time‑series store (e.g., a columnar database or Parquet lake).
   - Use the ticker‑mapping CSV to translate NSE symbols to the internal instrument IDs used by eqats, enabling seamless join with other data sources (e.g., fundamentals, news).
2. **Storage**
   - Store the raw OHLCV‑adjusted close tables partitioned by date and symbol for fast retrieval.
   - Maintain versioned snapshots to support back‑testing over the full 2015‑2021 window.

## Signal & Execution Logic Usage
- The repository does not contain signals; however, the clean price and volume series are ideal inputs for:
  - Technical‑indicator calculators (moving averages, RSI, MACD).
  - Statistical‑arbitrage or mean‑reversion models that rely on historical price patterns.
  - Machine‑learning feature pipelines that require aligned OHLCV feeds.
- Execution modules can consume the processed signals to generate orders; the data’s high frequency (daily) suits low‑to‑medium frequency strategies.

## Risk Engineering Usage
- Historical price and volume data enable:
  - Volatility estimation (historical VaR, EWMA).
  - Liquidity metrics (average daily volume, impact cost).
  - Drawdown and stress‑testing scenarios.
- Feed the time‑series into eqats’ risk engine to compute position‑size limits, margin requirements, and real‑time risk monitoring (if extended to live data).

## Implementation Steps
1. **Data Acquisition**
   - Clone the repo or download the latest release zip files.
   - Place them in a designated `data/raw/nse_indiastocks/` directory within the eqats codebase.
2. **Ingestion Script** (pseudo‑Python)
   ```python
   import pandas as pd, zipfile, os, glob
   from eqats.data_ingest import store_market_data

   RAW_DIR = "data/raw/nse_indiastocks"
   for zip_path in glob.glob(os.path.join(RAW_DIR, "*.zip")):
       with zipfile.ZipFile(zip_path, 'z') as z:
           for csv_name in z.namelist():
               if csv_name.endswith('.csv'):
                   with z.open(csv_name) as f:
                       df = pd.read_csv(f, parse_dates=['Date'])
                       # Assuming column names: Date, Open, High, Low, Close, Volume, AdjClose
                   store_market_data(df, source='NSE_INDIA')
   ```
3. **Ticker Mapping**
   - Load `NSE_to_Yahoo_Ticker.csv` and create a lookup dict to map raw symbols to eqats instrument IDs.
4. **Validation**
   - Run unit tests to ensure no missing dates, correct OHLC relationships (High ≥ Low, etc.), and that adjusted close aligns with close for non‑adjusted periods.
5. **Back‑testing**
   - Use the stored data in eqats’ back‑tester to evaluate strategies over the 2015‑2021 horizon.

## Considerations
- The data ends in Jan 2021; for live trading, supplement with a real‑time feed (e.g., NSE API or broker data).
- Ensure licensing compliance; the repo appears to be publicly shared but verify any redistribution restrictions.
- Adjust timezone handling (NSE is IST) to match eqats’ internal UTC timestamps.
- Monitor data quality: occasional missing symbols due to delistings or suspensions; implement forward‑fill or removal logic as appropriate.
