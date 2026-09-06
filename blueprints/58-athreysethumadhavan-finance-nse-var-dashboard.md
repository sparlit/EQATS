# Integration Blueprint: NSE VaR Dashboard into eqats

## Overview
The `nse-var-dashboard` repository provides a self-contained Value at Risk (VaR) model and interactive Streamlit dashboard for five NSE stocks. Its core capabilities—market data ingestion, VaR calculation (historical simulation and parametric), portfolio‑level VaR, and interactive risk visualisation—can be leveraged to enhance eqats's risk‑engineering layer and optionally its data‑engine and UI components.

## Data Engines
- **Live market data ingestion**: The project uses `yfinance` to fetch historical price data for NSE tickers. eqats can adopt a similar wrapper (or extend its existing data‑engine) to pull equities data from Yahoo Finance or other free sources, ensuring a reliable upstream for price series.
- **Pre‑processing pipeline**: Returns are computed via simple log returns, missing values are dropped, and data is aligned across tickers. This preprocessing logic can be reused to standardise input for eqats's risk models.

## Signal & Execution Logic
- **No relevant features**: The repository does not contain signal generation, strategy logic, or order‑execution components. Hence, there is nothing to integrate into eqats's signal & execution domain from this project.

## Risk Engineering
- **VaR calculation modules**: 
  - Historical Simulation VaR at configurable confidence levels (95%, 99%).
  - Parametric VaR assuming normal distribution (using SciPy for quantile).
  - Functions return both asset‑level and portfolio‑level VaR (equal‑weighted).
- **Fat‑tail detection**: By comparing historical vs. parametric VaR, the code highlights periods where the historical VaR exceeds the parametric estimate, signalling fat‑tailed behaviour.
- **Interactive risk dashboard**: Built with Streamlit and Matplotlib, the dashboard allows users to:
  - Select stocks, date ranges, confidence levels, and portfolio value.
  - View return distributions, VaR lines, and volatility plots.
  - This UI pattern can be mirrored in eqats's risk‑monitoring interface, providing a configurable, web‑based VaR visualiser.
- **Portfolio construction**: Equal‑weighted portfolio VaR is computed directly; eqats could plug in its own weighting scheme (e.g., risk‑parity, market‑cap) while reusing the VaR core.

## Integration Steps
1. **Data Engine** – Add a `yfinance_loader` module to eqats's data‑ingestion layer, mirroring the fetch‑and‑preprocess functions.
2. **Risk Engine** – Import the VaR calculation functions (`historical_var`, `parametric_var`, `portfolio_var`) into eqats's risk‑metrics package; expose them via a common API (e.g., `get_var(confidence, method)`).
3. **Risk Monitoring UI** – Create a Streamlit page in eqats that reuses the dashboard layout: sidebar controls for assets, dates, confidence, portfolio size; main panel showing distribution plots and VaR thresholds.
4. **Testing & Validation** – Run the existing notebooks against eqats's internal data to verify parity of VaR outputs; add unit tests for the VaR functions.
5. **Documentation** – Link the adapted modules in eqats's developer guide, citing the original `nse-var-dashboard` as reference.

## Benefits
- Rapidly adds a battle‑tested VaR engine with both historical and parametric approaches.
- Provides an interactive visual tool for risk analysts to explore tail‑risk scenarios.
- Encourages reuse of well‑documented, modular code, reducing development effort.

## Caveats
- The original implementation assumes equal weighting and a single‑currency (INR) portfolio; eqats must adapt weighting and currency handling.
- The dashboard relies on Streamlit; if eqats uses a different web framework, the UI components will need porting.
- No execution or signal logic is present, so integration focuses solely on risk‑measurement and data ingestion.
