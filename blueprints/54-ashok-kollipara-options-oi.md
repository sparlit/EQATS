# Integration Blueprint: options-oi → eqats

## Overview
The `options-oi` repository provides a simple Tkinter‑based GUI that retrieves NSE option‑chain data via the public NSE API and visualises open‑interest (OI) for selected indices and expiries. While it does not contain signal generation, order execution, or risk‑management logic, its data‑acquisition and visualization components are valuable for eqats as an alternative market‑data source and as a reference for building a lightweight OI‑analysis dashboard.

## 1. Data Engines Integration

### 1.1 Market‑Data Ingestion
- **Source**: NSE public option‑chain endpoint (same as used in `options-oi`).
- **Implementation**: Replace the ad‑hoc `requests` calls in `options-oi` with eqats’ standardized data‑connector interface (e.g., a Python class inheriting from `eqats.data.BaseConnector`).
- **Normalisation**: Map the raw JSON fields (`strikePrice`, `openInterest`, `changeinOpenInterest`, `totalTradedVolume`, etc.) to eqats’ canonical option‑chain schema (`symbol`, `expiry`, `strike`, `right`, `oi`, `delta_oi`, `volume`).
- **Storage**: Persist each snapshot to eqats’ time‑series store (e.g., TimescaleDB or kdb+) with a timestamp, enabling historical OI analysis.
- **Refresh Logic**: Leverage the repository’s planned auto‑refresh (every 5 min) to schedule periodic pulls via eqats’ scheduler (e.g., APScheduler or Airflow).

### 1.2 In‑Memory Caching & Replay
- The GUI loads the entire chain into memory for plotting. In eqats, we can cache the latest chain in a shared memory store (Redis or in‑process dict) to serve low‑latency queries from strategies or dashboards.
- Historical snapshots can be replayed for back‑testing by reading from the time‑series store.

### 1.3 Visualization Reuse
- The existing Matplotlib OI plot can be extracted as a reusable plotting function (`plot_oi(chain_df)`) and integrated into eqats’ monitoring UI (e.g., a Grafana panel or a custom Streamlit/Dash view).
- This enables traders to quickly inspect OI distribution across strikes for a given expiry, supporting manual strategy adjustments.

## 2. Signal & Execution Logic

The repository does not contain any signal generation, strategy logic, or order‑execution code. Consequently, there are no direct features to map into eqats’ signal/execution domain. If desired, the OI data supplied by the connector could feed into custom eqats strategies (e.g., OI‑based mean‑reversion or skew‑trading signals) that reside in the `eqats.signal` package.

## 3. Risk Engineering

No risk‑limits, position‑sizing, or risk‑monitoring features are present in `options-oi`. Risk‑management in eqats would continue to rely on its existing risk engine; the OI data could be used as an additional risk factor (e.g., monitoring extreme OI concentration at specific strikes) but would require new risk‑module development.

## 4. Summary of Integration Steps
1. **Create a NSE Option‑Chain Connector** in `eqats/data/connectors/nse_oi.py` that mirrors the request logic from `options-oi`.
2. **Define a schema‑mapping layer** to convert raw API output to eqats’ internal option‑chain format.
3. **Schedule periodic pulls** (e.g., every 5 min) using eqats’ job scheduler.
4. **Store snapshots** in the eqats time‑series database for historical analysis.
5. **Expose a caching layer** (Redis) for the latest chain to serve low‑latency UI components.
6. **Extract the plotting routine** into a shared utilities module (`eqats/utils/plot_oi.py`) and integrate it into eqats’ monitoring dashboard.
7. **Document usage** in eqats’ developer guide, highlighting how to retrieve OI data for strategy development.

By incorporating these components, eqats gains a reliable, low‑latency source of NSE option‑chain open‑interest data and a ready‑to‑use visualization tool, enhancing its data‑engine capabilities without duplicating effort.
