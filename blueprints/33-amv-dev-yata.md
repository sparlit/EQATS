# Integration Blueprint for yata in eqats

## Overview
yata is a pure‑Rust technical analysis library offering a wide collection of moving averages, methods, and indicators. It can be used to transform raw market data and generate trading signals within the eqats framework.

## Data Engine Integration
- **Timeframe conversion**: Use `CollapseTimeframe`, `HeikinAshi`, and `Renko` to resample or transform OHLCV series before feeding them to strategies.
- **Custom preprocessing**: The library’s generic indicator trait allows wrapping any user‑defined calculation, enabling eqats to plug in proprietary data cleaning steps.

## Signal & Execution Logic Integration
- **Moving averages**: Import SMA, EMA, HMA, VWMA, etc., directly as eqats signal nodes.
- **Methods**: Leverage cross‑over detectors (`Cross`, `CrossAbove`, `CrossUnder`), momentum (`Momentum`, `ROC`), volatility (`StDev`, `LinearVolatility`), and trend‑strength (`AverageDirectionalIndex`, `TSI`) to build composite signals.
- **Indicators**: Plug‑and‑play Bollinger Bands, MACD‑like constructs (via EMA combinations), Awesome Oscillator, etc., as independent signal generators.
- **Signal composition**: Combine multiple yata outputs using eqats’ signal algebra (AND/OR, weighting) to produce final entry/exit orders.

## Risk Engineering Integration
yata does not provide risk‑management primitives; eqats should continue to use its own risk‑engine modules (position sizing, stop‑loss, drawdown limits) while treating yata outputs as pure signal inputs.

## Implementation Steps
1. Add dependency in `Cargo.toml`:
   ```toml
   [dependencies]
   yata = "0.6"
   ```
2. In eqats’ data‑pipeline module, instantiate a `CollapseTimeframe` or `HeikinAshi` transformer and feed raw OHLCV vectors.
3. Pass the transformed series to chosen yata methods/indicators, collecting their `next()` outputs as f64 signals.
4. Map those signals to eqats’ `Signal` trait implementations (e.g., `ThresholdCross`, `ZScore`).
5. Feed the resulting signals into existing strategy logic and order execution unchanged.
6. Optionally, wrap custom calculations via yata’s `Indicator` trait for reuse across multiple strategies.

## Benefits
- Rust‑native performance, zero‑cost abstractions.
- Extensive, well‑tested TA functions reduce boilerplate.
- Easy to extend with user‑defined indicators that stay within eqats’ type‑safe pipeline.

## Caveats
- yata focuses solely on technical calculations; it does not handle order execution, risk limits, or portfolio state.
- Ensure compatibility of data types (eqats likely uses `f64` or `Decimal`; yata works with generic `Float` types).