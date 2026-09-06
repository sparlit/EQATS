# Integration Blueprint: Fund Forge → eqats

## Overview
Fund Forge is a Rust-based trading engine focused on backtesting, live trading, and charting. Its strongest assets are a flexible data server, a clean strategy abstraction, and a clear separation between strategy logic and execution. These components can be adopted by eqats to enhance its data ingestion, strategy development, and execution pipelines.

## Data Engine Integration
- **Historical Data Server**: Reuse `ff_data_server` (or a lightweight fork) to provide automatic download of free historical data from Rithmic, Oanda, and future Bitget/DataBento feeds. eqats can point its data-loader to the server's HTTP/WebSocket endpoints.
- **Multi-Broker, Multi-Symbol Streams**: Adopt the server's ability to handle multiple symbols and brokers concurrently, enabling eqats to run heterogeneous strategies without custom multiplexing code.
- **Candle Data Model**: Consider migrating eqats' internal candle representation to the Fund Forge base type (or its planned DailyCandles/WeeklyCandles refactor) to benefit from a unified resolution-agnostic design.
- **Configuration**: Use the existing setup guides (RITHMIC_SETUP.md, OANDA_SETUP.md) as templates for eqats' broker-specific credential handling.

## Signal & Execution Logic Integration
- **Strategy Abstraction**: Import the `ff_standard_lib/src/strategies` traits (e.g., `Strategy`, `Indicator`) into eqats' strategy crate. This gives eqats plug-and-play indicators and a standardized `on_tick`, `on_bar` interface.
- **Backtesting Reuse**: Leverage Fund Forge's backtesting harness (found in `ff_tests`) to validate eqats strategies against the same historical data used by the server.
- **Live Trading Adapter**: Wrap eqats' order-execution module with the Rithmic/Oanda client code from Fund Forge to gain immediate live-trading capability while maintaining eqats' risk layer.
- **Modular Strategy Deployment**: Follow Fund Forge's pattern of running each strategy as an isolated binary, communicating via a shared GUI or IPC, to allow eqats strategies to be started/stopped independently.
- **GUI Inspiration**: Examine the planned Rust Iced GUI for charting and discretionary trading; eqats can adopt similar components for its own UI.

## Risk Engineering Integration
- **Pre-Order Risk Checks**: Insert a risk-validation layer (position limits, max-drawdown, stop-loss) between the strategy's signal output and the Fund Forge execution client, mirroring the advice to set trader-side risk rules on the Rithmic gateway.
- **Exposure Monitoring**: Use eqats' existing risk engine to compute real-time exposure across symbols and brokers; expose these metrics via the same telemetry channels that Fund Forge uses for logging.
- **Risk Configuration**: Borrow Fund Forge's configuration pattern (command-line flags like `--rithmic "0"`/`"1"`) to let users toggle between test and live modes with associated risk profiles.

## Implementation Steps
1. **Data Layer** – Clone `ff_data_server`, strip unused broker code, expose a simple REST/WS endpoint for historical candles; integrate with eqats' data manager.
2. **Strategy Layer** – Add the Fund Forge strategy traits as a dependency; rewrite existing eqats strategies to implement these traits, reusing the indicator library.
3. **Execution Layer** – Create a thin adapter that translates eqats' order objects to Fund Forge's Rithmic/Oanda clients; enable the adapter only in live mode.
4. **Risk Layer** – Implement pre-order risk checks that call eqats' risk manager before passing orders to the adapter.
5. **Testing** – Run existing `ff_tests` strategies against eqats' data feed to ensure parity; then run eqats strategies through Fund Forge's backtesting harness.
6. **GUI (Optional)** – If eqats desires a charting UI, prototype with Rust Iced using Fund Forge's GUI work as a reference.

## Considerations
- Fund Forge is marked as "unstable" and "for development and testing only"; any production use should involve thorough auditing of the networking and order-sending code.
- The live-trading functionality for Oanda is incomplete; prioritize Rithmic or eqats' existing broker adapters for live deployment.
- Future refactors (e.g., removing resolution property from candle types) should be tracked to avoid breaking changes when syncing with upstream Fund Forge.
