# Integration Blueprint: Sectoral Breadth Dashboard → eqats

## Repository Overview
- **Name:** Sectoral‑Breadth‑Dashboard
- **Primary Language:** Python
- **Key Frameworks:** Streamlit (UI), pandas (data wrangling), plotly (interactive charts)
- **Purpose:** Provides a real‑time Streamlit dashboard that visualizes NSE industry‑wise breadth metrics (advance‑decline, new highs/lows, sector strength).

## Mapped eqats Domains

### Data Engines
- **Ingestion:** The dashboard pulls live NSE sector data via HTTP APIs (or libraries like `nsepy`). This can be reused as a market‑data feed for eqats’ data engine.
- **Transformation:** Calculates advance‑decline ratios, new highs/lows counts, and sector breadth percentages—exactly the kind of derived market‑data eqats expects from its data layer.
- **Storage/Caching:** Optionally writes processed data to CSV/Parquet files; eqats could adopt a similar caching layer to reduce API calls and speed up back‑testing.

### Signal & Execution Logic
- **Signal Generation:** The breadth metrics (e.g., sector advance‑decline line, bullish/bearish sector score) constitute actionable signals. eqats can import these as feature inputs for its strategy modules.
- **Execution:** The repository does **not** contain order‑placement or broker‑integration code; eqats would retain its own execution layer while consuming the signals.

### Risk Engineering
- **Current State:** No explicit risk limits, position sizing, or risk‑monitoring components.
- **Potential Use:** The sector breadth outputs can serve as risk‑monitoring indicators (e.g., flagging overly concentrated bullish/bearish sectors). eqats’ risk engine could subscribe to these metrics to enforce sector‑exposure limits or adjust volatility scaling.

## Integration Steps
1. **Data Engine Adaptation**
   - Extract the API‑calling and data‑transformation functions from the dashboard into a reusable Python module (e.g., `eqats/data/nse_breadth.py`).
   - Align the output schema with eqats’ canonical market‑data format (timestamp, sector, advance, decline, new_high, new_low, breadth_score).
   - Add optional persistence (Parquet/Feather) to eqats’ data lake for historical breadth series.
2. **Signal Layer Hook**
   - Create a signal provider in eqats (`eqats/signals/breadth.py`) that calls the breadth module and emits signals via eqats’ event bus.
   - Define signal types: `SECTOR_BREADTH_BULLISH`, `SECTOR_BREADTH_BEARISH`, `SECTOR_ADVANCE_DECLINE_RATIO`.
3. **Risk Engine Consumption**
   - In eqats’ risk module (`eqats/risk/sector_exposure.py`), subscribe to breadth signals to compute sector‑level exposure limits.
   - Implement rules such as: if breadth score > 0.8 for a sector, reduce new long exposure in that sector by 20%.
4. **UI/Optional Dashboard**
   - The existing Streamlit app can be repurposed as a monitoring view inside eqats’ ops portal, showing live breadth alongside strategy P&L.
   - No code changes needed; just point the Streamlit app to eqats’ data store.
5. **Testing & CI**
   - Write unit tests for the breadth calculations using historical NSE fixtures.
   - Add integration tests that verify signal emission and risk‑rule triggering.

## Value Proposition
- **Speed to Market:** Leverages an already‑built, tested data pipeline for NSE sector breadth.
- **Enhanced Signals:** Provides macro‑level sector sentiment that complements eqats’ existing alpha models.
- **Risk Awareness:** Supplies a transparent metric for sector‑concentration risk, improving eqats’ risk‑adjusted returns.

## Caveats
- The repo lacks explicit error handling, logging, and production‑grade deployment configs; these must be added when porting to eqats.
- Data source reliability depends on NSE public APIs; consider adding a fallback or premium data feed for robustness.
