# Integration Blueprint for BrG Zone Scanner into eqats

## Repository Overview
- **Name**: BrG Zone Scanner
- **Primary Language**: Python
- **Purpose**: Scans NSE (National Stock Exchange) stocks to identify price zones (e.g., support/resistance or trading ranges).
- **Key Implication**: Likely includes routines for fetching NSE market data and calculating zones based on price action.

## Proposed Integration Areas

### Data Engines
- **Current Capability**: Ingestion of NSE equity data (likely via APIs such as NSE Python or similar) and preprocessing for zone calculations.
- **eqats Integration**: Replace or augment eqats' existing market data feed for Indian equities with the scanner's data ingestion module. This would provide eqats with ready‑to‑use OHLCV series for NSE symbols, enabling downstream analytics.

### Signal & Execution Logic
- **Current Capability**: Generation of zone‑based signals (e.g., long when price enters a demand zone, short when it hits a supply zone).
- **eqats Integration**: Expose the zone detection logic as a signal plugin within eqats' Signal & Execution Logic layer. The plugin would consume the OHLCV series from the data engine and emit zone‑trigger events that eqats can route to its order execution subsystem.

### Risk Engineering
- **Current Capability**: The scanner may include basic risk parameters such as zone width‑based stop‑loss or target‑profit calculations.
- **eqats Integration**: Adapt these risk rules into eqats' Risk Engineering module, allowing users to define position sizing and stop‑loss levels derived from the identified zone dimensions. This would provide a consistent risk‑adjusted framework for zone‑based strategies.

## Implementation Steps
1. **Data Engine Wrapper**
   - Create an eqats data‑engine adapter that calls the scanner’s NSE data fetch function.
   - Normalize output to eqats’ canonical market‑data schema (timestamp, open, high, low, close, volume).

2. **Signal Plugin**
   - Wrap the zone‑detection algorithm in a stateless function that receives a rolling window of bars and returns signal flags (e.g., `ZONE_ENTRY_LONG`, `ZONE_EXIT`).
   - Register the plugin with eqats’ signal registry.

3. **Risk Module Extension**
   - Extract any stop‑loss/target logic (e.g., ATR‑based or zone‑width‑based) and expose as configurable risk parameters.
   - Integrate with eqats’ position‑sizing calculator to compute lot size based on zone width and account risk.

4. **Testing & Validation**
   - Run historical backtests on NSE equities using eqats’ backtesting harness to verify signal accuracy and risk‑adjusted performance.
   - Compare against baseline strategies to ensure value‑add.

## Considerations
- **Data Source Reliability**: Verify the scanner’s NSE data provider respects rate limits and licensing.
- **Frequency**: Ensure the scanner’s update cadence matches eqats’ expected frequency (e.g., end‑of‑day vs intraday).
- **Customizability**: Make zone parameters (look‑back period, sensitivity) configurable via eqats’ strategy settings.
- **Error Handling**: Propagate data‑fetch failures through eqats’ error‑handling framework to avoid silent strategy degradation.

## Expected Benefits
- Rapid deployment of a NSE‑focused zone‑trading strategy within eqats.
- Reuse of proven zone‑detection logic, reducing development time.
- Enhanced risk controls tied directly to zone geometry, improving strategy robustness.
