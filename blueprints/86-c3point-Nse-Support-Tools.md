# Integration Blueprint for Nse-Support-Tools into eqats

## Overview
The Nse-Support-Tools repository provides a lightweight Python client for fetching real‑time market data from the National Stock Exchange of India (NSE). Its core functionality centers on retrieving quotes, lists, and pre‑open data for equities, indices, and derivatives.

## Data Engine Integration
All exposed methods map directly to eqats’ Data Engines layer, which is responsible for market‑data ingestion, normalization, and storage.

| Nse‑Support‑Tools Method | eqats Data Engine Equivalent | Description |
|--------------------------|-----------------------------|-------------|
| `get_stock_quote(symbol)` | `MarketDataFetcher.get_quote(symbol)` | Retrieves latest quote for a single equity. |
| `get_bulk_stock_quotes(symbol_list=None)` | `MarketDataFetcher.get_bulk_quotes(symbol_list)` | Pulls quotes for all NSE symbols or a user‑supplied list; results stored in `quote_list`. |
| `get_equity_instrument_list()` | `InstrumentRepository.load_equities()` | Returns the full list of equity instruments traded on NSE. |
| `get_nifty_gainers()` / `get_nifty_losers()` | `IndexMetricsFetcher.get_gainers('NIFTY')` / `get_losers('NIFTY')` | Provides top movers for the NIFTY index. |
| `get_fno_gainers()` / `get_fno_losers()` | `DerivativesMetricsFetcher.get_gainers('FNO')` / `get_losers('FNO')` | Same for futures & options segment. |
| `get_advance_decline_ratio()` | `MarketBreadthFetcher.get_advance_decline()` | Supplies the advance‑decline ratio for market breadth analysis. |
| `get_indices_list()` | `IndexRepository.load_all()` | Lists all available NSE indices. |
| `get_most_active_monthly()` | `VolumeAnalyticsFetcher.get_most_active(period='monthly')` | Highlights most actively traded stocks over the past month. |
| `get_year_high()` / `get_year_low()` | `PriceExtremesFetcher.get_year_high()` / `get_year_low()` | Returns yearly high/low prices for securities. |
| `get_nifty_preopen()` / `get_fno_preopen()` / `get_bank_nifty_preopen()` | `PreOpenFetcher.get_preopen('NIFTY')` etc. | Captures pre‑open auction data for indices. |

### Implementation Steps
1. **Wrap the client** – Create a thin adapter class `NseSupportAdapter` inside `eqats/data_engines/market_data/nse_support.py` that instantiates `NseSupport.Nse()` and delegates each method to the corresponding eqats interface.
2. **Normalize payloads** – Convert the raw dictionaries returned by Nse‑Support‑Tools into eqats’ canonical `Quote`, `Instrument`, and `MarketMetrics` dataclasses (already defined in `eqats/core/models.py`).
3. **Integrate with the scheduler** – Register the adapter with eqats’ data‑ingestion scheduler (e.g., `DataIngestionManager`) so that quotes are fetched at the desired frequency (real‑time tick, end‑of‑day, etc.).
4. **Persist to storage** – Feed normalized objects into eqats’ storage layer (e.g., TimescaleDB or Redis) via the existing `DataStore` abstraction.
5. **Add unit tests** – Use the repository’s existing examples as test vectors; mock HTTP responses to ensure reliability.
6. **Documentation** – Update the eqats data‑engine documentation to note the NSE India data source and its refresh characteristics.

## Signal & Execution Logic
The repository does not contain any signal generation, strategy, or order‑execution components. Hence, no direct mapping exists for the Signal & Execution Logic domain. If eqats requires NSE‑specific signals (e.g., momentum based on NIFTY gainers), those can be built on top of the ingested data using eqats’ existing signal framework.

## Risk Engineering
Similarly, there are no risk‑limit, position‑sizing, or monitoring features in Nse‑Support‑Tools. Risk calculations (VaR, exposure limits, etc.) should continue to be handled by eqats’ Risk Engineering modules, consuming the market data supplied by this adapter.

## Benefits
- **Rapid access** to Indian equity and derivative market data without maintaining a custom scraper.
- **Low dependency footprint** – only the packages listed in `requirements.txt`.
- **Consistent interface** – aligns with eqats’ pluggable data‑engine pattern, enabling easy swap with other providers (e.g., Bloomberg, Quandl).
- **Extensible** – the adapter can be expanded to include forthcoming features from the repository’s TODO list (sector/industry data, improved error handling, etc.).

## Conclusion
By integrating Nse‑Support‑Tools as a dedicated NSE India market‑data adapter within eqats’ Data Engines layer, the platform gains immediate access to a broad set of real‑time quotes, index movers, and pre‑open information. This enriches the data universe for strategy development, back‑testing, and live trading while keeping signal and risk layers unchanged.
