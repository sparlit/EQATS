# Integration Blueprint for eqats: indian-stock-tracker

## Overview
The indian-stock-tracker repository provides a self‑contained pipeline for fetching Indian equity data, computing a momentum‑volume score, and storing results in a SQLite database. Its components can be reused to augment eqats with Indian‑market data ingestion, a ready‑made scoring signal, and a lightweight database browser.

## Data Engines
- **Data fetching** – data_sources.py defines a DataSource abstraction with NSESource (primary) and YFinanceSource (fallback). data_fetcher.py iterates over SOURCES to obtain OHLCV for Nifty‑50 symbols (and optional mutual‑fund NAVs).
- **Storage** – SQLAlchemy models in models.py (Stock, DailyPrice, Suggestion) and helper init_db() create a local stocks.db. The schema mirrors eqats’ needs for instruments, price bars, and signal outputs.
- **Automation** – run_daily.py orchestrates fetch → score → store and can be scheduled via cron or eqats’ own scheduler.
- **Exploration UI** – The Flask app (flask_app.py) serves a DB browser at 'http://localhost:8080' with JSON APIs (/api/stocks, /api/prices). This can be run alongside eqats’ admin console for quick data validation.

## Signal & Execution Logic
- **Scoring engine** – scoring.py implements a composite score = price momentum + relative volume factor. The function score_stocks(df) returns a DataFrame with score and reasoning.
- **Suggestion generation** – After scoring, the top‑N (default 50) stocks are persisted as Suggestion rows with date, score, and free‑text reasoning.
- **CLI** – cli.py reads suggestions for a given date (or generates them on the fly) and prints them, providing a simple way to feed signals into eqats’ execution layer.
- **Integration point** – Eqats can import scoring.score_stocks or call run_daily.py as a subprocess to obtain daily signals, then map the returned stock_id to eqats’ internal instrument IDs and consume the score as an alpha weight.

## Risk Engineering
The repository does not contain explicit risk‑management modules (position sizing, limits, exposure monitoring). Consequently, no direct risk‑engineering features are available for import. Eqats should continue to apply its own risk overlays (volatility targeting, max‑position, sector caps) on top of the scores supplied by this tracker.

## Implementation Steps
1. **Add as a dependency** – Clone the repo or install it as a local package; ensure pandas, yfinance, nsepy, flask, sqlalchemy etc. are available (they overlap with eqats’ existing stack).
2. **Expose a signal function** – Create a thin wrapper in eqats, e.g.:

   ```python
   from indian_stock_tracker.scoring import score_stocks
   from indian_stock_tracker.data_fetcher import fetch_latest_prices

   def get_indian_signals(as_of_date=None):
       price_df = fetch_latest_prices()          # returns OHLCV for tracked symbols
       scored = score_stocks(price_df)           # adds score & reasoning
       suggestions = scored.nlargest(50, 'score')[['symbol','score','reasoning']]
       return suggestions
   ```

3. **Persist to eqats’ store** – Map symbol to eqats’ instrument IDs and insert rows into the signals table (or equivalent) with timestamp and alpha weight = normalized score.
4. **Schedule** – Hook the wrapper into eqats’ daily batch (e.g., after market close) using eqats’ scheduler or a cron identical to the one shown in the repo’s README.
5. **Optional UI** – Launch flask_app.py on a separate port to visualize the raw Indian‑stock data and suggestions; eqats’ ops team can use it for sanity checks.
6. **Testing** – Run `python cli.py --date 01-09-2025` to verify that suggestions are generated and persisted; compare against eqats’ signal output.

## Notes
- The tracker’s default universe is the Nifty‑50 list; to expand or restrict the universe, edit DEFAULT_SYMBOLS in data_fetcher.py or adjust MF_SCHEME_CODES for mutual funds.
- The scoring algorithm is deliberately simple (momentum + volume); eqats can replace or blend it with proprietary models while retaining the data‑pipeline and storage benefits.
- No changes to the existing Flask UI are required for eqats consumption; it remains a convenient diagnostic tool.
