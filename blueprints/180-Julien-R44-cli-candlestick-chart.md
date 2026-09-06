# Integration Blueprint for cli-candlestick-chart into eqats

## Overview
The cli-candlestick-chart crate provides a lightweight, terminal‑native way to render OHLCV candlestick charts from Rust. It can be used as a library or a binary and already supports reading CSV, JSON, and stdin input.

## Data Ingestion Integration
- Add the crate as a dependency in eqats’ visualization service (`cli-candlestick-chart = \"0.3\"`).
- Pull market data from eqats’ data engine (e.g., a Kafka topic or internal market‑data feed) and convert each tick into a `Candle { open, high, low, close, volume? }`.
- For backtesting or replay, reuse the existing CSV/JSON parsers by feeding eqats‑generated dump files.

## Visualization Enhancements
- Instantiate `Chart::new(&candles)`, set a descriptive name with `set_name`, and configure bull/bear colors via `set_bear_color` / `set_bull_color`.
- Enable the volume pane when volume data is present (`set_volume_pane_enabled(true); set_volume_pane_height(6);`).
- The chart automatically sizes itself to the current terminal width/height, making it suitable for eqats’ console‑based dashboards.
- For GUI or web front‑ends, the binary can be invoked as a subprocess to produce an image or ANSI output that is then embedded.

## Signal & Execution Logic Overlay
- The crate does not natively draw signal markers, but eqats can extend the visualization layer: after drawing the base chart, overlay ANSI escape codes to place symbols (e.g., ▲ for buy, ▼ for sell) at specific candle indices.
- Alternatively, fork the repo or submit a feature request to add a `set_signal_color` and `draw_signals` method; until then, post‑processing the output is a lightweight workaround.

## Risk Engineering Visualization
- Risk metrics such as VaR, drawdown, or position‑size limits are not part of the charting library. eqats can compute these metrics separately and render them as additional text panes or as a second chart (e.g., equity curve) using the same crate.
- Future work could involve adding a `set_extra_pane` feature to stack risk‑metric series alongside price candles.

## Deployment
- Add the dependency to the relevant eqats Cargo.toml and enable `features = [\"serde\",\"csv\"]` for file‑based backtesting.
- The pre‑built binary can be shipped with the eqats CLI for quick ad‑hoc charting of CSV dumps (`eqats chart --file data.csv`).
- All functionality is pure Rust, with no external runtime dependencies, ensuring easy cross‑platform distribution.

## Benefits
- Minimal overhead and fast rendering, ideal for real‑time console monitoring.
- Customizable colors let eqats match its visual theme.
- Terminal‑native output integrates seamlessly with existing eqats console tools.

## Limitations & Future Work
- No built‑in support for technical indicator lines, text annotations, or multi‑series overlay; would require upstream changes or post‑processing.
- No direct GUI or web rendering; for those contexts consider the Python port (`py-candlestick-chart`) or a WASM target.

By incorporating cli-candlestick-chart, eqats gains a fast, dependency‑light candlestick visualizer that can display market data, user‑generated signals, and risk metrics with little effort.