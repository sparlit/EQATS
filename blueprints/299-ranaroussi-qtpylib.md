# Integration Blueprint for QTPyLib Features into eqats

## Overview
QTPyLib provides a clean separation between market data handling (Blotter), strategy logic (Algo), and broker execution. These components can be mapped onto the eqats domains as follows.

## Data Engines
- **Blotter**: Run a persistent Blotter process that connects to Interactive Brokers (or other data feeds) and streams market data via ZeroMQ pub/sub.
- **Storage**: Market data (tick, bar, trade) is persisted to MySQL, enabling historical backtesting and research.
- **Resolution Flexibility**: Configure the Blotter with `--orderbook` to capture depth, or use tick/bar/time/volume based streams.
- **Async Architecture**: Non‑blocking event loop ensures low‑latency data delivery to multiple strategies.

**How to integrate into eqats**:
1. Replace or augment eqats’ current data ingestion layer with a QTPyLib‑style Blotter.
2. Use the MySQL schema (or adapt to eqats’ preferred store) for raw market data.
3. Leverage the ZeroMQ pub/sub to decouple data producers from consumers, allowing multiple eqats strategies to subscribe to the same feed.

## Signal & Execution Logic
- **Algo Base Class**: Subclass `Algo` to implement strategy lifecycle methods (`on_start`, `on_tick`, `on_bar`, `on_orderbook`, `on_quote`, `on_fill`).
- **Instrument API**: `instrument.get_bars(window)` returns a pandas‑like DataFrame with rolling utilities; `instrument.get_positions()` provides current exposure.
- **Order Execution**: Simple `instrument.buy(qty)` / `instrument.sell(qty)` abstracts broker interaction.
- **Indicators & ML**: Built‑in TA‑Lib wrapper and ability to import any Python package (e.g., scikit‑learn, TensorFlow) for custom signal generation.
- **Recording**: `self.record(key=value)` logs custom metrics for later analysis.

**How to integrate into eqats**:
- Map eqats’ strategy class to inherit from QTPyLib’s `Algo` (or adapt its callbacks).
- Use the provided indicator library or plug in eqats’ existing ML models via the import mechanism.
- Implement risk checks inside `on_bar`/`on_tick` before issuing orders, using position data from `get_positions()`.
- Utilize the `record` method to feed eqats’ performance‑tracking pipeline.

## Risk Engineering
QTPyLib’s README does not detail explicit risk‑limiting features (e.g., max position, stop‑loss, volatility scaling). Risk management would need to be built on top of the existing position and order APIs.

**Suggested approach for eqats**:
- Add a risk‑engine layer that wraps order submission: check equity‑based limits, max daily loss, or volatility‑adjusted size before calling `instrument.buy/sell`.
- Use the `record` method to expose risk metrics (e.g., current leverage, margin usage) to eqats’ monitoring dashboard.
- Implement stop‑loss logic inside `on_tick`/`on_bar` by evaluating recent price action and submitting opposite orders when thresholds are breached.

## Summary
By adopting QTPyLib’s Blotter for robust, asynchronous market data ingestion and storage, and its Algo framework for clean strategy development, eqats can gain a battle‑tested, event‑driven architecture while retaining freedom to plug in its own risk engines and ML signal generators.
