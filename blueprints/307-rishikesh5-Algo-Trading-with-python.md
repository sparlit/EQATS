# Integration Blueprint for eqats

## Overview
The `Algo-Trading-with-python` repository provides a simple intraday SMA‑crossover bot that pulls live and historical NSE data from Zerodha’s Kite platform, calculates SMA5 and SMA20, and places buy/sell orders every five minutes. Although the code is minimal, it demonstrates a complete data‑pipeline → signal → execution loop that can be adapted into the eqats framework.

## Data Engines Integration
- **Market Data Source**: Replace the custom KiteConnect calls with eqats’ abstracted `DataEngine` interface. Implement a `KiteDataEngine` plugin that fetches live tick data and historical OHLCV (last 100 days) using the same `kiteconnect` library.
- **Storage & Pre‑processing**: Store incoming candles in a rolling pandas DataFrame (or eqats’ `TimeSeriesBuffer`) to enable efficient SMA calculation. The existing practice of converting raw API responses to `pandas.DataFrame` can be wrapped in eqats’ `DataFrameAdapter`.
- **Update Frequency**: The repo’s 5‑minute loop maps directly to eqats’ `BarSubscription` with a 5‑minute resolution.

## Signal & Execution Logic Integration
- **Signal Module**: Encapsulate the SMA crossover logic into a `SMASignal` class that subscribes to the `DataEngine` and emits `Long` when `SMA5 > SMA20` and `Short` when `SMA5 < SMA20`. This mirrors the existing condition but plugs into eqats’ `SignalEngine`.
- **Execution Module**: Use eqats’ `ExecutionEngine` to route signals to broker‑agnostic order objects. The existing `kiteconnect.place_order` calls become a `KiteExecutor` plugin that translates eqats’ `Order` (type, quantity, side) into Kite API requests.
- **Loop & Timing**: Replace the manual `while True: time.sleep(300)` with eqats’ `Scheduler` which triggers the signal evaluation at each bar close.

## Risk Engineering Integration
- The repository does not contain risk‑management components (position sizing, stop‑loss, max drawdown, etc.). To make the strategy production‑ready within eqats, add a `RiskEngine` layer that:
  1. Calculates position size based on volatility or equity risk percent.
  2. Applies per‑trade stop‑loss and take‑profit levels.
  3. Enforces max daily loss and max concurrent positions.
  These can be implemented as eqats plugins without altering the core SMA signal.

## Conclusion
By wrapping the existing KiteConnect data fetch, SMA calculation, and order placement into eqats’ modular domains (Data Engines, Signal & Execution, Risk Engineering), the simple intraday strategy becomes a reusable, testable component. Further enhancements (multiple symbols, alternative indicators, advanced risk controls) can be layered on top of this foundation.