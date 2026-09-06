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

## Repo 050. Aravin/nse-data
- **Repository URL:** `https://github.com/Aravin/nse-data`
- **Magic Number:** `9100048`
- **Architecture & System Design:** TypeScript client for NSE data API endpoints with cookie session extraction (`src/common/http.ts`), equity quote parsing (`src/api/equity-quote`), and option chain matrix extraction (`src/api/equity-option-chain`).
- **Categorization:**
  - **Data Engines:** Akamai header spoofing, set-cookie session manager, equity quote and option chain payload parsers.
  - **Signal & Execution Logic:** Equity price change momentum evaluation and Put-Call Ratio (PCR) calculation.
  - **Risk Engineering:** 0.05 INR price tick size rounding, IST trading session validation.
- **EQATS Integration Module:** `src/institutional_integrations/nse_data_aravin_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `NSE_DATA_ARAVIN`.

## Repo 051. ArishHassan/nse-live_testing
- **Repository URL:** `https://github.com/ArishHassan/nse-live_testing`
- **Magic Number:** `9100049`
- **Architecture & System Design:** Live NSE market data feed connectivity tester and latency benchmarking utility.
- **Categorization:**
  - **Data Engines:** Live NSE HTTP/REST response parsers, ping latency recorders, connectivity health checkers.
  - **Signal & Execution Logic:** Network latency thresholding, response timeout detection, connection status categorization.
  - **Risk Engineering:** 0.05 INR price tick size rounding, IST market session validation.
- **EQATS Integration Module:** `src/institutional_integrations/nse_live_testing_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `NSE_LIVE_TESTING`.

## Repo 052. arvchahal/kalshi-rs
- **Repository URL:** `https://github.com/arvchahal/kalshi-rs`
- **Magic Number:** `9100050`
- **Architecture & System Design:** Rust SDK for Kalshi prediction markets REST API, market orderbook query engine, and event probability pricing.
- **Categorization:**
  - **Data Engines:** Kalshi REST API payload decoders, event ticker market data structures (`Market`, `Orderbook`).
  - **Signal & Execution Logic:** Implied YES/NO event probability pricing and Expected Value (EV) calculation.
  - **Risk Engineering:** Zero-margin requirement checks, 0.05 INR price tick rounding, IST trading session validation.
- **EQATS Integration Module:** `src/institutional_integrations/kalshi_rs_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `KALSHI_RS`.

## Repo 053. asavinov/intelligent-trading-bot
- **Repository URL:** `https://github.com/asavinov/intelligent-trading-bot`
- **Magic Number:** `9100051`
- **Architecture & System Design:** Machine Learning time-series feature engineering and price trend signal classification engine.
- **Categorization:**
  - **Data Engines:** Rolling window price transformer, mean return & volatility aggregators.
  - **Signal & Execution Logic:** Multi-factor ML feature extraction (`ret_mean`, `volatility`, `high_ratio`, `low_ratio`) and logistic probability signal classification (`prob_buy`, `recommended_signal`).
  - **Risk Engineering:** 0.05 INR price tick rounding, IST trading session validation, closed session order rejection.
- **EQATS Integration Module:** `src/institutional_integrations/intelligent_trading_bot_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `INTELLIGENT_TRADING_BOT`.

## Repo 055. ashgen/NSEDataAnalytics
- **Repository URL:** `https://github.com/ashgen/NSEDataAnalytics`
- **Magic Number:** `9100052`
- **Architecture & System Design:** Implied Volatility (IV) smile spline interpolation, bid-ask volume imbalance analytics, and Max Pain strike calculation engine.
- **Categorization:**
  - **Data Engines:** Historical tick/quote loader (`LoadFromCSV.py`), bid/ask market depth volume parser (`BidAskVolume.py`).
  - **Signal & Execution Logic:** Implied volatility smile calculation (`VolSmileCalc.py`), spline interpolation (`SplineInterpVol.py`), Max Pain strike calculation (`MaxPain.py`), bid/ask volume imbalance ratio.
  - **Risk Engineering:** 0.05 INR price tick rounding, IST trading session validation, closed session order rejection.
