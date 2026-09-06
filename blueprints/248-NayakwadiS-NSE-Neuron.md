# Integration Blueprint for NSE-Neuron Features into eqats

## Overview
NSE-Neuron provides a deep‑learning based pipeline for Indian equities that fetches NSE historical data, trains multiple sequence models, and outputs 5‑day OHLC forecasts together with BUY/HOLD/SELL signals, market regime tags, and candlestick pattern annotations. These capabilities can be plugged into eqats to enhance its signal generation and data layers.

## Data Engines
- **Historical Data Ingestion**: Replace or augment eqats’ current market‑data adapter with NSE‑Neuron’s data fetcher (likely using yfinance or NSE API) to obtain daily OHLCV for any NSE‑listed symbol. The fetcher already handles date alignment, missing‑value filling, and scaling for model input.
- **Pre‑processing Pipeline**: Reuse the normalization and windowing code that prepares data for LSTM/BiLSTM/GRU/CNN‑LSTM models. This ensures eqats consumes features in the same format the models expect, reducing integration friction.

## Signal & Execution Logic
- **Model‑Based Forecasts**: Import the four trained models (or their training scripts) into eqats’ signal engine. Each model returns a 5‑day ahead forecast for High, Low, Close; eqats can store these as predicted price series.
- **Signal Classifier**: Attach the models’ built‑in classifiers that map forecasts to BUY/HOLD/SELL actions. eqats can treat these as primary signals or as inputs to its existing signal‑fusion logic.
- **Market Regime Detection**: Use the regime‑detector (BULL/BEAR/SIDEWAYS) to gate or weight signals. For example, in a BEAR regime eqats could reduce long exposure or increase short bias.
- **Candlestick Pattern Overlay**: Integrate the pattern‑recognition module to emit additional pattern‑based signals (e.g., bullish engulfing, doji) that eqats can combine with model signals via its signal‑aggregation framework.
- **Execution Hook**: Expose the prediction/signal outputs through a lightweight FastAPI endpoint (already present in the repo). eqats’ execution layer can call this endpoint to receive real‑time signals for order generation.

## Risk Engineering
- **No native risk limits or position‑sizing logic** is present in NSE‑Neuron. However, the regime output can be repurposed as a risk‑adjustment factor: eqats could map BULL → full leverage, BEAR → reduced leverage or inverse exposure, SIDEWAYS → neutral. This would be implemented as a simple risk‑scaling rule in eqats’ risk‑engine, not as a direct import.

## Implementation Steps
1. **Clone NSE‑Neuron** into a vendor directory.
2. **Create a Python wrapper** (`nse_neuron_adapter.py`) that:
   - Calls the data‑fetcher to pull OHLCV for a given symbol.
   - Runs the preprocessing pipeline.
   - Loads the four pretrained models (or trains on‑the‑fly if desired).
   - Returns forecasts, signal labels, regime tag, and pattern list.
3. **Expose via FastAPI** (reuse existing `start.bat`/`uvicorn` launch) or call the wrapper directly from eqats’ signal service.
4. **Subscribe eqats’ signal engine** to the adapter’s output, fusing with existing signals using eqats’ weighting scheme.
5. **Add a risk‑scaling module** that reads the regime tag and adjusts position‑size limits accordingly.
6. **Unit‑test** the adapter against known NSE tickers to ensure data shape matches eqats expectations.
7. **Document** the new data source and signal type in eqats’ configuration guide.

## Benefits
- Adds a sophisticated deep‑learning forecast source for Indian equities.
- Provides alternative signal regime and pattern‑based overlays that can improve signal robustness.
- Leverages existing UI (React) for optional visual validation within eqats’ dashboard if desired.

## Caveats
- Models are trained on historical NSE data; periodic retraining is needed to avoid drift.
- The repo does not include order‑execution or risk‑limit logic, so eqats must supply those layers.
- Ensure compliance with NSE data‑usage policies when fetching historical data.
