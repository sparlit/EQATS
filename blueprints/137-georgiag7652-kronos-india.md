# Integration Blueprint for kronos-india into eqats

## Overview
The kronos-india repository provides a Python‑based pipeline that consumes NSE intraday market data and produces trade signals using the Kronos foundation model. This aligns closely with eqats’ Signal & Execution Logic domain and can augment its data‑engine capabilities.

## Domain Mapping

### Data Engines
- **Feature:** Ingestion of NSE intraday trade data (price, volume, timestamps).
- **Integration:** Replace or supplement eqats’ current market‑data adapters with the kronos‑india data loader to support NSE‑specific intraday feeds. The loader can be wrapped as an eqats data‑engine plugin, outputting standardized OHLCV bars.

### Signal & Execution Logic
- **Feature:** Signal generation via the Kronos foundation model (a pretrained time‑series model).
- **Integration:** Hook the model’s prediction function into eqats’ signal engine as a new signal provider. The output (e.g., signal strength, direction) can be mapped to eqats’ signal schema and fed into the execution module for order generation.

### Risk Engineering
- **Feature:** None explicitly described in the README.
- **Integration:** No direct risk‑engineering components to import. However, the generated signals can be subjected to eqats’ existing risk limits, position‑sizing, and monitoring layers.

## Implementation Steps
1. **Data Adapter** – Create an eqats‑compatible adapter that calls kronos‑india’s data‑ingestion routine to fetch NSE intraday bars.
2. **Signal Plugin** – Wrap the Kronos model inference code in an eqats signal plugin; expose a `generate_signal(data)` function returning standardized signal objects.
3. **Configuration** – Add the new adapter and plugin to eqats’ configuration YAML, enabling selection of the NSE/Kronos pipeline.
4. **Testing** – Run unit tests using sample NSE data to verify signal output matches expected format.
5. **Deployment** – Deploy alongside existing strategies; monitor signal quality and integrate with eqats’ risk checks.

## Expected Benefits
- Access to a foundation‑model‑driven signal source for Indian equities.
- Expanded market coverage (NSE) within eqats.
- Modular plug‑in approach keeps core eqats unchanged.

## Considerations
- Verify licensing of the Kronos foundation model for commercial use.
- Ensure latency of model inference fits intraday trading windows.
- Apply eqats’ risk‑engineering controls (max position, stop‑loss) to signals from this new source.