- **EQATS Integration Module:** `src/institutional_integrations/nse_data_analytics_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `NSE_DATA_ANALYTICS`.

## Repo 056. ashishkumar30/stock_market_live_trading_using_ai
- **Repository URL:** `https://github.com/ashishkumar30/stock_market_live_trading_using_ai`
- **Magic Number:** `9100053`
- **Architecture & System Design:** Guppy Multiple Moving Average (GMMA) trend scoring, Heikin-Ashi candle transformation, and RSI momentum break triggers.
- **Categorization:**
  - **Data Engines:** Historical price data fetcher, Heikin-Ashi candle transformer (`convert_to_heikin_ashi`).
  - **Signal & Execution Logic:** GMMA short/long group EMA alignment (`evaluate_gmma_trend`), RSI momentum break triggers.
  - **Risk Engineering:** 0.05 INR price tick rounding, IST trading session validation, closed session order rejection.
- **EQATS Integration Module:** `src/institutional_integrations/ai_stock_live_trader_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `AI_STOCK_LIVE_TRADER`.

## Repo 057. ashok-kollipara/options-oi
- **Repository URL:** `https://github.com/ashok-kollipara/options-oi`
- **Magic Number:** `9100054`
- **Architecture & System Design:** Open Interest (OI) strike matrix parser, Call/Put OI change imbalance scoring, Put-Call Ratio (PCR) analytics.
- **Categorization:**
  - **Data Engines:** NSE JSON option chain fetcher and response handler (`json_handler.py`).
  - **Signal & Execution Logic:** Put-Call Ratio calculation (`compute_pcr`), Call/Put OI change imbalance scoring (`analyze_oi_change_imbalance`).
  - **Risk Engineering:** 0.05 INR price tick rounding, IST trading session validation, closed session order rejection.
- **EQATS Integration Module:** `src/institutional_integrations/options_oi_analytics_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `OPTIONS_OI_ANALYTICS`.

## Repo 058. AshokKumar3502/nse-quant-trading
- **Repository URL:** `https://github.com/AshokKumar3502/nse-quant-trading`
- **Magic Number:** `9100055`
- **Architecture & System Design:** Multi-timeframe stock breakout scanner (`stock_scanner.py`), Bollinger Band volatility squeeze detection, ATR trailing stop bounds.
- **Categorization:**
  - **Data Engines:** Stock market data scanner and report generator (`upload_reports.py`).
  - **Signal & Execution Logic:** Bollinger Band volatility squeeze & 20-bar high breakout triggers (`evaluate_volatility_breakout`).
  - **Risk Engineering:** 0.05 INR price tick rounding, IST trading session validation, closed session order rejection.
- **EQATS Integration Module:** `src/institutional_integrations/nse_quant_trading_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `NSE_QUANT_TRADING`.

## Repo 059. Ashutosh0x/rust-finance
- **Repository URL:** `https://github.com/Ashutosh0x/rust-finance`
- **Magic Number:** `9100056`
- **Architecture & System Design:** High-performance Rust quantitative finance workspace crates (`crates/pricing`, `crates/risk`, `crates/signals`).
- **Categorization:**
  - **Data Engines:** Fast market event bus and price ticks decoder.
  - **Signal & Execution Logic:** Black-Scholes analytical option pricing and Delta calculation (`calculate_black_scholes`).
  - **Risk Engineering:** Parametric Value-at-Risk (VaR) Monte Carlo risk bounds (`calculate_value_at_risk`), 0.05 INR price tick rounding, IST trading session validation.
