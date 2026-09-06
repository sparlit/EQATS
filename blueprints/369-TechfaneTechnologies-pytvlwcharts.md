# Integration Blueprint for pytvlwcharts in eqats

## Overview
Integrate the TradingView Lightweight-Charts wrapper (pytvlwcharts) into the eqats quantitative trading system to enable interactive visualisation of market data, trading signals, and risk metrics directly from Rust-generated data structures via PyO3 bindings.

## Components
- **Data Engines**: Feed OHLCV data from eqats' data engine (e.g., Polars or DataFusion) into a pandas DataFrame that pytvlwcharts consumes.
- **Signal & Execution Logic**: Use pytvlwcharts to plot buy/sell markers, entry/exit zones, and equity curves on top of price charts.
- **Risk Engineering**: Overlay risk metrics such as drawdown, volatility bands, and Value-at-Risk as additional series or horizontal lines.

## Interaction Flow
1. Rust core computes signals and risk metrics.
2. Data is transferred to Python side via PyO3-exposed functions (e.g., plot_chart).
3. Python side loads data into a pandas DataFrame, creates a LightweightCharts instance, adds series and markers, and displays the chart in a Jupyter notebook or Colab.
4. User interacts with the chart; optional callbacks can send back annotations to Rust for strategy refinement.

## Implementation Details
- A PyO3 module eqats_charts provides a plot_chart(df: &PyAny) function.
- The function imports pytvlwcharts, creates a chart, loads the dataframe, adds candlestick series, and optionally overlays signal and risk series.
- The module is compiled as part of the eqats Python package and can be imported in notebooks: import eqats_charts; eqats_charts.plot_chart(df).

## Testing
- Unit test verifies that the PyO3 module loads and the function is callable with a dummy DataFrame.
- Integration test runs in a notebook environment to confirm chart rendering.