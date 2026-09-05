

## Repo 018. AI4Finance-Foundation/FinRL-Trading
- **Repository URL:** `https://github.com/AI4Finance-Foundation/FinRL-Trading`
- **Magic Number:** `9100033`
- **Architecture & System Design:** Deep Reinforcement Learning (DRL) stock portfolio allocation, time-series momentum signals, GICS sector rotation, and automated trade execution workflows.
- **Categorization:**
  - **Data Engines:** `src/data/data_fetcher.py`, `src/data/data_processor.py`, fundamental data & historical S&P 500 fetchers.
  - **Signal & Execution Logic:** `src/strategies/rl_model.py`, `src/strategies/fundamental_portfolio_drl.py`, `src/strategies/adaptive_rotation/` multi-asset group strength & market regime engine.
  - **Risk Engineering:** `src/strategies/adaptive_rotation/risk_manager.py`, PyPortfolioOpt efficient frontier risk bounds, draw-down guards.
- **EQATS Integration Module:** `src/institutional_integrations/finrl_trading_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `FINRL_TRADING`.
  - Feature scoring, continuous action state space mapping, 0.05 INR tick size rounding, and IST market session validation.

## Repo 019. ajakaiye33/ngrcoydisclosures
- **Repository URL:** `https://github.com/ajakaiye33/ngrcoydisclosures`
- **Magic Number:** `9100034`
- **Architecture & System Design:** Corporate disclosures parser extracting company news, director/insider dealings, and financial statement publication feeds via XML/RSS ingestion.
- **Categorization:**
  - **Data Engines:** `fetch_data()`, XML parsing of `<entry>` tags and field mapping (`Description`, `Type_of_Submission`, `CompanyName`, `CompanySymbol`).
  - **Signal & Execution Logic:** Filtering and event classification for `Directors Dealings` and `Financial Statements` into positive/negative sentiment scores and trading actions.
  - **Risk Engineering:** IST market session validation, 0.05 INR tick rounding, rejection of invalid/closed session order submissions.
- **EQATS Integration Module:** `src/institutional_integrations/ngrcoydisclosures_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `NGRCOY_DISCLOSURES`.

## Repo 031. amitashwinibhagat/nse-swing-scanner
- **Repository URL:** `https://github.com/amitashwinibhagat/nse-swing-scanner`
- **Magic Number:** `9100012`
- **Architecture & System Design:** Multi-timeframe swing trend alignment scanning (EMA 20/50/200), RSI oversold/overbought recovery triggers, Supertrend volatility trailing channel calculations.
- **Categorization:**
  - **Data Engines:** Multi-timeframe bar aggregators, historical EOD quote streams.
  - **Signal & Execution Logic:** Swing alignment scanner matching trend and momentum recovery triggers.
  - **Risk Engineering:** Trailing Supertrend channel stops, 0.05 INR price tick size rounding, IST trading session validation.
- **EQATS Integration Module:** `src/institutional_integrations/nse_swing_scanner_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `NSE_SWING_SCANNER`.

## Repo 032. amv-dev/yata
- **Repository URL:** `https://github.com/amv-dev/yata`
- **Magic Number:** `9100037`
- **Architecture & System Design:** High-performance technical analysis indicators library written in Rust computing streaming Hull Moving Average (HMA), MACD crossovers, and Parabolic SAR trend reversals.
- **Categorization:**
  - **Data Engines:** OHLCV candle window series and time-series moving average transformers (WMA, EMA, HMA).
  - **Signal & Execution Logic:** `src/indicators/hull_moving_average.rs`, `src/indicators/macd.rs`, `src/indicators/parabolic_sar.rs` reversal signals.
  - **Risk Engineering:** 0.05 INR price tick rounding, IST market session validation.
- **EQATS Integration Module:** `src/institutional_integrations/yata_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `YATA_TECHNICAL`.

## Repo 033. aneesh540/vse
- **Repository URL:** `https://github.com/aneesh540/vse`
- **Magic Number:** `9100038`
- **Architecture & System Design:** Virtual Stock Exchange (VSE) web application handling virtual demat portfolios, simulated stock buying/selling, cash accounting, and NSE listed companies CSV ingestion (`bin/nse_listed.js`).
- **Categorization:**
  - **Data Engines:** `bin/nse_listed.js` CSV parsing and company information lookup endpoints (`api/controllers/nse_share.js`).
  - **Signal & Execution Logic:** `api/controllers/portfolio.js` simulated trade execution engine, average buy price calculation, and demat portfolio management.
  - **Risk Engineering:** Insufficient funds rejection, insufficient holdings check, 0.05 INR price tick rounding, IST market session validation.
