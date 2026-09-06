# Integration Blueprint for NSE-Stock-Scanner features into eqats

## Overview
The NSE-Stock-Scanner repository provides a rich set of tools for Indian equity markets, including live/historical data ingestion, technical indicator calculations, candlestick pattern detection, swing/intraday strategy rules, backtesting, broker connectivity (Zerodha Kite), and risk management utilities. These components can be mapped onto the three eqats domains: Data Engines, Signal & Execution Logic, and Risk Engineering.

## Data Engines
- **Live & Historical Market Data**: Implement a unified data adapter that pulls tick/minute data from Zerodha Kite (via kiteconnect) and supplements with end‑of‑day bulk downloads for NSE symbols. Support the timeframes `[2,3,4,5,10,15,30,60]` minutes as well as daily bars.
- **Automatic Data Refresh**: Schedule a daily job (e.g., using APScheduler or cron) that runs after market close to download the latest equity list and OHLCV data, storing it in a columnar format (Parquet) for fast retrieval.
- **Metadata & Symbol Management**: Maintain a symbol master table with sector, lot size, tick size, and instrument token required by Kite APIs.

## Signal & Execution Logic
- **Technical Indicator Library**: Wrap pandas‑ta or TA‑Lib to compute CCI, MACD, Stochastic, Ichimoku, Moving Averages, Bollinger Bands, RSI, ATR, ADX. Expose each as a reusable feature that eqats can combine in strategy formulas.
- **Candlestick Pattern Detector**: Implement pattern recognition for Marubozu, Harami, Doji, Hammer/Shooting Star, V‑Pattern, Reverse Pattern, 3 White Soldiers, Engulfing patterns. Output boolean signals per bar.
- **Swing / Momentum Strategy Module**: Encode entry logic (price > recent high), stop‑loss (below recent low or previous close), target (1:2 risk‑reward), and optional overrides. Include daily pivot points and CPR calculations as additional filters.
- **Intraday Filters**: Add `Open == Low` and `Open == High` conditions, plus live market mood indicators (TICK, TRIN, count of 52‑week high/low stocks) as intraday regime filters.
- **Breakout & Consolidation Scanner**: Detect tight consolidation (price within x% range over n days) and flag potential breakout candidates.
- **Moving Average Crossover**: Generate signals when fast MA crosses slow MA within a look‑back window.
- **Backtesting Engine**: Reuse the existing backtesting notebook as a template; integrate with eqats’ event‑driven backtester to evaluate strategies on historical data.
- **Order Execution Adapter**: Translate signal objects into Kite order requests (limit/market) with appropriate product types (MIS for intraday, CNC for delivery) and tag them for journaling.

## Risk Engineering
- **Position Sizing & Risk Controls**: Implement automatic risk‑based sizing: calculate quantity such that monetary risk per trade equals a user‑defined % of capital, using stop‑loss distance. Enforce max daily loss and max concurrent positions.
- **Risk Appetite Filtering**: Provide a UI/configurable scanner that only passes symbols whose required capital (based on price and lot size) fits within the user’s budget.
- **Journal & Performance Analysis**: Store each trade (entry, exit, P&L, tags) in a SQLite/PostgreSQL table; expose equity‑curve, win‑rate, avg‑R, and drawdown metrics. Allow import/export of the journal for further analysis.
- **Emotion Control Aids**: Show live market mood and sentiment scores (future AI/RL extensions) to help traders stay disciplined; log deviations from plan.

## Integration Steps
1. **Data Layer** – Add a `NSEDataProvider` class inheriting from eqats’ `BaseDataAdapter`. Implement `fetch_live(symbol, interval)` and `fetch_historical(symbol, start, end, interval)` using kiteconnect and fallback to CSV/Parquet.
2. **Feature Library** – Create `ta_indicators.py` and `candlestick_patterns.py` modules that return pandas Series/DataFrames of signals.
3. **Strategy Modules** – Define `SwingStrategy`, `IntradayStrategy`, `BreakoutStrategy`, `MACrossoverStrategy` classes that consume the feature library and output `Signal` objects.
4. **Risk Module** – Build `RiskManager` with methods `position_size(signal, capital, risk_per_trade)` and `pre_trade_checks(signal, account)`.
5. **Execution Adapter** – Extend eqats’ `BrokerExecutor` to place orders via Kite, respecting product type and tagging orders with strategy ID.
6. **Backtesting** – Plug the strategy modules into eqats’ backtest engine; use the historical data provider to generate equity curves.
7. **Journaling** – Hook into the execution adapter’s fill events to write trades to the journal table; expose a Streamlit or notebook dashboard for analysis.
8. **Testing & CI** – Write unit tests for each indicator and pattern detector; configure GitHub Actions to run on push.

## Expected Benefits
- Immediate access to live NSE data via Zerodha Kite.
- A ready‑made library of 15+ technical indicators and 8 candlestick patterns.
- Pre‑built swing and intraday rule‑sets that can be toggled or combined.
- Robust risk‑based sizing and journaling to improve discipline.
- Extensible foundation for the repository’s planned AI news sentiment and RL modules.
