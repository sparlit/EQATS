# Integration Blueprint for eqats

## Overview
The AI‑trader repository provides a mature, production‑grade intraday options trading stack built for NSE F&O. Its core components can be lifted and adapted into the eqats framework to accelerate data handling, signal generation, and risk control.

## 1. Data Engines
- **Ingestion**: Replace or augment eqats’ current market‑data adapter with the TrueData WebSocket collector (`scripts/collect_ticks.py`). The collector subscribes to NIFTY‑I futures and the ATM ±3 strike option chain (14 contracts), automatically re‑subscribing when the underlying moves >100 pts. Historical backfill can be performed via the REST endpoint to populate a TimescaleDB hypertable, mirroring eqats’ preferred time‑series store.
- **Storage**: Leverage the existing TimescaleDB schema (tick table, 1‑minute candle table) – eqats can map its own candle model to the same hypertables, enabling tick‑level replay without code changes.
- **Replay Engine**: The tick‑level backtest module re‑uses the live pipeline, guaranteeing that feature engineering, model inference, and risk checks behave identically in simulation and live mode. eqats can adopt this replay runner as a drop‑in replacement for its current backtester.
- **Caching**: The live price cache (`/tmp/td_live_prices.json`) refreshed each second provides a low‑latency lookup layer for UI components; eqats can expose a similar cache via an in‑memory Redis or shared dict.

## 2. Signal & Execution Logic
- **Feature Set**: Import the `features/` package to compute the 80 macro and 5 micro tick features per minute bar. These are fully compatible with pandas DataFrames and can be fed directly into eqats’ feature store.
- **ML Models**: Serve the pretrained XGBoost models (macro, micro, per‑strategy) and the Q‑learning RL exit agent via a lightweight inference service (e.g., FastAPI). eqats can call this service to obtain signal probabilities and exit actions, or retrain the models on its own data using the same training scripts.
- **Rule‑Based Strategies**: The three deterministic strategies (e.g., opening‑range breakout, volatility‑mean‑reversion, OI‑pressure) are implemented as pure functions returning a raw score. eqats can wrap these functions, multiply by the ML probability, and apply a threshold to generate final trade signals.
- **Execution**: The paper‑trading module (`paper_trading.py`) provides both manual and auto‑order placement hooks that interface with a broker adapter. eqats can replace its simulated order executor with this module, gaining live‑like order‑ticket management, position tracking, and a terminal‑style dashboard built with Next.js.
- **Dashboard**: The Next.js terminal UI offers real‑time panels for equity curve, open positions, option chain, and backtest results. eqats can embed these React components into its own web‑portal or run the dashboard side‑by‑side for monitoring.

## 3. Risk Engineering
- **Position Sizing**: Adopt the Kelly criterion calculator (`risk/kelly.py`) to dynamically adjust lot size based on win‑rate and payoff ratio estimated from recent trades.
- **Dynamic Stops & Targets**: Use the ATR‑based stop‑loss and target functions (`risk/stops.py`) that adapt to current volatility; integrate them into the order‑submission flow.
- **Trailing Stops**: Implement the trailing‑stop logic from `risk/trailing.py` to lock in profits as the option price moves favorably.
- **Regime Gating**: Apply the regime filter (e.g., high‑volatility or low‑liquidity blocks) from `risk/regime.py` to pause new signal generation when conditions are unfavorable.
- **Monitoring**: The real‑time P&L and drawdown checks built into the execution loop can be ported to eqats’ risk manager, ensuring that max‑loss per trade and daily loss limits are enforced before any order is sent.

## 4. Implementation Steps
1. **Data Layer** – Add the TrueData collector as an optional market‑data plugin; configure TimescaleDB connection parameters to match eqats’ existing DB.
2. **Feature Layer** – Copy `features/` into eqats’ `eqats/features` and expose a `compute_features(df)` function.
3. **Model Layer** – Serve XGBoost and RL models via a micro‑service; update eqats’ signal generator to call `/predict` and `/exit` endpoints.
4. **Strategy Layer** – Import the three rule‑based functions, combine with ML scores, and feed the result into eqats’ existing signal‑validation pipeline.
5. **Execution Layer** – Replace the paper‑trading executor with the AI‑trader paper‑trading module, linking it to eqats’ broker adapter.
6. **Risk Layer** – Integrate Kelly sizing, dynamic stops, trailing stops, and regime gating into eqats’ risk manager; reuse the provided utility functions.
7. **UI (Optional)** – Deploy the Next.js dashboard alongside eqats’ web‑app for enhanced visibility, or extract individual React charts (option chain, equity curve) for reuse.

## Expected Benefits
- **Speed to Market**: Tick‑level data pipeline and backtester eliminate months of engineering effort.
- **Model Quality**: Proven XGBoost + RL models give a strong baseline for strategy research.
- **Risk Discipline**: Kelly‑based sizing and adaptive stops reduce tail‑risk exposure.
- **Operational Visibility**: The terminal‑style dashboard provides real‑time insight into positions, P&L, and model performance.

By following this blueprint, eqats can rapidly evolve from a research prototype to a robust, live‑ready intraday options trading system that leverages battle‑tested components from the AI‑trader repository.