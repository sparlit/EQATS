# Integration Blueprint: PKScreener -> eqats

## Overview
PKScreener is a Python-based NSE stock screener offering 40+ built-in scanners, technical indicators, AI-driven predictions, chart-pattern detection, Telegram alerts, backtesting and scheduling capabilities. These capabilities can be leveraged to enrich eqats' data pipelines, signal generation, and risk management layers.

## 1. Data Engines
- **Market Data Ingestion**: PKScreener fetches real-time and historical OHLCV data for NSE equities via its `data_fetch` module (uses NSE API / Yahoo Finance). eqats can reuse this connector to populate its feature store with minute-, daily- and OHLCV-adjusted series.
- **Data Caching & Storage**: The screener caches downloaded symbols locally (pickle/CSV) to reduce latency. eqats can adopt a similar tiered cache (memory -> disk) for frequently scanned universes.
- **Pre-processing Pipeline**: Includes adjustment for splits, dividends, and conversion to uniform time-zone. eqats' data engine can plug this preprocessing step before feature calculation.
- **Fundamental & Alternative Data**: Modules for FII/DII holdings, mutual fund ownership, IPO lists, and dividend yields are already present; eqats can ingest these as alternative datasets.

## 2. Signal & Execution Logic
- **Scanner Library**: The 40+ built-in scanners (breakout, consolidation, VCP, NRx, ATR cross, etc.) are implemented as reusable functions that take a DataFrame and return boolean signals. eqats can import these as signal plugins.
- **Technical Indicator Suite**: RSI, MACD, CCI, ATR, PSAR, Aroon, etc., are calculated using pandas/ta-lib. eqats can replace its own indicator calculations with this tested suite.
- **Chart-Pattern Detection**: Head & Shoulders, Double Top/Bottom, Cup & Handle, Inside Bar, etc., are pattern-recognition algorithms that output pattern-specific scores. eqats can treat these as pattern-based signal generators.
- **AI/ML Signals**: Nifty prediction model, ML-based trend forecaster, and Lorentzian classifier are trained on historical data. eqats can import the trained models or retrain them on its own data pipeline.
- **Custom Piped Scanners**: Users can combine basic scanners via a pipe syntax (`scanner1 | scanner2`). eqats can expose a similar combinatorial DSL for strategy construction.
- **Telegram Alerting**: Real-time push of signals to Telegram channels/bots. eqats can integrate this as a notification channel for order-execution alerts.
- **Backtesting Engine**: The "Growth of 10k" module walks a strategy through historical data, computing equity curves, drawdowns, and win-rate. eqats can adopt this backtester as a reference or replace its own.
- **Scheduling & Automation**: Cron-job based scanning (daily, intraday) and on-demand Telegram bot allow timed signal generation. eqats can use the same scheduler (APScheduler) to trigger signal generation at market open/close.

## 3. Risk Engineering
- **Volatility-Based Stops**: ATR Trailing Stops and ATR Cross signals provide dynamic stop-loss levels keyed to market volatility. eqats can incorporate these stops into its risk-management module.
- **Position Sizing Hints**: Fair Value Buy Opportunities and volatility-contraction patterns (VCP) suggest optimal entry sizes based on price-fair-value deviation; eqats can map these to its Kelly-fraction or volatility-sizing logic.
- **Risk Monitoring Alerts**: Telegram alerts for breach of ATR-based stop or for high-RSI/MFI conditions can be repurposed as risk-limit warnings.
- **Drawdown Analysis**: Built-in backtesting includes max-drawdown calculation; eqats can reuse this reporting for post-trade risk review.
- **Exposure Limits**: The screener allows filtering by market-cap, sector, and FII/DII ownership, enabling pre-trade exposure caps that eqats can enforce via its risk engine.

## Integration Steps
1. **Data Layer** – Wrap PKScreener's `data_fetch` and caching functions into eqats' `DataIngestor` interface; store raw OHLCV in eqats' time-series database.
2. **Signal Layer** – Create an `SignalAdapter` that loads PKScreener's scanner functions, indicator calculators, and pattern detectors as eqats signal plugins; expose a YAML/JSON config to enable/disable each.
3. **Execution Layer** – Use PKScreener's Telegram notifier as eqats' `AlertPublisher`; connect to eqats' order-management system for auto-execution of high-confidence signals.
4. **Risk Layer** – Map ATR-based stop-loss and fair-value sizing logic to eqats' `RiskManager`; configure limits and drawdown alerts.
5. **Testing** – Run PKScreener's backtesting module on eqats' historical data to validate signal performance; adjust parameters and re-train ML models within eqats' training pipeline.
6. **Deployment** – Dockerize the adapted components (PKScreener already provides Docker images) and deploy alongside eqats' microservices via Kubernetes.

## Expected Benefits
- Accelerated feature development by re-using a proven scanner/indicator library.
- Enhanced signal diversity (pattern-recognition, AI, custom pipes) without building from scratch.
- Real-time alerting via Telegram reduces latency between signal generation and execution.
- Robust risk controls grounded in ATR-based volatility and fair-value metrics.
- Shared backtesting framework ensures consistency between research and production.

## Caveats
- PKScreener is NSE-focused; eqats may need to adapt data connectors for other exchanges.
- Some ML models are trained on Indian market data; re-training may be required for eqats' target universes.
- Licensing: verify compatibility of PKScreener's open-source license with eqats' distribution.