- **EQATS Integration Module:** `src/institutional_integrations/rust_finance_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `RUST_FINANCE`.

## Repo 060. ashwanthkumar/Live-NSE-Stock
- **Repository URL:** `https://github.com/ashwanthkumar/Live-NSE-Stock`
- **Magic Number:** `9100057`
- **Architecture & System Design:** Live NSE quote JSON parser and stock price percentage change tracker (`live_quote.js`).
- **Categorization:**
  - **Data Engines:** Live NSE HTTP/REST quote response parser (`parse_quote_response`).
  - **Signal & Execution Logic:** Real-time stock price change percentage calculation (`p_change`).
  - **Risk Engineering:** 0.05 INR price tick rounding, IST trading session validation, closed session order rejection.
- **EQATS Integration Module:** `src/institutional_integrations/live_nse_stock_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `LIVE_NSE_STOCK`.

## Repo 061. athreysethumadhavan-finance/nse-var-dashboard
- **Repository URL:** `https://github.com/athreysethumadhavan-finance/nse-var-dashboard`
- **Magic Number:** `9100058`
- **Architecture & System Design:** Portfolio Value-at-Risk (VaR) and Conditional VaR (Expected Shortfall) calculation dashboard (`var_dashboard.py`).
- **Categorization:**
  - **Data Engines:** Historical return distribution series transformer.
  - **Signal & Execution Logic:** Historical VaR/CVaR cutoff calculation (`compute_historical_var`), Parametric Gaussian VaR (`compute_parametric_var`).
  - **Risk Engineering:** 0.05 INR price tick rounding, IST trading session validation, closed session order rejection.
- **EQATS Integration Module:** `src/institutional_integrations/nse_var_dashboard_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `NSE_VAR_DASHBOARD`.

## Repo 062. atilaahmettaner/tradingview-mcp
- **Repository URL:** `https://github.com/atilaahmettaner/tradingview-mcp`
- **Magic Number:** `9100059`
- **Architecture & System Design:** Model Context Protocol (MCP) server providing TradingView technical indicators and multi-indicator technical recommendation summary aggregation (`server.py`).
- **Categorization:**
  - **Data Engines:** TradingView quote and technical indicator payload parser.
  - **Signal & Execution Logic:** Multi-indicator technical recommendation summary (`compute_technical_summary`) combining moving averages (SMA 10, SMA 20) and RSI overbought/oversold levels.
  - **Risk Engineering:** 0.05 INR price tick rounding, IST trading session validation, closed session order rejection.
- **EQATS Integration Module:** `src/institutional_integrations/tradingview_mcp_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `TRADINGVIEW_MCP`.

## Repo 063. atrybyme/Open-Interest-NSE-Live-Analysis
- **Repository URL:** `https://github.com/atrybyme/Open-Interest-NSE-Live-Analysis`
- **Magic Number:** `9100060`
- **Architecture & System Design:** Live Option Max Pain calculation, historical Open Interest histogram distribution (`historical_histogram.py`), and Put-Call Ratio (PCR) momentum calculation.
- **Categorization:**
  - **Data Engines:** Live options CSV data fetcher and histogram builder.
  - **Signal & Execution Logic:** Option Max Pain calculation (`compute_max_pain`), PCR trend momentum evaluation (`analyze_pcr_momentum`).
  - **Risk Engineering:** 0.05 INR price tick rounding, IST trading session validation, closed session order rejection.
- **EQATS Integration Module:** `src/institutional_integrations/open_interest_live_analysis_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `OPEN_INTEREST_LIVE_ANALYSIS`.

## Repo 064. Atul-Anand-Jha/Time-Series-Forecast-NSEPy
- **Repository URL:** `https://github.com/Atul-Anand-Jha/Time-Series-Forecast-NSEPy`
- **Magic Number:** `9100061`
- **Architecture & System Design:** Auto-Regressive (AR) time-series price forecasting and exponentially weighted moving average momentum prediction (`NSEPy=Part-1 and 2.ipynb`).
- **Categorization:**
  - **Data Engines:** NSEPy historical stock CSV ingestor (`infy_stock.csv`, `tcs_stock.csv`).
  - **Signal & Execution Logic:** Auto-Regressive linear weight forecasting (`forecast_next_close`).
  - **Risk Engineering:** 0.05 INR price tick rounding, IST trading session validation, closed session order rejection.
