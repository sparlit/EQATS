# Integration Blueprint for eqats: Upstox Python Data Layer

## Overview
The `upstox-python-data` repository provides a clean Python wrapper for Upstox market data (REST + WebSocket) and a simulated trading environment. Its modular design makes it a strong candidate for ingestion, signal generation, execution, and risk monitoring within the eqats quantitative trading framework.

## Data Engines Integration
- **Market Data Ingestion**: Replace eqats' current data fetcher with `upstox_data.py` functions (`get_spot`, `get_option_chain`, `fetch_daily_candles`, `fetch_intraday_candles`, `get_vix`, `get_pcr`, `get_max_pain`, `get_oi`, `get_fii_activity`, `get_dii_activity`). These provide real-time and historical data for NSE indices and F&O contracts.
- **WebSocket Streaming**: Use `MarketStreamer` from `upstox_websocket.py` to subscribe to LTP, depth, or option Greeks streams. Feed the ticks into eqats' tick handler or the `DataHeartbeat` cache for low‑latency LTP access.
- **Reference Data**: Instrument keys are defined in `INSTRUMENT_KEYS`; eqats can extend this dict for additional stocks/F&O by adding ISIN‑based keys and lot‑size/step configs.
- **Caching & Fallback**: `DataHeartbeat` offers a background LTP cache with REST fallback and spike detection (`check_spike`). eqats can wrap its own data manager around this to guarantee fresh prices and detect abnormal moves.

## Signal & Execution Logic Integration
- **Signal Generation**: Compute indicators (IV, Greeks, PCR, OI change, VIX) directly from the data engine outputs. Example: a volatility‑skew signal using IV from `get_option_chain` or a momentum signal from OI buildup (`get_oi_change`).
- **Order Execution**: Replace eqats' execution adapter with the `PaperBroker` class for simulation or adapt its logic to live orders. Key methods:
  - `place_order(...)` – sends an order with slippage model and margin validation.
  - `place_spread(...)` – atomic multi‑leg spread execution.
  - `close_position(...)` – exits with full cost breakdown.
  - `update_price(id, ltp)` – updates MFE/MAE from live ticks.
  - `set_sl_target(id, sl_pct, target_pct)` – attaches stop‑loss/target.
- **Slippage & Costs**: Integrate `slippage.py` (depth‑based model) and `costs.py` (NSE F&O charge calculator) into eqats' transaction cost analysis (TCA) module to produce realistic P&L estimates.
- **Examples**: The `examples/` folder provides ready‑to‑run scripts (`spot_price.py`, `option_chain.py`, `live_ticks.py`, `candles.py`, `sentiment.py`, `paper_trading.py`) that can be adapted as eqats tutorials or unit tests.

## Risk Engineering Integration
- **Position & Capital Tracking**: `PaperBroker.get_portfolio()` returns a snapshot of positions, P&L, capital usage, and lot consumption. eqats can expose this via its risk dashboard.
- **Margin Validation**: `get_order_margin` and internal margin checks in `PaperBroker` ensure orders do not exceed available margin; eqats can call this pre‑trade.
- **Stop‑Loss / Target**: `set_sl_target` attaches percentage‑based SL/TP; eqats can extend this to trailing stops or volatility‑based exits.
- **Spike Detection**: `DataHeartbeat.check_spike` flags abrupt price moves; eqats can trigger risk‑off logic or volatility scaling.
- **Limits**: `PaperBroker` constructor accepts `max_lots` and `max_positions`; eqats can map these to its global risk limits.
- **Cost Awareness**: By using `costs.py` for every trade, eqats can compute real‑time transaction cost impact on risk metrics (e.g., VaR after slippage).

## Implementation Steps
1. **Dependency Setup** – Add `requests`, `websocket-client`, `protobuf`, `python-dotenv` to eqats' `requirements.txt`.
2. **Copy Core Modules** – Place `upstox_data.py`, `upstox_websocket.py`, `heartbeat.py`, `paper_broker.py`, `slippage.py`, `costs.py` into eqats' `data_feeds/upstox` package.
3. **Adapter Layer** – Write thin wrapper classes that expose eqats‑standard interfaces (`MarketDataProvider`, `ExecutionEngine`, `RiskManager`) delegating to the Upstox modules.
4. **Configuration** – Use `.env` for the Upstox analytics token; eqats' config system can read the same variable.
5. **Testing** – Run the provided examples to verify data flow; then replace eqats' mock data provider in unit tests with the Upstox adapter.
6. **Go Live** – Switch `PaperBroker` to a live execution adapter (e.g., reuse its order‑building logic but send orders via Upstox API) once validation passes.

## Expected Benefits
- Low‑latency, reliable tick data via WebSocket with auto‑reconnect.
- Rich options analytics (Greeks, IV, PCR, max pain) without extra subscriptions.
- Realistic simulation that mirrors live slippage, fees, and margin requirements.
- Unified risk controls (position limits, margin checks, SL/TP, spike detection) already built‑in.
- Rapid prototyping of new strategies using the example scripts as starting points.
