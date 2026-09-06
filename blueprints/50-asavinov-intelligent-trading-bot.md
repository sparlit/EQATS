# Integration Blueprint for eqats: Intelligent Trading Bot

## 1. Data Engines
- **Historic data download**: Use the `scripts.download` module to pull OHLCV data from Binance (via ccxt) and Yahoo Finance. In eqats, replace the existing data loader with this module, configuring `data_sources` and `column_prefix` to avoid name clashes.
- **Time‑aligned merging**: The `scripts.merge` script aligns multiple feeds on timestamps and fills gaps to produce a continuous raster. Integrate this as a preprocessing step before feature generation, ensuring eqats’ unified table matches the bot’s offline/online feature consistency requirement.
- **Feature engineering pipeline**: The `scripts.features` script computes derived features via user‑defined Python functions (technical indicators, custom logic). eqats can adopt this plug‑in feature registry, allowing users to register functions that are automatically applied in both batch training and live inference.
- **Frequency handling**: The bot supports arbitrary pandas frequencies (`freq` in config). eqats can expose the same `freq` parameter to its data engine, letting users switch between 1‑min, 1‑hour, 1‑day rasters without code changes.
- **Label generation**: `scripts.labels` creates target variables for ML models. Reuse this to produce eqats‑compatible label columns (e.g., future return bins) during offline training.

## 2. Signal & Execution Logic
- **Intelligent indicator scoring**: The bot outputs a normalized score in [-1, +1] indicating expected price movement. eqats can incorporate this as a signal generator module, feeding the score into its strategy evaluator.
- **Threshold‑based triggers**: When the score exceeds user‑defined thresholds, buy/sell signals are emitted (e.g., `Indicator: +0.12 ↑ BUY ZONE`). eqats can map these thresholds to its order‑execution hooks, enabling automatic market or limit orders.
- **Customizable notification/actions**: The `scripts.signals` and `scripts.output` modules allow users to define Python callbacks for Telegram, API endpoints, database logging, or real transaction execution. eqats should expose a similar callback interface, letting users plug in their own notifiers or executors.
- **Backtesting framework**: The bot’s offline pipeline includes periodic retraining and performance measurement. eqats can reuse the `scripts.train`, `scripts.predict`, and `scripts.output` steps to run walk‑forward backtests, storing equity curves and metrics.
- **Trading service**: The online mode runs a service that loops on the configured frequency, fetches new data, runs feature generation, loads the latest model, computes the score, and triggers the notification callback. eqats can adopt this service skeleton, replacing the Telegram callback with its own order manager.

## 3. Risk Engineering
- The repository does not explicitly expose risk‑limit, position‑sizing, or monitoring components. Risk controls would need to be added externally (e.g., max‑drawdown limits, volatility‑based position sizing) around the signal‑execution layer.

## 4. Suggested Integration Steps
1. **Add data engine plugins**: wrap `download`, `merge`, `features`, `labels` as eqats‑compatible functions.
2. **Expose a config schema** matching the bot’s `config.json` (symbol, freq, data_folder, thresholds, notification callbacks).
3. **Implement a signal adaptor** that converts the bot’s indicator score into eqats’ signal object.
4. **Plug in execution callbacks**: map the bot’s Telegram/notifier functions to eqats’ order executor and logger.
5. **Run a backtest**: use the bot’s training/prediction scripts inside eqats’ walk‑forward framework to validate performance.
6. **Add risk layer**: overlay position sizing and stop‑loss logic on top of the execution adaptor.