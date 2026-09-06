# Integration Blueprint for pm-hftbacktest into eqats

## Overview
The pm-hftbacktest repository provides a high‑frequency backtesting framework for Polymarket prediction markets, built with a Rust core and Python/Numba bindings. Its key strengths are tick‑level market‑data ingestion, a flexible strategy API, and built‑in fee/position tracking.

## Data Engines
- **Polymarket L2 & Trade ingestion**: Functions `polymarket_to_hbt` convert Parquet L2 and trade data from pmdata.dev into the internal hbt order‑book format.
- **Tick‑level order‑book reconstruction**: The backend maintains a full depth book with tick size precision, enabling micro‑structure simulations.
- **Storage‑agnostic loading**: Uses pandas `read_parquet` with `storage_options` for API‑key authenticated downloads, which can be swapped for eqats’ data lake connectors.

## Signal & Execution Logic
- **Trigger‑based entry**: Example `endgame_trading` activates on mid‑price crossing user‑defined up/down thresholds.
- **One‑time order submission**: Flags `submitted_once` and `stop_submitted` prevent duplicate orders within a regime.
- **Stop‑loss logic**: Dynamically computes stop prices based on best bid/ask and a tick‑size offset, submitting opposite‑side orders to flatten position.
- **Order management APIs**: `submit_buy_order`, `submit_sell_order`, `clear_inactive_orders`, and time‑advance via `elapse`.
- **Recorder integration**: `Recorder` captures snapshots of the backtest state for post‑analysis.

## Risk Engineering
- **Fee modeling**: `binary_fee_model` allows setting maker/taker rebates/fees (e.g., maker ‑0.014, taker 0.07) directly on the asset.
- **Position monitoring**: `hbt.position(asset_no)` provides real‑time net exposure, used for stop‑loss triggers.
- **Order inactivation clearing**: `clear_inactive_orders` removes stale orders, reducing latency‑induced risk.
- **Risk‑aware stop submission**: Stop orders are priced inside the valid tick range and respect the book’s best bid/ask, limiting slippage.

## Integration Steps for eqats
1. **Data Layer** – Wrap `polymarket_to_hbt` in eqats’ ingestor to pull L2/trade Parquet from pmdata.dev (or eqats’ internal storage) and feed the resulting order‑book objects into eqats’ market‑data engine.
2. **Strategy Layer** – Expose the `endgame_trading` logic as a template strategy class in eqats, substituting the Numba‑jitted function with eqats’ signal framework (e.g., using pandas‑based indicators or custom Numba kernels).
3. **Execution Layer** – Map `submit_buy_order`/`sell_order` calls to eqats’ order‑gateway interface, preserving the GTC/LIMIT flags and order‑ID generation logic.
4. **Risk Layer** – Incorporate the binary fee model into eqats’ risk‑engine to compute PnL with maker/taker rebates, and reuse the position‑checking and stop‑logic as a risk‑module template.
5. **Testing & Validation** – Run the provided example end‑to‑end within eqats’ backtest harness, comparing equity curves and trade logs to ensure parity.

## Expected Benefits
- Access to tick‑level Polymarket data without building a custom parser.
- Ready‑made, low‑latency order‑book simulation that can be plugged into eqats’ vectorized backtester.
- A clear pattern for trigger‑based, single‑submit strategies with embedded stop‑loss, accelerating strategy research.
- Transparent fee and position‑risk controls that align with eqats’ existing risk‑engineering practices.