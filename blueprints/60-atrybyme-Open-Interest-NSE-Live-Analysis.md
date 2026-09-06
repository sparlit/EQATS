# Integration Blueprint for Open-Interest-NSE-Live-Analysis into eqats

## Overview
The repository provides live NSE option chain data collection and analytical indicators such as Put‑Call Ratio, Max Pain, and Probability‑of‑Change/Swing. These can be leveraged as market‑data engines and signal generators within the eqats quantitative trading framework.

## Data Engine Integration
1. **Live Data Ingestion** – Replace or augment eqats's market‑data adapter with the scripts `option_data_plotter_live_file1.py` and `option_data_put_call_ratio.py` to fetch real‑time option chain JSON from NSE.
2. **Normalization** – Convert raw NSE payload into eqats's canonical `OptionTick` schema (timestamp, symbol, strike, type, OI, volume, IV, LTP).
3. **Storage** – Stream the normalized ticks into eqats's timeseries store (e.g., kdb+/InfluxDB) via the existing data‑engine pipeline; optional caching layer can be added for replay.
4. **Utilities** – Reuse `utilities.py` helper functions (e.g., link building, point‑side extraction) inside eqats's data‑engine module.

## Signal & Execution Logic Integration
1. **Put‑Call Ratio Signal** – Compute the live PCR from ingested OI and expose as a `pcr_signal` feature; eqats's signal module can subscribe and generate long/short bias when PCR crosses thresholds (e.g., >1.2 bullish, <0.8 bearish).
2. **Max Pain Indicator** – Derive the max‑pain strike from OI distribution; treat deviation of underlying price from max‑pain as a mean‑reversion signal.
3. **Probability‑of‑Change / Swing** – Use the output of `utilities.py` (probability of trend change) as a momentum‑fade or breakout signal.
4. **Signal Aggregation** – Combine PCR, max‑pain, and probability scores into a composite signal using eqats's signal‑fusion framework (weighted sum or ML model).
5. **Order Execution** – Feed the composite signal into eqats's execution engine (e.g., TWAP/VWAP algos) to generate option‑chain‑based orders (buy calls/puts, vertical spreads) with appropriate lot sizing.

## Risk Engineering Considerations
- The source repo does not contain risk‑limit or position‑sizing logic. When integrating, apply eqats's existing risk‑engine modules:
  - **Exposure Limits** – Cap notional exposure per underlying and per strike.
  - **Greek Limits** – Enforce delta, gamma, vega limits derived from option‑chain Greeks (which can be calculated from fetched data).
  - **Stop‑Loss / VaR** – Apply eqats's real‑time risk monitor on the P&L of generated option positions.
  - **Liquidity Checks** – Use volume/OI thresholds from the data engine to filter illiquid strikes before sending orders.

## Implementation Steps
1. Fork the repo and package its core functions (`fetch_option_chain`, `compute_pcr`, `max_pain`, `prob_change_swing`) as a Python module `eqats.contrib.nse_oi`.
2. Add an eqats data‑engine adapter that calls this module on a configurable interval (e.g., every 5 seconds) and writes ticks to the timeseries store.
3. Extend eqats's signal library with three new signal classes: `PCRSignal`, `MaxPainSignal`, `ProbChangeSignal`.
4. Register these signals in the signal‑fusion config, assign weights, and back‑test using historical NSE option‑chain data (available via the same fetch routine).
5. Wire the fused signal to eqats's execution module, ensuring that order generation respects lot size and risk limits.
6. Deploy in a sandbox environment, monitor latency (<200 ms per fetch), and validate signal stability before moving to production.

## Expected Benefits
- Real‑time insight into market sentiment via PCR and max‑pain.
- Enhanced alpha generation for NIFTY/BANK NIFTY options strategies.
- Reuse of existing eqats infrastructure for storage, risk, and execution, minimizing duplication.

## Open Issues
- The original repo relies on a notification audio file; replace with eqats's alerting service.
- No built‑in error handling for NSE API changes; add retry/back‑off and fallback to cached data.
- No Greeks calculation; integrate eqats's Greek‑engine to enrich the option‑chain ticks.