- **EQATS Integration Module:** `src/institutional_integrations/vse_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `VSE_DEMAT`.

## Repo 040. ankitchaudhary6886/nse-system
- **Repository URL:** `https://github.com/ankitchaudhary6886/nse-system`
- **Magic Number:** `9100040`
- **Architecture & System Design:** Comprehensive multi-factor stock screening and market regime gatekeeper system combining fundamental band scoring (`scoring.py`), benchmark EMA(10) regime detection (`regime.py`), sector relative strength ranking (`sector_gate.py`), and institutional accumulation tracking (`institutional.py`).
- **Categorization:**
  - **Data Engines:** `db.py` SQLite tables, `universe.py`, `fundamentals_compute.py`, `ingest_prices.py`.
  - **Signal & Execution Logic:** `scoring.py` ROCE/profit/PEG scoring bands, `regime.py` top-down market gatekeeper, `sector_gate.py` leadership sector filter.
  - **Risk Engineering:** Regime-based entry prohibition in bearish trends, 0.05 INR price tick rounding, IST trading session validation.
- **EQATS Integration Module:** `src/institutional_integrations/nse_system_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `NSE_SYSTEM`.

## Repo 043. anshuthopsee/nse-oi-visualizer
- **Repository URL:** `https://github.com/anshuthopsee/nse-oi-visualizer`
- **Magic Number:** `9100043`
- **Architecture & System Design:** Option chain Open Interest (OI) tracking, Call/Put Open Interest change imbalance scoring, Put-Call Ratio (PCR) analytics, and Black-76 option pricing/implied volatility model (`backend/black76.js`).
- **Categorization:**
  - **Data Engines:** `backend/server.js` option-chain API fetchers (`api/option-chain-indices`, `api/option-chain-equities`), cookies/user-agent manager.
  - **Signal & Execution Logic:** `backend/black76.js` Black-76 option pricing algorithm, Call/Put OI change imbalance, Max Pain strike calculation, and PCR signal thresholds.
  - **Risk Engineering:** 0.05 INR price tick rounding, IST market trading session validation.
- **EQATS Integration Module:** `src/institutional_integrations/nse_oi_visualizer_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `NSE_OI_VISUALIZER`.

## Repo 045. anthdm/rust-trading-engine
- **Repository URL:** `https://github.com/anthdm/rust-trading-engine`
- **Magic Number:** `9100044`
- **Architecture & System Design:** Price-time priority L2 orderbook matching engine written in Rust (`src/matching_engine/orderbook.rs`, `src/matching_engine/engine.rs`).
- **Categorization:**
  - **Data Engines:** L2 orderbook price level HashMap queues (`asks`, `bids`), `TradingPair` base/quote symbol management.
  - **Signal & Execution Logic:** Market and limit order fill execution (`fill_market_order`, `add_order`), price-time queue priority matching.
  - **Risk Engineering:** 0.05 INR price tick size rounding, IST market session validation.
- **EQATS Integration Module:** `src/institutional_integrations/rust_matching_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `RUST_MATCHING_ENGINE`.

## Repo 048. api-evangelist/nse-india
- **Repository URL:** `https://github.com/api-evangelist/nse-india`
- **Magic Number:** `9100046`
- **Architecture & System Design:** OpenAPI/YAML specification registry for National Stock Exchange of India (NSE) data services (`apis.yml`), domain security controls auditing (`security/nse-india-domain-security.yml`), and API quality/health score checking (`kin/score-*.yml`).
- **Categorization:**
  - **Data Engines:** `apis.yml` API surface definitions, delivery/access models, and endpoint catalog.
  - **Signal & Execution Logic:** Domain security compliance validator (DNSSEC, SPF, DMARC policy) and API health quality scoring.
  - **Risk Engineering:** 0.05 INR price tick rounding, IST trading session enforcement.
- **EQATS Integration Module:** `src/institutional_integrations/nse_india_api_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `NSE_INDIA_API`.

## Repo 049. Aravin/Algo-Trade
- **Repository URL:** `https://github.com/Aravin/Algo-Trade`
- **Magic Number:** `9100047`
- **Architecture & System Design:** Multi-broker unified gateway router, serverless cron session token refreshers (`app/cron/src`), and multi-broker client wrappers (`testapp/src/finvasia`, `testapp/src/upstox`, `testapp/src/smartapi`).
- **Categorization:**
  - **Data Engines:** Broker API client abstractions (Finvasia Shoonya, Upstox, Zerodha Kite, AngelOne SmartAPI).
  - **Signal & Execution Logic:** `route_order_execution` multi-broker order router, session health monitoring, and automated cron refreshers.
  - **Risk Engineering:** Session token inactivity checks, 0.05 INR price tick rounding, IST trading session enforcement.
- **EQATS Integration Module:** `src/institutional_integrations/algo_trade_aravin_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `ALGO_TRADE_ARAVIN`.
