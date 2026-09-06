# Integration Blueprint for eqats: CCI(20) & SMA(20) Scanner

## Overview
The repo provides a daily scanner that fetches NSE OHLCV via yfinance, computes CCI(20) and SMA(20), generates four momentum signals, flags proximity to weekly/monthly/yearly lows, stores results in Couchbase, and serves them through a FastAPI API with an Angular dashboard.

## Data Engines Integration
- Replace yfinance fetch with eqats's market‑data adaptor.
- Compute CCI/SMA using eqats's feature library.
- Write results to eqats's preferred store (e.g., TimescaleDB) with fields: timestamp, watchlist, ticker, close, cci20, sma20, signal, near_low.
- Index on (watchlist, timestamp).
- Expose a FastAPI endpoint /api/v1/scan_results?watchlist=&date= returning JSON.
- Trigger via GitHub Actions cron or eqats's internal scheduler.

## Signal & Execution Logic Integration
- Define signals:
  * Reversal Zone: cci < -100 AND close < sma20
  * Recovery: -100 <= cci <= 0 AND close > sma20
  * Bullish Setup: 0 < cci <= 100 AND close > sma20
  * Overbought: cci > 100 AND close > sma20
- Low‑proximity flag: near_low = (close - min(low_week,low_month,low_year))/min_low <= 0.05.
- Attach signal and near_low to each record; API returns them.
- Reuse Angular UI (table, sortable columns, CCI sparkline, TradingView links) as an eqats plugin or iframe.
- Feed signals into eqats's execution layer for order generation.

## Risk Engineering Integration
- No explicit risk limits or sizing in the repo.
- Use near_low as a support‑distance risk gauge: higher proximity → lower position size or tighter stop.
- Add a risk factor proximity_to_low (0‑1) into eqats's risk model.
- Combine with volatility‑based stops; no further risk features needed.

## Implementation Steps
1. Fork repo into eqats monorepo under packages/cci20-sma20-scanner.
2. Replace backend/requirements.txt with eqats's dependency specs.
3. Refactor scanner.py to use eqats's market‑data client and feature store.
4. Replace backend/api.py with a thin FastAPI router reading from eqats's store.
5. Adjust GitHub Actions workflow to use eqats's secrets or swap to internal scheduler.
6. (Optional) Port Angular frontend to eqats's UI library or embed as iframe.
7. Write unit tests for CCI/SMA and signal logic.
8. Deploy and verify twice‑daily runs, API output, and dashboard display.

## Example Code Snippet
```python
def cci(series, period=20):
    tp = (series['high'] + series['low'] + series['close']) / 3
    ma = tp.rolling(period).mean()
    md = tp.rolling(period).apply(lambda x: pd.Series(x).mad())
    return (tp - ma) / (0.015 * md)

def sma(series, period=20):
    return series['close'].rolling(period).mean()

def compute_signals(df):
    df['cci20'] = cci(df)
    df['sma20'] = sma(df)
    df['signal'] = None
    df.loc[(df['cci20'] < -100) & (df['close'] < df['sma20']), 'signal'] = 'Reversal Zone'
    df.loc[(df['cci20'].between(-100,0)) & (df['close'] > df['sma20']), 'signal'] = 'Recovery'
    df.loc[(df['cci20'].between(0,100)) & (df['close'] > df['sma20']), 'signal'] = 'Bullish Setup'
    df.loc[(df['cci20'] > 100) & (df['close'] > df['sma20']), 'signal'] = 'Overbought'
    low_min = df[['low_week','low_month','low_year']].min(axis=1)
    df['near_low'] = (df['close'] - low_min) / low_min <= 0.05
    return df
```

## Conclusion
Adopting this scanner gives eqats a ready‑made NSE momentum pipeline that plugs directly into its data engine, signal engine, and (with the near_low factor) risk engine, requiring only minor adapter changes.