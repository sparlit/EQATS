# Integration Blueprint for NSE-Closing-Stock-Price-Prediction-Using-LSTM into eqats

## Overview
The repository implements an LSTM model to predict NSE closing stock prices using historical data from Kaggle. It provides a complete pipeline for data ingestion, preprocessing, model training, and prediction.

## Data Engines Domain
- **Ingestion**: Load CSV file from Kaggle NYSE dataset via `pandas.read_csv`.
- **Preprocessing**: Parse dates, sort chronologically, scale the 'Close' column with `MinMaxScaler` to [0,1].
- **Feature Engineering**: Create sliding windows of length `look_back` (e.g., 60 days) to form input sequences and corresponding targets.
- **Storage**: Processed numpy arrays are kept in memory for model training; can be persisted to disk using `numpy.save` if needed.

These capabilities map directly to eqats’ data engine responsibilities: acquiring market data, normalizing it, and preparing supervised learning datasets.

## Signal & Execution Logic Domain
- **Signal trained**: The LSTM outputs a scaled price prediction; after inverse scaling, it yields a forecasted closing price for the next time step.
- **Signal usage**: Convert the forecast into a directional signal:
  - If predicted price > latest actual price → **Buy** signal.
  - If predicted price < latest actual price → **Sell** signal.
  - Magnitude of difference can be used to size the signal strength.
- **Execution hook**: In eqats, the signal can be fed into the existing signal router to generate order tickets via the execution adapter.

## Risk Engineering Domain
The repository does not contain any risk‑management components (position sizing, stop‑loss, VaR, leverage limits, or real‑time risk monitoring). Therefore, no direct risk‑engineering features are available for integration.

## Integration Steps
1. **Wrap the notebook functions** (`load_data`, `preprocess`, `create_dataset`, `build_lstm`, `train_model`, `predict`) into a Python module `eqats/data_engines/nse_lstm.py`.
2. **Expose a data‑engine plugin** that returns a pandas DataFrame with columns: `timestamp`, `predicted_close`, `signal` (buy/sell/hold).
3. **Register the plugin** in eqats’ data‑engine registry so it can be scheduled alongside other market‑data feeds.
4. **Connect the signal output** to eqats’ signal‑execution layer: map the `signal` column to the strategy signal format expected by the order‑generation engine.
5. **Optional**: Add a thin risk‑wrapper (e.g., max position size) around the signal if desired, though this would be implemented in eqats’ risk‑engineering layer, not borrowed from the repo.

## Example Snippet
```python
# eqats/data_engines/nse_lstm.py
import pandas as pd
import numpy as np
from sklearn.preprocessing import MinMaxScaler
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense

def load_nse_data(csv_path):
    df = pd.read_csv(csv_path)
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.sort_values('Date')
    return df

def prepare_lstm(df, look_back=60):
    scaler = MinMaxScaler(feature_range=(0,1))
    scaled = scaler.fit_transform(df[['Close']])
    X, y = [], []
    for i in range(look_back, len(scaled)):
        X.append(scaled[i-look_back:i, 0])
        y.append(scaled[i, 0])
    X = np.array(X).reshape(-1, look_back, 1)
    y = np.array(y)
    return X, y, scaler

def build_model(input_shape):
    model = Sequential([
        LSTM(50, return_sequences=True, input_shape=input_shape),
        LSTM(50),
        Dense(1)
    ])
    model.compile(optimizer='adam', loss='mean_squared_error')
    return model

def generate_signal(df, model, scaler, look_back=60):
    X, _, _ = prepare_lstm(df, look_back)
    pred_scaled = model.predict(X)
    pred = scaler.inverse_transform(pred_scaled)
    # Align predictions with timestamps (skip first look_back rows)
    signals = []
    for i, idx in enumerate(df.index[look_back:]):
        actual = df.loc[idx, 'Close']
        forecast = pred[i,0]
        signal = 'buy' if forecast > actual else 'sell' if forecast < actual else 'hold'
        signals.append({
            'timestamp': df.loc[idx, 'Date'],
            'predicted_close': forecast,
            'signal': signal,
            'signal_strength': abs(forecast - actual)
        })
    return pd.DataFrame(signals)
```

By plugging this module into eqats, the LSTM‑based price forecast becomes a reusable signal source, while the data‑engineering parts enhance eqats’ market‑data pipeline.

## Conclusion
The notebook contributes valuable data‑engine and signal‑generation assets. No risk‑engineering features are present, so that domain remains unchanged in eqats.
