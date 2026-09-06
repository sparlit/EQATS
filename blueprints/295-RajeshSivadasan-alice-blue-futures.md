# Integration Blueprint: alice-blue-futures -> eqats

## Summary
The repository provides a ready-made Alice Blue broker integration with:
- Real-time market data ingestion via the Alice Blue Python SDK.
- Configurable Supertrend + RSI signal generation on 3-minute and 6-minute bars.
- Telegram-based runtime control (start/stop, SL/MTM adjustment, log retrieval).
- Simple ini-file driven parameterisation for capital, lot size, stop-loss, etc.

## How to Map to eqats Domains

### Data Engines
- **Market Data Feed**: Replace the Alice Blue API calls with eqats’ universal data-engine adapter (WebSocket/REST) to pull tick/OHLCV for NSE & MCX symbols.
- **Local Storage**: The repo’s log/ and data/ folders can be mapped to eqats’ partitioned parquet lake; write raw ticks and processed bars to the lake via eqats’ storage connector.
- **Background Telegram Listener**: Re-use as an external control plane; eqats can expose a similar RPC/Telegram bot via its control-plane service.

### Signal & Execution Logic
- **Strategy Core**: The Supertrend + RSI logic lives in ab.py/ab_options.py. Extract the indicator calculations (Supertrend, RSI) and signal generation into a pluggable Strategy class that eqats can load via its strategy registry.
- **Order Execution**: The broker-specific order placement (Alice Blue place_order) can be wrapped by eqats’ execution adapter, translating eqats’ order objects (side, quantity, price, product type) to Alice Blue calls.
- **Telegram Control**: Map telegram commands (/start, /stop, /set_sl, /set_mtm) to eqats’ control-plane API endpoints, allowing remote strategy lifecycle management without modifying the core logic.

### Risk Engineering
- **Capital & Position Sizing**: The ab.ini/ab_options.ini parameters for capital, lot size, and max-risk can be read by eqats’ risk-engine module to compute position size dynamically.
- **Stop-Loss & MTM Limits**: The repo’s manual SL/MTM handling via telegram can be replaced by eqats’ automated risk limits (max-loss per trade, daily drawdown, trailing stop) enforced by the risk-engine.
- **Leverage & Margin Checks**: Although not explicit in the repo, eqats can add margin-validation before sending orders, using the same account-info endpoints that the Alice Blue SDK provides.

## Integration Steps
1. Create an eqats data-engine connector for Alice Blue (inherit from eqats.data.BaseFeed).
2. Implement an eqats execution adapter (eqats.exec.BaseBroker) that calls the Alice Blue SDK methods.
3. Port the Supertrend/RSI indicator code into a reusable eqats.signal.indicators module and reference it from a new strategy class (SupertrendRSIStrategy).
4. Expose a thin Telegram bot (or reuse eqats’ control-plane) that mirrors the existing bot’s command set, linking each command to eqats’ control-plane APIs (/strategy/start, /strategy/stop, /risk/set_sl, etc.).
5. Migrate ini-file parameters to eqats’ configuration store (YAML/DB) and bind them to the risk-engine’s sizing and limit rules.
6. Run the strategy within eqats’ orchestration layer (e.g., Kubernetes cronjob or long-running pod) scheduled at 8:59:30 AM / 9:14:00 AM as in the original crontab.
7. Monitor & log: Direct logs to eqats’ logging pipeline (ELK or Loki) and store raw/processed data in the data lake for backtesting.

## Expected Benefits
- Re-use of a proven, simple trend-following strategy while gaining eqats’ scalable data-engine, risk-engine, and execution abstraction.
- Centralised risk controls (position sizing, max-loss, drawdown) replace ad-hoc telegram adjustments.
- Ability to run the same strategy across multiple brokers by swapping the execution adapter.
- Enhanced observability and auditability through eqats’ unified logging and metrics.

## Caveats
- The original code warns that the Alice Blue API may be outdated; the integration should verify current endpoint contracts and update the SDK calls accordingly.
- The repo focuses on option-buying only and futures with a fixed strategy; extending to more complex option Greeks or multi-leg strategies would require additional eqats modules.
- No explicit handling of slippage or order-type (limit vs market) is present; eqats’ execution adapter should enforce the desired order type and apply slippage models.
