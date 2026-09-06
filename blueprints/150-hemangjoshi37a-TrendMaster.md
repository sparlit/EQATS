# Integration Blueprint for TrendMaster into eqats

## Overview
TrendMaster provides a Transformer‑based stock price prediction pipeline built with PyTorch. It offers a clean data‑ingestion layer (DataLoader) that authenticates with Zerodha Kite Connect, fetches historical OHLCV data, and prepares windowed datasets. The modeling core (TransAm, Trainer, Inferencer) can be reused as a signal generator within eqats, while the visualization and backtesting hooks aid in strategy validation.

## 1. Data Engine Integration
- Replace or wrap DataLoader: eqats already has market‑data connectors; we can add a Zerodha adapter that reuses TrendMaster’s `DataLoader.authenticate` and `prepare_data` methods.
- Windowing configuration: expose `input_window` (look‑back) and `output_window` (forecast horizon) as strategy parameters, enabling eqats to create supervised learning samples.
- Multiple symbols: iterate over a watchlist and store each symbol’s processed tensors in eqats’ feature store (e.g., a partitioned Parquet dataset or a time‑series DB).
- Real‑time refresh: schedule a job that calls `DataLoader.prepare_data` for the most recent day and appends new rows to the training set, keeping the model up‑to‑date.

## 2. Signal & Execution Logic Integration
- Model as signal: instantiate `TransAm` with the same architecture (num_layers=2, dropout=0.2) and load weights saved by `Trainer.save_model`. Use `Inferencer.predict` to generate price forecasts for the next `future_steps` periods.
- Signal generation: convert predicted price series into directional signals (e.g., if predicted close > current close → long, else short) or compute expected returns for position sizing.
- Training pipeline: eqats can schedule periodic retraining using TrendMaster’s `Trainer.train` method, pulling the latest windowed data from the feature store, logging train/val losses to eqats’ monitoring system.
- Backtesting: leverage the existing hjAlgos backtest URL or export the prediction series to eqats’ backtesting engine to evaluate Sharpe, drawdown, win‑rate, etc.
- Visualization: reuse `plot_results` and `plot_predictions` to produce eqats‑compatible reports (HTML/Plotly) for strategy review.

## 3. Risk Engineering
TrendMaster does not contain explicit risk‑management components (position sizing, VaR limits, stop‑loss logic). Risk controls should be implemented in eqats’ risk layer, using the model’s output as an input signal. For example:
- Apply volatility‑adjusted position sizing based on prediction confidence (inverse of prediction variance).
- Enforce max‑loss limits and stop‑loss orders outside the model.
- Monitor prediction drift and trigger model retraining when out‑of‑sample error exceeds a threshold.

## 4. Implementation Steps
1. Add Zerodha connector in `eqats/data_engines/zerodha.py` wrapping `DataLoader`.
2. Create feature store (e.g., Delta Lake) to hold windowed tensors for each symbol.
3. Implement model wrapper in `eqats/signals/transformer_signal.py` that loads `TransAm`, runs `Inferencer.predict`, and outputs a signal DataFrame.
4. Schedule training via eqats’ orchestrator (Airflow/Prefect) calling `Trainer.train` nightly.
5. Integrate with backtesting: feed signal outputs into eqats’ backtest module; optionally push results to hjAlgos for visual validation.
6. Monitor: log training loss, prediction error, and signal turnover; raise alerts if error > threshold.

## 5. Example Usage (pseudo‑code)
```python
from eqats.data_engines.zerodha import ZerodhaLoader
from eqats.signals.transformer_signal import TransformerSignal

loader = ZerodhaLoader(user_id, password, totp_key)
train, test = loader.prepare_data(
    symbol='RELIANCE',
    from_date='2023-01-01',
    to_date='2023-06-30',
    input_window=30,
    output_window=10
)

signal = TransformerSignal(model_path='transam_model.pth')
preds = signal.predict(train, future_steps=10)
# preds -> eqats signal format
```

By plugging these components into eqats, we gain a state‑of‑the‑art Transformer‑based price predictor while retaining eqats’ robust execution, risk, and orchestration infrastructure.
```