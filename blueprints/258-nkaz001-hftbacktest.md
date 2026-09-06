# Integration Blueprint for hftbacktest Features into eqats

## Overview
The hftbacktest repository provides a high‑fidelity backtesting framework that models latency, order‑book depth, and queue position. Its core strengths—tick‑by‑tick replay, Level‑2/Level‑3 order‑book reconstruction, Numba‑accelerated strategy logic, and a Rust live‑trading bot—map directly onto the three eqats domains.

## Data Engines
- **Market‑data ingestion**: Support for Level‑2 (Market‑By‑Price) and Level‑3 (Market‑By‑Order) feeds, enabling eqats to ingest raw tick data from Binance, Bybit, or other exchanges and reconstruct the full order book.
- **Tick‑by‑tick replay**: Configurable simulation clock that can advance by a fixed interval or on each message, giving eqats deterministic control over time‑step granularity.
- **Latency modeling**: Pluggable feed‑ and order‑latency models (built‑in or custom) that can be applied to timestamp eqats’ signal generation and order submission.
- **Multi‑asset/multi‑exchange**: Ability to run simultaneous backtests across several symbols and venues, facilitating cross‑asset strategy research in eqats.
- **Data preparation utilities**: Documentation and example scripts for converting exchange‑provided CSV/WebSocket streams into the internal format used by hftbacktest.

## Signal & Execution Logic
- **Numba‑JIT strategy core**: Strategies are written as `@njit` functions that receive a lightweight `hbt` handle, allowing eqats to compile Python‑logic to native speed without leaving the Python ecosystem.
- **Signal construction**: Access to best bid/ask, tick size, lot size, mid‑price, and user‑defined indicators (forecast, volatility, risk) directly inside the JIT loop.
- **Order management**: Functions such as `clear_inactive_orders`, price‑tick alignment (`np.round(price/tick_size)`), and order‑quantity sizing (`notional_qty / mid_price / lot_size`) provide a ready‑to‑use execution template.
- **Live‑trading bot**: The same strategy code can be deployed to Binance Futures and Bybit via a Rust‑based bot, enabling eqats to move from backtest to production with zero code change.
- **Extensibility**: Users can substitute their own latency, queue, or pricing models, making it straightforward to plug eqats‑specific risk or execution logic.

## Risk Engineering
- **Position‑aware risk**: Built‑in position tracking (`hbt.position(asset_no)`) and simple risk scaling (`risk = (c + volatility) * position`) illustrate how eqats can incorporate real‑time P&L‑based risk adjustments.
- **Notional limits**: Parameters like `max_notional_position` and `notional_qty` show how to enforce exposure caps and order‑size limits.
- **Dynamic spread scaling**: Half‑spread calculation (`half_spread = (c + volatility) * hs`) demonstrates volatility‑adjusted liquidity taking.
- **Order‑queue awareness**: The fill simulation that respects queue position can be leveraged by eqats to model slippage more accurately when sizing orders.
- **Custom risk models**: The framework’s pluggable latency and queue models extend to risk, allowing eqats to inject VaR, CVaR, or margin‑check modules.

## Integration Steps
1. **Wrap the hbt handle**: Create an eqats adapter that exposes `depth`, `position`, `elapse`, `clear_inactive_orders`, etc., mirroring the hbt API.
2. **Convert strategy to Numba**: Port existing eqats signal functions into `@njit` kernels, using the adapter for market‑data access.
3. **Plug latency models**: Feed eqats’ latency estimates into hbt’s feed‑latency and order‑latency model slots.
4. **Enable multi‑asset**: Run multiple adapter instances, each bound to a different symbol/exchange, coordinated by a higher‑level eqats orchestrator.
5. **Live deployment**: Compile the same Numba kernel into the Rust bot (via PyO3 or similar) or re‑implement the logic in Rust, targeting Binance Futures/Bybit as already supported.
6. **Risk module injection**: Replace the simple risk line with eqats’ risk engine, feeding position and volatility into the adapter’s `risk` output.

## Expected Benefits
- **Accuracy**: Latency and queue‑aware fill simulation reduces the gap between backtest and live performance.
- **Speed**: Numba JIT enables microsecond‑scale strategy iteration, suitable for high‑frequency research.
- **Unified codebase**: One strategy implementation serves both backtest (Python) and live trading (Rust), lowering maintenance overhead.
- **Scalability**: Multi‑asset/multi‑exchange support aligns with eqats’ goal of cross‑venue arbitrage and market‑making.
- **Risk realism**: Position‑scaled risk and dynamic spread modeling give eqats a more truthful risk‑adjusted return estimate.