- **EQATS Integration Module:** `src/institutional_integrations/time_series_forecast_nsepy_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `TIME_SERIES_FORECAST_NSEPY`.

## Repo 065. augmentalphawealth/Sectoral-Breadth-Dashboard
- **Repository URL:** `https://github.com/augmentalphawealth/Sectoral-Breadth-Dashboard`
- **Magic Number:** `9100062`
- **Architecture & System Design:** Sectoral advance/decline breadth metrics and percentage of sector constituents trading above EMA 50 / EMA 200 moving averages.
- **Categorization:**
  - **Data Engines:** Multi-symbol sector constituent price matrix parser (`process_sector_constituents`).
  - **Signal & Execution Logic:** Sector breadth calculation (`calculate_sector_breadth`), advance/decline ratio evaluation.
  - **Risk Engineering:** 0.05 INR price tick rounding, IST trading session validation, closed session order rejection.
- **EQATS Integration Module:** `src/institutional_integrations/sectoral_breadth_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `SECTORAL_BREADTH`.

## Repo 066. avhz/RustQuant
- **Repository URL:** `https://github.com/avhz/RustQuant`
- **Magic Number:** `9100063`
- **Architecture & System Design:** Quantitative finance library in Rust providing analytical option pricing (Black-Scholes), Heston stochastic volatility simulation, and Sharpe/Sortino portfolio risk metrics.
- **Categorization:**
  - **Data Engines:** High-performance stochastic path simulator (`simulate_heston_process`).
  - **Signal & Execution Logic:** Analytical Black-Scholes call/put pricing (`black_scholes_price`), Heston stochastic volatility path simulation.
  - **Risk Engineering:** Sharpe and Sortino downside risk calculations (`calculate_portfolio_risk_metrics`), 0.05 INR price tick rounding, IST trading session validation.
- **EQATS Integration Module:** `src/institutional_integrations/rustquant_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `RUSTQUANT`.

## Repo 067. avin1311/nse-bse-dashboard
- **Repository URL:** `https://github.com/avin1311/nse-bse-dashboard`
- **Magic Number:** `9100064`
- **Architecture & System Design:** Multi-exchange quote aggregation (NSE & BSE) and dual-exchange price spread arbitrage evaluation.
- **Categorization:**
  - **Data Engines:** Multi-exchange quote response parser (`aggregate_quotes`).
  - **Signal & Execution Logic:** Dual-exchange price spread arbitrage signal evaluation (`evaluate_arbitrage_spread`).
  - **Risk Engineering:** 0.05 INR price tick rounding, IST trading session validation, closed session order rejection.
- **EQATS Integration Module:** `src/institutional_integrations/nse_bse_dashboard_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `NSE_BSE_DASHBOARD`.

## Repo 068. avirichie/NSE-Closing-Stock-Price-Prediction-Using-LSTM
- **Repository URL:** `https://github.com/avirichie/NSE-Closing-Stock-Price-Prediction-Using-LSTM`
- **Magic Number:** `9100065`
- **Architecture & System Design:** Time-series sequence prediction for NSE stock closing prices using min-max scaling and weighted recurrent LSTM prediction.
- **Categorization:**
  - **Data Engines:** Closing price sequence scaler (`min_max_scale`).
  - **Signal & Execution Logic:** LSTM sequence prediction (`predict_next_close`) and predicted change percentage signal generation.
  - **Risk Engineering:** 0.05 INR price tick rounding, IST trading session validation, closed session order rejection.
