# Integration Blueprint for eqats

## Overview
The `nse-ml-2021` repository provides a collection of market‑microstructure heuristics, technical indicators, and simple ML‑oriented features focused on NSE/Nifty stocks. These can be leveraged to enrich eqats’ data pipeline, signal generation, and risk management layers.

## Data Engine Integration
- **Market Data Ingestion**: Use `nsepy`/`yfinance` (or similar) to pull OHLCV, ATP, delivery, and VWAP series for Nifty and constituent stocks (SBI, ICICI, etc.).
- **Feature Engineering**:
  - Compute VWAP and add as a column.
  - Calculate RSI (14‑period), ADX, and VIX for each symbol.
  - Derive ATP‑delivery flow indicators (e.g., `ATP_down_delivery_up` = 1 when ATP down & delivery up).
  - Build correlation features: `Nifty_SBI_corr`, `Nifty_ICICI_corr`.
  - Create relative strength ratios: `Stock_Nifty_ratio`, `Sector_Nifty_ratio` (BankNifty, CNXIT, NiftyAuto, etc.).
  - Identify consecutive lows and power‑of‑2 reference high/low windows.
- **Storage**: Persist raw and feature‑enriched data in Parquet/CSV partitions keyed by date and symbol for fast retrieval by downstream modules.

## Signal & Execution Logic Integration
- **VWAP Rule**: Generate intraday signals:
  - `long_signal = (close < vwap) & (prev_close < prev_vwap)`
  - `short_signal = (close > vwap) & (prev_close > prev_vwap)`
  - Enforce “do not sell above VWAP, do not buy below VWAP” as a filter.
- **RSI Monthly Signal**: When monthly RSI > 70, flag a bullish outlook for the next 12 months; can be used as a regime filter for equity‑long strategies.
- **Higher‑Time‑Frame Confirmation**: Require alignment of monthly, weekly, and daily trend direction (e.g., all above their respective 50‑EMA) before executing a trade.
- **Power‑of‑2 Anchors**: For a target timeframe (hourly, daily, weekly), reference the high/low of the last two periods of the next higher scale to define support/resistance zones.
- **Anchor VWAP**: Track VWAP from significant low/high dates (e.g., 23‑Mar‑2020, 07‑Jul‑2021) as static reference levels.
- **F2B Relative Strength**: Compute `stock/Nifty` and `sector/Nifty` ratios; rank assets by rising relative strength to select candidates for momentum strategies.
- **ATP‑Delivery Flow**: Use the ATP‑delivery matrix to bias direction:
  - Bullish bias when ATP up & delivery up.
  - Bearish bias when ATP down & delivery up.
  - Neutral otherwise.

## Risk Engineering Integration
- **Trend Strength Filter**: Only take trades when ADX > 20 (or a configurable threshold) to avoid choppy markets.
- **Volatility Sizing**: Use calculated VIX or historical volatility to adjust position size inversely (higher volatility → smaller size).
- **Volume‑Price Consolidation**: Flag periods where price is flat but volume is rising (good demand) vs. flat price with falling volume (poor demand); adjust stop‑loss tightness accordingly.
- **ATP‑Delivery Risk Rules**: Reduce exposure or tighten stops when bearish ATP‑delivery signals appear (ATP down & delivery up).
- **Higher‑Time‑Frame Alignment**: Enforce that the trade direction agrees with the higher‑time‑frame trend; otherwise, treat as a conflict and skip or reduce size.
- **Stop‑Loss Guidance**: Place initial stop‑loss just beyond the nearest VWAP or anchor VWAP level; trail using VWAP or ATR.

## Implementation Steps
1. **Data Layer** – Extend eqats’ ingestion module to pull ATP, delivery, and VWAP fields alongside OHLCV.
2. **Feature Store** – Add the engineered features (VWAP, RSI, ADX, VIX, correlations, relative strength ratios, ATP‑delivery flags, anchor levels) to the feature repository.
3. **Signal Module** – Implement the VWAP rule, RSI monthly filter, higher‑time‑frame confirmation, power‑of‑2 anchor logic, and F2B relative strength ranking as signal generators.
4. **Risk Module** – Integrate ADX‑based trend filter, VIX‑based sizing, volume‑price consolidation scoring, ATP‑delivery bias, and higher‑time‑frame alignment checks.
5. **Backtesting** – Validate the combined signals and risk controls on historical Nifty/minute‑data to ensure performance gains.
6. **Deployment** – Wire the modules into eqats’ live trading engine, ensuring low‑latency feature updates (e.g., VWAP recomputed each tick).

## Expected Benefits
- Enhanced intraday edge via VWAP‑based mean‑reversion/continuation logic.
- Improved medium‑term outlook using RSI monthly extremes and relative strength.
- Robust risk controls that prevent trading against higher‑time‑frame trends and adjust exposure based on volatility and order‑flow signals.
- A richer feature set for any downstream ML models, increasing predictive power for direction forecasts.
