# Integration Blueprint: nse1minR → eqats

## Overview
The `nse1minR` repository is an R data package that distributes high‑frequency (1‑minute) historical market data for the National Stock Exchange of India (NSE). It contains:
- Minute‑level OHLCV series for the NIFTY 50 index (`nifty_1min`).
- Minute‑level OHLCV series for the BANK NIFTY index (`bank_1min`).
- Minute‑level OHLCV series for ~502 individual stocks, grouped alphabetically (e.g., `nse_BB`, `nse_CC`, …).
- A `companyList` data frame mapping company names, ticker IDs, and the associated data file.
- Documentation of the raw data source and the R‑based cleaning pipeline (using `dplyr`, `stringr`).

Because the data are already packaged as R objects, they can be loaded instantly with `library(nse1minR)` and used directly in any R‑based quantitative workflow.

## How to Leverage in eqats

### 1. Data Engine Layer
Eqats already defines a **Data Engines** domain responsible for market‑data ingestion, storage, and provisioning. The `nse1minR` package can be adopted as a **plug‑in data source** for the Indian equity market:

- **Data Loader Adapter** – Write a thin wrapper in eqats that calls `data(package = "nse1minR")` or directly accesses the exported objects (e.g., `nifty_1min`, `bank_1min`, `nse_<group>`). The adapter converts the native R data frames into eqats’ internal market‑data format (e.g., Apache Arrow tables or pandas‑like structures).
- **Metadata Mapping** – Use the `companyList` frame to map ticker symbols to the correct internal dataset (`nse_<group>`). This enables eqats to resolve a symbol like `BAJAJCORP` to the appropriate data frame without hard‑coding file names.
- **Incremental Updates** – Although the package currently covers 2013‑2016, the raw‑data processing script (based on `wget` + `dplyr`/`stringr`) is documented. Eqats can schedule a periodic job that re‑runs the script against the source URL (`http://www.keralabanking.com/intraday-one-minute-historical-data-free-download/`) to generate newer `.RData` snapshots, then version‑control them within eqats’ data lake.
- **Storage Optimization** – The existing `.RData` files are already compressed (~223 MB). Eqats can retain this format for archival storage while converting active working sets to columnar formats (Parquet/Feather) for low‑latency access during back‑testing or live‑signal generation.

### 2. Signal & Execution Logic
The repository does **not** contain any trading signals, strategy code, or order‑execution logic. Consequently, there are no direct assets to plug into eqats’ **Signal & Execution Logic** domain. However, the rich minute‑level data can be used as the **foundation** for developing new strategies within eqats:

- **Back‑testing Engine** – Feed the loaded data into eqats’ vectorized or event‑driven back‑tester to evaluate momentum, mean‑reversion, or machine‑learning models on Indian equities.
- **Feature Generation** – Use the high‑frequency series to compute technical indicators (e.g., VWAP, rolling volatility, order‑flow imbalance) directly in R or via eqats’ feature‑store interface.

### 3. Risk Engineering
No risk‑related components (limits, position sizing, monitoring) are present in `nse1minR`. Therefore, the **Risk Engineering** domain receives no direct contributions. Eqats can still apply its existing risk‑management modules (VaR, stress testing, exposure limits) to strategies built on top of this data.

## Implementation Steps

1. **Add Dependency** – Include `nse1minR` (via `devtools::install_github("ramamet/nse1minR")`) in the eqats R environment.
2. **Create Adapter Module** – `eqats/data_engines/nse1minR_adapter.R` exposing functions:
   - `load_index_data(index_name)` → returns OHLCV tibble.
   - `load_stock_data(symbol)` → resolves symbol via `companyList` and returns the appropriate minute‑level tibble.
   - `get_available_symbols()` → returns vector of all tickers.
3. **Metadata Registration** – Register the new data source in eqats’ data‑catalog so that the data‑engine discovery mechanism can pick it up automatically.
4. **Back‑test Integration** – Use the adapter as input to eqats’ `backtest.run()` function, specifying the desired time range and symbols.
5. **Refresh Pipeline (Optional)** – Schedule a cron job that:
   - Downloads raw files from the source URL.
   - Executes the cleaning script (provided in the repo’s `rawData` section).
   - Re‑builds the `.RData` package and pushes it to eqats’ internal artifact repository.

## Benefits
- **Immediate Access** – No need to parse raw CSV files; data are already in a tidy R format.
- **Comprehensive Coverage** – Includes both index and constituent‑stock data, enabling index‑arbitrage and sector‑analysis studies.
- **Transparent Provenance** – The README documents the source and processing steps, satisfying eqats’ data‑lineage requirements.
- **Low Overhead** – The package is lightweight to install (~223 MB) and loads quickly, fitting well into eqats’ iterative research workflow.

## Limitations & Mitigations
- **Historical Range** – Data stop at 2016. Mitigation: use the documented pipeline to extend the dataset forward.
- **Single‑Market Focus** – Only NSE (India). Mitigation: treat this as a regional data‑engine plugin; eqats can host multiple such plugins for other exchanges.
- **R‑Centric** – The native format is R objects. Mitigation: the adapter converts to eqats’ language‑agnostic columnar storage, allowing consumption from Python, Julia, or other language bindings.

---
*This blueprint outlines how the `nse1minR` data package can serve as a valuable **Data Engines** component for eqats, providing ready‑to‑use, high‑resolution Indian market data while leaving signal generation and risk management to eqats’ existing frameworks.*