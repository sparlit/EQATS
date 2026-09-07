# Integration Blueprint for BhavFnO into eqats

## Overview
The BhavFnO repository provides a lightweight Python pipeline for downloading, processing, and visualizing NSE Futures & Options (FnO) Bhavcopy data. Its core strengths lie in data ingestion, feature extraction, and visual reporting—capabilities that can be leveraged within the eqats framework to enrich market‑data feeds and generate systematic signals.

## Data Engines Integration
- **Automated Bhavcopy Acquisition**: Replace eqats's generic market‑data downloader with the BhavFnO `download_bhavcopy()` function (or equivalent) to pull the previous day’s NSE Bhavcopy CSV directly from the NSE website.
- **Parsing & Normalization**: Use the repository’s CSV‑reading logic (pandas‑based) to standardize column names, filter relevant FnO contracts, and compute derived fields such as:
  - Daily price change (%)
  - Open interest change
  - Volume
  - Put‑Call Ratio (PCR) per strike/expiry
- **Storage Hook**: After processing, persist the enriched DataFrame to eqats's feature store (e.g., Parquet or time‑series DB) via the existing `eqats.data_engine.store` interface, enabling downstream strategies to query historical FnO metrics.
- **Incremental Updates**: Schedule the download step to run after market close, aligning with eqats's daily data-refresh cadence.

## Signal & Execution Logic Integration
- **Signal Generation**: Translate the calculated metrics into actionable signals:
  - **Price‑Momentum Signal**: Go long/short on contracts with abnormal price change relative to historical volatility.
  - **OI‑Flow Signal**: Detect unusual open‑interest buildup/shedding as a proxy for institutional activity.
  - **PCR Signal**: Extreme PCR values (e.g., >1.5 or <0.5) as contrarian sentiment indicators.
- **Visualization & Reporting**: Re‑use the BhavFnO HTML‑report generator (matplotlib + mpld3 or similar) to produce eqats‑compatible dashboards that embed signal commentary directly into the UI, facilitating analyst review.
- **Execution Adapter**: While BhavFnO does not submit orders, its signal objects can be fed into eqats’s `signal_execution` layer (e.g., `eqats.signal_execution.router`) which maps signals to order‑size decisions and routes them to the broker‑agnostic execution module.

## Risk Engineering Integration
- **Current Gap**: The repository lacks explicit risk controls (position limits, VaR, margin checks). Integration should therefore:
  - Wrap the incoming FnO signals with eqats's risk‑engineering pre‑trade checks (e.g., max notional per contract, liquidity filters, margin utilization).
  - Leverage eqats's real‑time risk monitor to track exposure generated from FnO positions and trigger alerts if limits are breached.
- **Future Enhancement**: Consider adding a risk‑module to BhavFnO that calculates contract‑level margin requirements using NSE‑SPAN logic, then expose those metrics via the same data‑engine pipeline for consumption by eqats.

## Implementation Steps
1. **Clone & Package**: Wrap the BhavFnO core functions (`download_bhavcopy`, `process_bhavcopy`, `generate_report`) into a Python package (`eqats_ext_bhavfno`) and add it to eqats’s `requirements.txt`.
2. **Interface Layer**: Create an adapter (`eqats.adapters.bhavfno`) that calls the package, returns a normalized DataFrame, and publishes it to eqats’s feature store under the namespace `market_data.fnO.bhavcopy`.
3. **Signal Plugin**: Develop a signal plugin (`eqats.signal_plugins.fnO_trend`) that reads the stored FnO features, computes the three signal families above, and emits them via eqats’s signal bus.
4. **Dashboard Integration**: Hook the HTML report generator into eqats’s visualization service (e.g., Grafana panel or custom Streamlit view) to display daily FnO commentary alongside other market insights.
5. **Risk Controls**: Ensure all FnO signals pass through eqats’s risk‑engineering middleware before reaching the execution gateway.
6. **Testing & CI**: Add unit tests for the download/processing pipeline (mocking NSE responses) and integrate into eqats’s CI/CD to verify compatibility with future NSE format changes.

## Expected Benefits
- **Enhanced Market Coverage**: Immediate access to comprehensive FnO data without building a custom scraper.
- **Quantitative Signal Library**: Ready‑to‑use trend‑based signals that can be combined with existing eqats strategies.
- **Operational Simplicity**: Automated daily refresh reduces manual data‑handling overhead.
- **Extensible Foundation**: The modular adapter design allows future enrichment (e.g., adding options‑greeks, IV surfaces) while keeping risk‑management responsibilities within eqats’s core.

## Caveats
- The repository relies on the NSE website’s CSV structure; any changes to the Bhavcopy format will require updates to the parsing logic.
- No built‑in execution or risk‑limiting features; these must be supplied by eqats’s existing layers.
- The visualization is currently a static HTML file; for real‑time dashboards consider converting to a dynamic plotting library (Plotly/Dash) within eqats.
