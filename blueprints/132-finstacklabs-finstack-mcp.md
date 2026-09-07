# Integration Blueprint for FinStack MCP into eqats

## Overview
FinStack MCP provides a rich set of market data tools, AI‑agent debate signals, and risk analytics tailored for Indian markets. Integrating these into eqats can enhance data coverage, signal generation, and risk monitoring.

## Data Engines Integration
- **Market Data Ingestion**: Use FinStack's NSE/BSE real‑time data feed (via Angel One) to supplement eqats' existing market data pipeline. Implement a connector that calls FinStack's `get_market_data` tool (exposed via MCP) to fetch OHLCV, fundamentals, and corporate actions.
- **Fundamentals & Financials**: Pull balance‑sheet, P&L, and cash‑flow data from FinStack's fundamentals module to enrich eqats' fundamental store.
- **FII/DII Flows**: Integrate FinStack's FII flow tool to feed foreign institutional ownership changes into eqats' flow engine.
- **Options Data**: Leverage FinStack's options Greeks and OI buildup signals for eqats' derivatives analytics.
- **Alternative Data**: Incorporate social sentiment (StockTwits, Reddit, Economic Times) and promoter‑pledge/block‑deal feeds via FinStack's social and corporate‑action tools.
- **GST‑to‑Stock & Budget Analyzer**: Use these niche India‑specific datasets for sector‑level macro signals.

Implementation: create an eqats data‑engine adapter that registers FinStack as a remote MCP endpoint (Streamable HTTP) and maps each FinStack tool to eqats' canonical data schemas (e.g., `MarketBar`, `Fundamentals`, `Flow`, `OptionsChain`, `Sentiment`). Add caching layer and rate‑limit handling per FinStack's guidelines.

## Signal & Execution Logic Integration
- **AI‑Agent Debate Signals**: Wrap FinStack's multi‑agent stock brief (`get_stock_brief`) as a signal generator that outputs a consensus direction (BUY/HOLD/SELL) with confidence. Feed this into eqats' signal aggregator as a weighted expert signal.
- **Options Flow Signals**: Use FinStack's intraday F&O setup (`get_fno_setup`) to produce directional option signals (BUY_CE, BUY_PE, NO_TRADE) with ATM strike zone and confidence; map to eqats' options signal schema.
- **Market‑Direction Probability**: Convert FinStack's Nifty probability output (`get_nifty_probability`) into a eqats market‑regime signal.
- **Morning Brief & Watchlist Ranking**: Schedule FinStack's 8:15 AM F&O brief and watchlist ranking tools to produce pre‑market eqats signals for trade‑idea generation.
- **Social Sentiment Signal**: Transform FinStack's social buzz score into a short‑term sentiment factor.

Implementation: create eqats signal plugins that call the respective FinStack MCP tools, normalize outputs to eqats' `Signal` format (timestamp, ticker, direction, strength, metadata), and route them through the signal fusion engine.

## Risk Engineering Integration
- **Portfolio Risk Scan**: Use FinStack's portfolio risk tool (`analyze_portfolio`) to compute sector concentration, pledged promoter exposure, FII exposure, XIRR, and diversification score. Feed these metrics into eqats' risk monitor as additional risk factors.
- **Scam Detection**: Integrate FinStack's Telegram tip‑channel analyzer to produce a risk score for external signal sources; eqats can down‑weight or flag signals originating from high‑risk channels.
- **Risk Limits & Alerts**: Configure eqats' risk engine to trigger alerts when any FinStack‑derived risk metric exceeds user‑defined thresholds (e.g., promoter pledge > 20%, sector concentration > 30%).
- **Position Sizing Adjustments**: Use the diversification score and XIRR outputs to inform eqats' position‑sizing algorithm (e.g., reduce size when diversification low).

Implementation: develop eqats risk adapters that pull FinStack risk metrics via MCP, store them in the risk database, and expose them through eqats' risk API for real‑time monitoring and limit checks.

## Deployment & Operational Considerations
- **MCP Endpoint**: Deploy FinStack MCP as a remote Streamable HTTP service (following the repo's roadmap) with OAuth2 protection, rate limiting, and monitoring.
- **Fault Tolerance**: Implement retry logic and fallback to local data sources if the FinStack endpoint is unavailable.
- **Governance**: Align FinStack's usage with eqats' data‑usage policies; retain audit logs of MCP calls.
- **Testing**: Write unit tests that mock FinStack MCP responses; run integration tests against a staging FinStack instance.

## Expected Benefits
- Expanded Indian‑market data coverage without additional licensing cost.
- Enhanced signal quality via multi‑agent debate and alternative data.
- Robust risk monitoring with India‑specific metrics (promoter pledge, FII flow, GST context).
- Faster time‑to‑market for new India‑focused strategies via ready‑made MCP tools.
