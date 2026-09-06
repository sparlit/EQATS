# Integration Blueprint: kuldeeepy/algo‑trader → eqats

## 1. Overview
The algo‑trader repository provides a regime‑aware intraday backtester for NSE stocks. Its core strengths are:
- A robust data pipeline that fetches candles from yfinance or Upstox and caches them in SQLite.
- A three‑stage workflow: opening‑window regime classification → strategy selection → cost‑aware backtest.
- A lightweight FastAPI backend serving results to a Vite/React frontend with lightweight‑charts.

These components can be lifted into the eqats project to add regime‑dependent strategy allocation, improve data handling, and introduce realistic cost modeling.

## 2. Data Engines Integration

### 2.1 Market Data Ingestion
- Reuse `backend/upstox_setup.py` (or a thin wrapper) to obtain an Upstox access token and fetch 5‑minute candles.
- Fallback to `yfinance` for intraday data when no token is available, mirroring the existing logic.
- Implement an `InstrumentListDownloader` that pulls the NSE instrument list once and stores it locally (as the repo does).

### 2.2 Caching & Storage
- Adopt `backend/store.py` as a SQLite cache layer: table `candles(symbol, timestamp, open, high, low, close, volume)`.
- On first request, download and persist candles; subsequent runs read from the cache, dramatically speeding up research loops.
- Expose a simple API (`get_candles(symbol, start, end)`) that eqats’ data engine can call.

### 2.3 Implementation Steps
1. Copy `store.py`, `upstox_setup.py`, and the data‑fetching helpers into `eqats/data/`.
2. Add a configuration flag `USE_UPSTOX` that toggles the data source.
3. Ensure the cache directory (`eqats/data/`) is created on first run.
4. Write unit tests that verify cache hit/miss behavior.

## 3. Signal & Execution Logic Integration

### 3.1 Regime Classification
- Import `backend/regime.py` (or refactor into a reusable module) that computes opening‑range metrics (e.g., range size, volume imbalance) and returns one of `{trending, sideways, high_vol}`.
- Hook this into eqats’ pre‑market analysis step so each trading day receives a regime label before strategy selection.

### 3.2 Strategy Selector
- Use `backend/selector.py` as a template: train a gradient‑boosting model (e.g., XGBoost or LightGBM) on historical regime‑strategy performance.
- Persist the trained model (pickle or joblib) and load it at runtime to predict the best strategy for the day’s regime.
- Allow eqats to override the selector with a fixed strategy for ablation studies.

### 3.3 Strategy Library
- Import the four strategies from `backend/strategies.py`:
  * Opening Range Breakout (ORB)
  * VWAP Reversion
  * Gap Fade
  * Momentum
- Wrap each strategy in a common interface (`generate_signal(candles) -> signal`) so eqats’ execution engine can call them uniformly.

### 3.4 Backtest Engine
- Reuse `backend/engine.py` for indicator calculations (e.g., VWAP, ATR) and `backend/backtest.py` for the regime‑aware loop:
  1. Determine regime.
  2. Select strategy via selector.
  3. Generate signals, apply position sizing from risk module.
  4. Simulate order execution with slippage and commission.
- Integrate this loop into eqats’ existing backtest runner, replacing the single‑strategy pass with the regime‑aware pass.

### 3.5 API / Frontend (optional)
- If eqats wishes to expose a web UI, copy `backend/api.py` (FastAPI) and the `frontend/` Vite+React app.
- Set `VITE_API_BASE` to point to the eqats backend; enable CORS via `ALGO_CORS_ORIGINS`.
- This provides an interactive regime‑strategy visualisation similar to the live demo.

## 4. Risk Engineering Integration

### 4.1 Position Sizing & Risk Limits
- Adopt `backend/risk.py` which implements:
  * Volatility‑adjusted position sizing (e.g., fixed fractional risk based on ATR).
  * Daily loss cap (max % of equity allowed to lose in a session).
  * Per‑trade max risk.
- Expose a function `calculate_size(equity, stop_loss_price, entry_price)` that eqats can call before issuing an order.

### 4.2 Cost Modeling
- Copy the slippage model (4 bps) and fixed commission (₹20 per order) from the backtest loop.
- Ensure every simulated trade subtracts these costs from gross P&L, yielding net performance metrics.
- Make the slippage and commission values configurable via eqats’ config file.

### 4.3 Implementation Steps
1. Add `risk.py` to `eqats/risk/`.
2. Update eqats’ order‑generation pipeline to call `risk.calculate_size` and apply cost adjustments.
3. Add unit tests verifying that position size respects the daily loss cap under various volatility scenarios.
4. (Optional) expose risk parameters through eqats’ strategy configuration UI.

## 5. Summary of Benefits
- **Regime‑aware allocation** improves strategy robustness by matching tactics to market conditions.
- **Efficient data pipeline** reduces redundant downloads and speeds up research iterations.
- **Realistic cost modeling** ensures that backtested performance reflects live‑trading feasibility.
- **Modular risk controls** give eqats tighter control over drawdowns and leverage.

By integrating the highlighted components, eqats gains a production‑grade, regime‑driven backtesting framework with minimal new development effort.