- **EQATS Integration Module:** `src/institutional_integrations/nse_closing_lstm_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `NSE_CLOSING_LSTM`.

## Repo 069. ayushmaanbhav/stockmart
- **Repository URL:** `https://github.com/ayushmaanbhav/stockmart`
- **Magic Number:** `9100066`
- **Architecture & System Design:** Real-time stock trading platform and simulation engine in Rust (`backend/src/domain/trading/orderbook.rs`, `portfolio.rs`) providing limit orderbook matching and portfolio equity evaluation.
- **Categorization:**
  - **Data Engines:** Orderbook depth builder and portfolio position state tracker (`evaluate_portfolio_equity`).
  - **Signal & Execution Logic:** Limit order matching engine (`add_limit_order`, `_match_orderbook`) matching top bids and asks.
  - **Risk Engineering:** 0.05 INR price tick rounding, IST trading session validation, closed session order rejection.
- **EQATS Integration Module:** `src/institutional_integrations/stockmart_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `STOCKMART`.

## Repo 071. BarathGB007/nse-options-data-collector
- **Repository URL:** `https://github.com/BarathGB007/nse-options-data-collector`
- **Magic Number:** `9100068`
- **Architecture & System Design:** Automated NSE options data collection and premarket gap analyzer (`collectors/oi_collector.py`, `premarket_collector.py`).
- **Categorization:**
  - **Data Engines:** Option chain Open Interest (OI) snapshot parser and premarket Indicative Equilibrium Price (IEP) fetcher (`process_oi_snapshot`).
  - **Signal & Execution Logic:** Put-Call Ratio (PCR) market bias evaluation and premarket gap percentage classifier (`analyze_premarket_gap`).
  - **Risk Engineering:** 0.05 INR price tick rounding, IST trading session validation, closed session order rejection.
- **EQATS Integration Module:** `src/institutional_integrations/nse_options_data_collector_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `NSE_OPTIONS_DATA_COLLECTOR`.

## Repo 074. beinghorizontal/BhavFnO
- **Repository URL:** `https://github.com/beinghorizontal/BhavFnO`
- **Magic Number:** `9100071`
- **Architecture & System Design:** F&O Bhavcopy parser and monthly options expiry calculator (`def_expiry.py`, `main.py`).
- **Categorization:**
  - **Data Engines:** Monthly options expiry date generator with last Thursday/holiday shift adjustments (`calculate_monthly_expiries`).
  - **Signal & Execution Logic:** CE/PE Open Interest aggregator and weighted Implied Volatility (IV) & Put-Call Ratio (PCR) evaluator (`compute_bhav_iv_pcr`).
  - **Risk Engineering:** 0.05 INR price tick rounding, IST trading session validation, closed session order rejection.
- **EQATS Integration Module:** `src/institutional_integrations/bhavfno_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `BHAVFNO`.

## Repo 075. benimward9621/advanced-nse-momentum-terminal
- **Repository URL:** `https://github.com/benimward9621/advanced-nse-momentum-terminal`
- **Magic Number:** `9100072`
- **Architecture & System Design:** Browser-based research workspace and momentum terminal (`index.html`) providing Relative Strength screening, volatility-adjusted trend scoring, and ETF/sector heatmap analytics.
- **Categorization:**
  - **Data Engines:** Sector rotation and ETF heatmap payload processor.
  - **Signal & Execution Logic:** Mansfield Relative Strength (RS) momentum score evaluator (`calculate_relative_strength`) and volatility-normalized trend detector (`compute_volatility_adjusted_trend`).
  - **Risk Engineering:** 0.05 INR price tick rounding, IST trading session validation, closed session order rejection.
