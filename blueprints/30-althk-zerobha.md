# Integration Blueprint: Zerobha Features into eqats

## 1. Data Engines
- Replace eqats market‑data layer with Zerobha’s Kite Ticker client (Go) to stream live ticks.
- Plug the custom candle aggregation engine into eqats’ candle builder interface to produce 5‑minute (or user‑defined) candles.
- Use the `cmd/histdl` utility to download historical intraday candles from Kite and store them in eqats’ historical data format (e.g., Parquet/CSV) for backtesting.
- Adapt the Python stock‑selection pipeline (`scripts/build_watchlist.py`) as a pre‑trade watchlist generator: run it before market open to populate eqats’ universe with sector‑momentum stocks filtered by industry and ranked by beta + relative strength.
- Integrate the pre‑market filter (`scripts/premarket_filter.py`) as a liquidity/volatility gate that feeds the watchlist into eqats’ signal engine.

## 2. Signal & Execution Logic
- Wrap the ORB strategy (`pkg/strategy`) as an eqats signal module: expose functions `Init`, `OnTick`, `OnCandle` that compute RSI/ADX, ATR range, candle‑body strength, volume surge, gap, VWAP distance and emit long/short signals.
- Incorporate the structural stop‑loss logic from Zerobha into eqats’ risk‑aware order‑ticket builder.
- Reuse the backtesting engine (`cmd/backtest`) by adapting its CSV‑input handler to read eqats’ historical candle format; keep the cost‑bps slippage model.
- Leverage the existing Zerodha broker adapter (`pkg/broker`) for order routing; eqats can swap in the Sim adapter for paper‑trading.
- The live‑trading entry point (`cmd/trader/main.go`) shows how to wire config, data engine, strategy, and risk module – eqats can follow the same composition pattern.

## 3. Risk Engineering
- Import the risk‑management constants (daily max loss, max trades per day, auto‑square‑off times) into eqats’ risk‑policy configuration (TOML or YAML).
- Implement a daily P&L tracker that blocks new signals once the loss limit is hit, mirroring Zerobha’s behavior.
- Add a time‑based rule generator that cancels new entry signals after 15:05 IST and triggers an auto‑square‑off of all MIS/GTT positions at 15:13 IST.
- Expose these limits via eqats’ risk‑engine API so they can be tuned per‑instrument or per‑account without code changes.

## 4. Deployment & Configuration
- Keep the existing `config.toml` structure; map its sections (`strategy`, `csv_file`, `limit`, `timeframe`, `api_key`, `api_secret`) to eqats’ configuration schema.
- Provide a Dockerfile that builds the Go binary and copies the Python watchlist scripts, enabling a single‑container deployment similar to Zerobha.
- The web dashboard (`internal/web`) can be reused as‑is or replaced by eqats’ monitoring UI; it serves live fund, position, and order data on `:8080`.

## Expected Benefits
- Instant access to a proven ORB strategy with advanced intraday filters.
- Robust, low‑latency tick‑to‑candle pipeline tuned for NSE.
- Automated sector‑based watchlist generation reduces manual curation.
- Comprehensive risk controls protect against overnight exposure and intraday blow‑ups.
- Reusable backtesting and historical‑download tools shorten strategy‑validation cycles.
