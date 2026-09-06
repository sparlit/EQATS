# Integration Blueprint for sector-rotation-map into eqats

## Overview
The sector-rotation-map repository provides an interactive Relative Rotation Graph (RRG) dashboard for NSE sector indices, powered by OpenAlgo. It fetches historical price data, computes RS-Ratio and RS-Momentum, and visualizes sector rotation across four quadrants.

## Data Engines Integration
- **OpenAlgo Data Ingestion**: Reuse the existing OpenAlgo SDK wrapper and `.env` configuration (OPENALGO_API_KEY, OPENALGO_HOST) to pull daily OHLCV for the 12 NSE sector indices and benchmarks (NIFTY, BANKNIFTY, etc.).
- **Weekly Resampling**: Implement a resampling step (similar to the repo’s weekly conversion) to feed lower‑frequency data into eqats’ data engine, storing the resampled series in eqats’ time‑series store (e.g., PostgreSQL/TimescaleDB).
- **Metadata Catalog**: Store sector‑symbol mappings and benchmark lists as reference data, enabling dynamic symbol selection in eqats’ strategy studio.

## Signal & Execution Logic Integration
- **RRG Signal Engine**: Extract the RS‑Ratio and RS‑Momentum calculations (relative strength vs. benchmark, momentum of that ratio) into a reusable signal module. Output quadrants (Leading, Weakening, Lagging, Improving) as signal attributes.
- **Tail‑Length Analysis**: Expose configurable tail lengths (6, 8, 12, 16, 20 weeks) as parameters for trend‑strength scoring; longer tails can be used to generate persistence signals.
- **Custom Symbol & Portfolio Support**: Leverage the repo’s ability to add user‑defined symbols and create ad‑hoc portfolios to let eqats users define custom sector baskets or thematic indices for RRG analysis.
- **Benchmark Switching**: Integrate the benchmark selector (NIFTY, BANKNIFTY, NIFTY500, etc.) so that eqats strategies can run RRG against any chosen base index.
- **Visualization Export**: Optionally export the D3.js scatter chart data (coordinates, tails, tooltips) to eqats’ frontend for inline RRG widgets within strategy dashboards.

## Risk Engineering Integration
No explicit risk‑engineering features are present in the repository. The RRG dashboard offers visual monitoring of relative strength and momentum, which can inform risk exposure but does not implement position‑sizing, risk limits, or automated risk‑monitoring controls. To add risk capabilities, eqats could layer its existing risk‑engine (e.g., volatility‑based sizing, drawdown limits) on top of the RRG signals.

## Implementation Steps
1. **Data Layer** – Add an OpenAlgo connector in eqats’ data‑ingestion service, mirroring the repo’s `api_server.py` endpoint `/rrggraph` to return RS‑Ratio/RS‑Momentum for all sectors.
2. **Signal Layer** – Create a new `rrg_signal.py` strategy that consumes the connector output, computes quadrant labels, and emits them as signal events.
3. **Parameterization** – Expose tail length, benchmark, and custom symbols as strategy parameters via eqats’ UI.
4. **Frontend Widget** – Adapt the D3.js code to render inside eqats’ dashboard component, reusing tooltip and highlight logic.
5. **Testing** – Validate against historical NSE sector data; ensure signal reproducibility matches the original dashboard’s output.
6. **Documentation** – Update eqats’ strategy library with RRG documentation, linking to the original sector‑rotation‑map repo for reference.

## Conclusion
By extracting the data ingestion pipeline and RRG signal logic from sector‑rotation‑map, eqats gains a ready‑made sector‑rotation analysis tool that can be plugged into strategy development, portfolio construction, and visual monitoring, while relying on eqats’ own risk‑engine for position sizing and risk limits.