- **EQATS Integration Module:** `src/institutional_integrations/advanced_nse_momentum_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `ADVANCED_NSE_MOMENTUM`.

## Repo 076. BennyThadikaran/eod2
- **Repository URL:** `https://github.com/BennyThadikaran/eod2`
- **Magic Number:** `9100073`
- **Architecture & System Design:** End-of-Day technical charting and market breadth analyzer (`src/renderer/indicators.py`, `src/market_breadth_sync.py`).
- **Categorization:**
  - **Data Engines:** Daily CSV price loader and market breadth sync engine (`evaluate_market_breadth`).
  - **Signal & Execution Logic:** Dorsey Relative Strength (`compute_dorsey_rs`) and Mansfield Relative Strength (`compute_mansfield_rs`) indicator calculators.
  - **Risk Engineering:** 0.05 INR price tick rounding, IST trading session validation, closed session order rejection.
- **EQATS Integration Module:** `src/institutional_integrations/eod2_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `EOD2`.

## Repo 078. BennyThadikaran/NseIndiaApi
- **Repository URL:** `https://github.com/BennyThadikaran/NseIndiaApi`
- **Magic Number:** `9100075`
- **Architecture & System Design:** Python API wrapper and HTTP transport layer for NSE India exchange endpoints (`src/nse/NSE.py`, `src/nse/transport.py`).
- **Categorization:**
  - **Data Engines:** Live quote JSON response parser (`parse_quote_data`) and session cookie transport layer.
  - **Signal & Execution Logic:** Bulk and block deal institutional accumulation/distribution imbalance analyzer (`analyze_bulk_deals`).
  - **Risk Engineering:** 0.05 INR price tick rounding, IST trading session validation, closed session order rejection.
- **EQATS Integration Module:** `src/institutional_integrations/nse_india_api_benny_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `NSE_INDIA_API_BENNY`.

## Repo 082. blitzarx1/netstrat
- **Repository URL:** `https://github.com/blitzarx1/netstrat`
- **Magic Number:** `9100079`
- **Architecture & System Design:** Network graph topology analyzer and synthetic market data generator in Rust (`src/widgets/net_props/graph/cycle.rs`, `src/netstrat/syntetic_data/dataset.rs`).
- **Categorization:**
  - **Data Engines:** Synthetic market dataset mesh resolution generator (`generate_synthetic_dataset`).
  - **Signal & Execution Logic:** Market exchange network graph cycle and arbitrage path detector (`detect_graph_cycles`).
  - **Risk Engineering:** 0.05 INR price tick rounding, IST trading session validation, closed session order rejection.
- **EQATS Integration Module:** `src/institutional_integrations/netstrat_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `NETSTRAT`.

## Repo 083. bohr1005/xcrypto
- **Repository URL:** `https://github.com/bohr1005/xcrypto`
- **Magic Number:** `9100080`
- **Architecture & System Design:** High-performance Rust & Python crypto spot/futures trading framework with Binance connectors, Chat interface, position tracking, and PyAlgo strategy engine (`xcrypto/src/rest.rs`, `xcrypto/src/ws.rs`, `xcrypto/pyalgo/src/lib.rs`).
- **Categorization:**
  - **Data Engines:** Binance spot and futures market data parser and WebSocket stream ingestor.
  - **Signal & Execution Logic:** PyAlgo moving average crossover signal generator and position PnL evaluator (`evaluate_pyalgo_signal`).
  - **Risk Engineering:** 0.05 INR price tick rounding, IST trading session validation, closed session order rejection.
- **EQATS Integration Module:** `src/institutional_integrations/xcrypto_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `XCRYPTO`.

## Repo 084. braverock/nse
- **Repository URL:** `https://github.com/braverock/nse`
- **Magic Number:** `9100081`
- **Architecture & System Design:** R package for Numerical Standard Error (NSE) estimation in time series and Markov Chain Monte Carlo outputs (`R/nse.R`, `R/hirukawa.R`, `R/kernels.R`, `R/boostrap.R`, `R/prewhitening.R`).
- **Categorization:**
  - **Data Engines:** Time series return stream residual variance extractor.
  - **Signal & Execution Logic:** Batch Means (BM), Overlapping Batch Means (OBM), Newey-West Kernel, and Effective Sample Size (ESS) time-series variance estimator (`analyze_time_series`).
  - **Risk Engineering:** 0.05 INR price tick rounding, IST trading session validation, closed session order rejection.
