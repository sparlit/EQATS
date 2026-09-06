# Integration Blueprint for nse_eod into eqats

## Overview
The `nse_eod` package provides a simple Python interface to download End‑of‑Day (EOD) OHLCV data from the National Stock Exchange (NSE) of India. It returns data as a pandas DataFrame, which matches eqats’ internal data format. This blueprint outlines how to integrate `nse_eod` as a data engine for eqats, enabling backtesting, research, and live trading on NSE‑listed equities.

## Data Engine Integration
- **Wrapper Creation**: Implement `eqats/data/nse_eod_adapter.py` that exposes two functions:
  - `fetch_historical(symbol: str, start: str, end: str) -> pd.DataFrame`
  - `fetch_period(symbol: str, period: str) -> pd.DataFrame`
  These wrappers will call `nse_eod.get_historical_data` and `nse_eod.get_period_data`, convert the `Date` column to `datetime`, and optionally rename columns to eqats’ canonical names (e.g., `open`, `high`, `low`, `close`, `volume`).
- **Storage**: After fetching, the DataFrame can be persisted to eqats’ feature store (e.g., a TimescaleDB table `market_data.eod`) using existing eqats storage utilities.
- **Unified API**: Add an entry point in `eqats/data/__init__.py` such that users can call `eqats.data.fetch('NSE', symbol, start, end)` which dispatches to the nse_eod adapter when the source is `'NSE'`.
- **Testing**: Use VCR.py or similar to record HTTP interactions and create unit tests that validate column types, date parsing, and handling of missing data.

## Signal & Execution Logic Integration
- The returned DataFrame is directly consumable by eqats’ signal‑generation pipeline. Example usage within a strategy:
  ```python
  import eqats.data as data
  df = data.fetch('NSE', 'ACC', '01-01-2020', '01-03-2020')
  df['returns'] = df['close'].pct_change()
  df['signal'] = (df['returns'].rolling(5).mean() > 0).astype(int)
  ```
- Signals can then be passed to `eqats.execution.generate_orders` or any custom execution logic without modification.
- No new signal or execution code is required from `nse_eod`; it serves purely as a data provider.

## Risk Engineering Integration
- Risk metrics can be computed on the fetched EOD data, for example:
  - **Volatility**: annualized standard deviation of daily returns.
  - **Value‑at‑Risk (VaR)**: parametric or historical VaR on the return series.
  - **Drawdown**: max peak‑to‑trough decline over a look‑back window.
- These calculations can be encapsulated in `eqats/risk/nse_eod_risk.py` and invoked from the eqats risk‑monitoring service during pre‑trade checks or portfolio‑level risk aggregation.
- Because the data is end‑of‑day, it is suitable for daily risk limits and end‑of‑day position‑sizing, but not for intra‑day margin checks.

## Implementation Steps
1. **Add Dependency**: Include `nse_eod` in `eqats/requirements.txt` via a direct git link:
   ```
   git+https://github.com/opmashin/nse_eod.git
   ```
2. **Create Adapter**: Develop `eqats/data/nse_eod_adapter.py` with the wrapper functions described above.
3. **Expose API**: Update `eqats/data/__init__.py` to import and expose `fetch_historical` and `fetch_period` under a common namespace.
4. **Unit Tests**: Write tests in `tests/data/test_nse_eod_adapter.py` using mocked responses or VCR cassettes.
5. **Documentation**: Add a section to the eqats docs (e.g., `docs/data_sources/nse_eod.md`) detailing installation, usage examples, and limitations.
6. **CI/CD**: Ensure the new module passes linting and testing in the eqats CI pipeline.

## Benefits
- Direct access to authoritative NSE EOD data for Indian equities.
- Simple pandas‑native output eliminates extra transformation steps.
- Enables eqats users to backtest and trade NSE‑listed stocks without building a custom scraper.

## Limitations
- Only end‑of‑day data; no intraday, real‑time, or tick‑level data.
- Currently limited to equity instruments; derivatives, indices, and other securities are not supported (per the repository’s TODO).
- Reliant on the NSE website; changes to their HTML structure could break the fetcher.

By following this blueprint, eqats can quickly incorporate a reliable NSE EOD data source, expanding its coverage of Indian markets while leveraging existing signal, execution, and risk components.