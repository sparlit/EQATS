# Integration Blueprint for top-gainers-and-losers-nse into eqats

## Overview
The repository provides a simple Python script that pulls the day's top gainers and losers from the National Stock Exchange (NSE) using the `nsetools` library, enriches each symbol with OHLC, previous close, volume and last traded price (LTP), and writes the results to CSV files. It also exposes an in‑memory list (`stock_list`) containing just the ticker symbols.

## Data Engine Integration
- **Market Data Ingestion**: Replace eqats’ current NSE data fetcher with the script’s `nsetools` calls to obtain real‑time top‑mover lists.
- **Storage**: The CSV output can be directed to eqats’ data lake (e.g., `data/raw/nse_top_movers_YYYYMMDD.csv`) for downstream analysis or back‑testing.
- **In‑Memory Symbol List**: The `stock_list` can be consumed directly by eqats’ universe builder to limit the trading universe to the most active stocks each day.

## Signal & Execution Logic
- **Momentum Signal**: Treat the top gainers list as a long signal and the top losers list as a short signal. eqats can generate orders by:
  1. Pulling the latest CSV (or `stock_list`) at market open.
  2. Assigning equal weight or volatility‑scaled weights to each symbol.
  3. Sending market‑on‑open or VWAP orders via eqats’ execution adapter.
- **Signal Filtering**: Combine the raw list with eqats’ existing factor models (e.g., volatility, liquidity) to refine the signal before execution.

## Risk Engineering
- The source repo does not contain risk‑limits, position‑sizing, or monitoring logic. Risk controls should be applied at the eqats level:
  - Apply max position size per symbol.
  - Enforce sector/industry caps.
  - Use eqats’ risk engine to monitor P&L and enforce stop‑losses on the generated positions.

## Implementation Steps
1. **Wrapper Module**: Create `eqats/data_engines/nse_top_movers.py` that wraps the original script, exposing a function `get_top_movers(date)` returning a DataFrame with columns `[symbol, open, high, low, prev_close, volume, ltp]` and also the `stock_list`.
2. **Scheduler**: Integrate the wrapper into eqats’ daily pre‑market job to populate the universe cache.
3. **Signal Module**: Add `eqats/signals/momentum_top_movers.py` that reads the universe and emits long/short signals.
4. **Risk Checks**: Ensure the signal passes through eqats’ risk checks before order submission.
5. **Testing**: Run a paper‑trading simulation to validate turnover and performance.

## Benefits
- Quick access to NSE’s most active stocks without building a custom scraper.
- Ready‑to‑use CSV logs for audit and research.
- Minimal dependency overhead (only `nsetools`).

## Caveats
- Relies on `nsetools` which may be subject to NSE API changes; monitor for updates.
- The script provides end‑of‑day data; for intraday strategies, a real‑time websocket would be needed.