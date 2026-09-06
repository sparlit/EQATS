# Integration Blueprint: nse-smart-investor → eqats

## Overview
The `nse-smart-investor` repository provides a Streamlit‑based dashboard for Indian equity analysis, built around a pure‑Python analysis engine that is deliberately decoupled from the UI. Its core strengths lie in a tiered market data pipeline, a composite scoring / signal suite, and a comprehensive risk‑analytics toolkit. These components can be lifted and adapted into the `eqats` project to enrich its data layer, signal generation, and risk management capabilities.

## 1. Data Engines

### 1.1 Tiered Market Data Fetcher
- **What it does:** Attempts Angel One SmartAPI first, falls back to Stooq, then Yahoo Finance, with results cached via `shared/cache.py`.
- **How to integrate:** Replace or augment `eqats`’s current data‑ingestion module with a similar fallback chain. Wrap each provider in a thin adapter returning a normalized OHLCV/DataFrame schema. Use the existing caching decorator (or `joblib`/`diskcache`) to persist recent bars and reduce API calls.

### 1.2 Angel One SmartAPI Client
- **What it does:** Provides live quotes, holdings, positions, funds, and order placement (including GTT).
- **How to integrate:** If `eqats` targets Indian brokers, reuse the `angel_fetcher.py` patterns (session generation, token refresh) to create a broker‑agnostic wrapper. Expose functions like `get_ltp(symbol)`, `place_order(...)`, and `get_holdings()` that `eqats` strategies can call.

### 1.3 Universe & Sector Mapping
- **What it does:** `universe.py` maps ~745 Nifty Total Market tickers to sectors, used by sector‑aware fundamentals and qualitative flags.
- **How to integrate:** Import this mapping (or rebuild a similar CSV/JSON) to enable sector‑specific risk adjustments and scoring in `eqats`.

### 1.4 Corporate Actions, News & RSS Feeds
- **What it does:** `nse_corp_info.py`, `news_feed.py`, `nse_rss_feeds.py` feed qualitative flags.
- **How to integrate:** Schedule a daily job that pulls NSE corporate actions (splits, bonuses, dividends) and Google News RSS for each sector, storing results in a lightweight DB (SQLite/Postgres) for the risk engine to consult.

### 1.5 Persistent Trade Store
- **What it does:** `trade_store.py` offers SQLite by default, switching to Postgres when `DATABASE_URL` is set; stores paper trades, watchlists, and journal entries.
- **How to integrate:** Adopt the same pattern for `eqats`’s persistence layer: a thin abstraction layer that routes to SQLite in dev/test and to a managed Postgres instance in production, ensuring paper‑trade survivability across redeploys.

## 2. Signal & Execution Logic

### 2.1 Composite Score (0‑90)
- **What it does:** Combines technical (40), momentum (25), volume (15), sentiment (10) – sentiment derived from India VIX regime + sector rank.
- **How to integrate:** Implement the four sub‑scores as separate modules in `eqats.signals`. The final score can drive a ranking universe or feed into a meta‑strategy.

### 2.2 Trend Quality Score (TQS)
- **What it does:** 90‑point, four‑pillar scanner across Nifty 50/100/500/Total Market.
- **How to integrate:** Port the TQS logic (trend strength, consistency, momentum, volatility) into `eqats.scanners`. Use it as a pre‑filter for trade ideas or as a component of a regime‑detector.

### 2.3 Valuation Decision Layer (E1‑v2)
- **What it does:** Rules‑based engine that outputs a descriptive posture (Bull/Bear/Risk/Verdict) without issuing explicit buy/sell calls.
- **How to integrate:** Plug this into `eqats.valuation` as a posture generator that can be combined with other signals to produce a final strategy bias.

### 2.4 Intraday Toolkit
- **What it does:** CPR, ORB, Supertrend, anchored VWAP, gap scanner, OI & options analysis.
- **How to integrate:** Expose each as a function returning signal series (e.g., `signal_cpr(df)`). These can be used by `eqats`’s intraday strategies or as features for machine‑learning models.

### 2.5 Paper Trading Journal
- **What it does:** Persistent journal of simulated trades (entry/exit, P&L, tags).
- **How to integrate:** Reuse the `trade_store` schema to log `eqats` paper trades, enabling performance analytics and walk‑forward analysis.

### 2.6 Smart Screener & Backtest
- **What it does:** Interactive screener and a backtest page that runs the pure engine on historical data.
- **How to integrate:** Extract the backtesting harness (`analysis/` modules) and incorporate it into `eqats`’s CI/CD pipeline for regression testing of new signals.

### 2.7 Angel One Order Execution
- **What it does:** Live order placement and GTT via SmartAPI.
- **How to integrate:** If `eqats` aims for live execution with Angel One, adopt the existing order‑placement functions, adding idempotency checks and error handling.

## 3. Risk Engineering

### 3.1 Portfolio Risk Analytics
- **What it does:** Beta vs Nifty, NAV reconstruction, Sharpe/Sortino/Calmar, correlation, HHI concentration, hedge sizing.
- **How to integrate:** Bundle these metrics into a `eqats.risk` module that consumes portfolio positions and returns a risk dashboard (or JSON) for monitoring and alerting.

### 3.2 Position Sizer
- **What it does:** Tool that computes optimal stake size based on risk per trade, volatility, and portfolio constraints.
- **How to integrate:** Use the position sizer as a pre‑trade gate in `eqats`’s execution layer, ensuring each signal respects max‑drawdown or VaR limits.

### 3.3 Hedging & Liquidity Analysis
- **What it does:** `hedging.py` and `liquidity.py` provide hedge ratios and liquidity‑adjusted cost estimates.
- **How to integrate:** Incorporate these into the risk‑engineering workflow to dynamically adjust hedge exposure and estimate slippage for large orders.

### 3.4 Sector‑Aware Fundamentals & Qualitative Flags
- **What it does:** Adjusts valuation metrics for banks/NBFCs/insurers and flags governance/regulatory risks.
- **How to integrate:** Feed sector‑specific adjustments into the valuation and scoring engines; use qualitative flags as risk overlays that can increase required capital or halt trading.

## 4. Suggested Implementation Steps
1. **Data Layer** – Add the tiered fetcher, Angel One adapter, and universe/sector mapping to `eqats/data`.
2. **Persistence** – Introduce `trade_store`‑style abstraction for paper‑trade/journal storage.
3. **Signal Modules** – Port composite score, TQS, valuation layer, intraday toolkit, and screener/backtest into `eqats/signals` and `eqats/scanners`.
4. **Risk Module** – Consolidate beta, Sharpe/Sortino/Calmar, HHI, position sizer, hedging, and liquidity into `eqats/risk`.
5. **Broker Execution** – If live trading with Angel One is desired, wrap the existing SmartAPI client in `eqats/execution`.
6. **Testing** – Leverage the existing pytest suite (unit tests in `analysis/`) as a template for `eqats`’s own test coverage.

By following this blueprint, `eqats` can quickly gain a robust, production‑grade data pipeline, a diversified set of alpha signals, and institutional‑grade risk controls—all grounded in the proven, Streamlit‑free components of `nse-smart-investor`.