- **EQATS Integration Module:** `src/institutional_integrations/braverock_nse_engine.py`
  - Registered in `IndianBrokerPluginRegistry` as `BRAVEROCK_NSE`.
| 11 | adavarski/DevSecOps-full-integration-chain | https://github.com/sparlit/EQATS/pull/567 | https://github.com/sparlit/EQATS/issues/568 | 2026-09-06T08:19:19.746Z |
| 15 | affaan-m/dprc-autotrader-v2 | https://github.com/sparlit/EQATS/pull/573 | https://github.com/sparlit/EQATS/issues/574 | 2026-09-06T08:23:01.232Z |
| 17 | AI4Finance-Foundation/FinRL-Trading | https://github.com/sparlit/EQATS/pull/575 | https://github.com/sparlit/EQATS/issues/576 | 2026-09-06T08:29:04.271Z |
| 22 | akshaypawar7/WODS | https://github.com/sparlit/EQATS/pull/581 | https://github.com/sparlit/EQATS/issues/582 | 2026-09-06T08:41:50.098Z |
| 24 | akshayz14/indian-stock-tracker | https://github.com/sparlit/EQATS/pull/586 | https://github.com/sparlit/EQATS/issues/587 | 2026-09-06T08:44:15.146Z |
| 26 | AlexWan/OsEngine | https://github.com/sparlit/EQATS/pull/590 | https://github.com/sparlit/EQATS/issues/591 | 2026-09-06T08:46:38.805Z |
| 27 | algotrading-lab/ai-algotrading-agent | https://github.com/sparlit/EQATS/pull/592 | https://github.com/sparlit/EQATS/issues/593 | 2026-09-06T08:48:40.345Z |
| 31 | Ameobea/tickgrinder | https://github.com/sparlit/EQATS/pull/596 | https://github.com/sparlit/EQATS/issues/597 | 2026-09-06T08:52:59.618Z |
| 31 | Ameobea/tickgrinder |  | https://github.com/sparlit/EQATS/issues/600 | 2026-09-06T08:53:58.016Z |
| 32 | amitashwinibhagat/nse-swing-scanner | https://github.com/sparlit/EQATS/pull/601 | https://github.com/sparlit/EQATS/issues/602 | 2026-09-06T08:55:46.395Z |
| 34 | Aneesh540/VSE | https://github.com/sparlit/EQATS/pull/605 | https://github.com/sparlit/EQATS/issues/606 | 2026-09-06T08:57:51.161Z |
| 34 | Aneesh540/VSE |  | https://github.com/sparlit/EQATS/issues/608 | 2026-09-06T08:59:11.156Z |
| 40 | anshulk/nse | https://github.com/sparlit/EQATS/pull/620 | https://github.com/sparlit/EQATS/issues/621 | 2026-09-06T09:03:31.507Z |
| 42 | anthdm/rust-trading-engine | https://github.com/sparlit/EQATS/pull/625 | https://github.com/sparlit/EQATS/issues/626 | 2026-09-06T09:06:06.244Z |
| 66 | ayushmaanbhav/StockMart | https://github.com/sparlit/EQATS/pull/697 | https://github.com/sparlit/EQATS/issues/698 | 2026-09-06T09:38:19.258Z |
| 66 | ayushmaanbhav/StockMart |  | https://github.com/sparlit/EQATS/issues/721 | 2026-09-06T09:48:13.699Z |
| 66 | ayushmaanbhav/StockMart |  | https://github.com/sparlit/EQATS/issues/728 | 2026-09-06T09:50:31.289Z |
| 228 | meticulousCraftman/TickerStore | https://github.com/sparlit/EQATS/pull/1362 | https://github.com/sparlit/EQATS/issues/1363 | 2026-09-06T12:57:17.024Z |
