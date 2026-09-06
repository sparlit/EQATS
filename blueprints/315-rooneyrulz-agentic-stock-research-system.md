# Integration Blueprint for eqats

## Overview
The agentic-stock-research-system provides a mature multi-agent pipeline for NSE stock analysis that can be plugged into eqats to enhance its data engines, signal generation, and risk management.

## Data Engine Integration
- **Real‑time NSE Market Data**: Replace or augment eqats’ current market data feed with the Market Data Agent which streams live prices, volume, and technical indicators (RSI, MACD, moving averages) via Bright Data MCP.
- **News Sentiment Engine**: Integrate the News Analyst Agent to scrape recent financial news, perform sentiment classification, and feed sentiment scores into eqats’ feature store.
- **Stock Universe Scanner**: Use the Stock Finder Agent to pre‑filter the NSE universe for liquid, high‑momentum large‑ and mid‑cap stocks, producing a dynamic watchlist that eqats can consume.
- **Export & Storage**: Leverage the existing CSV export functionality to persist raw agent outputs for back‑testing or audit trails.

## Signal & Execution Logic Integration
- **Recommendation Agent as Signal Generator**: Treat the BUY/SELL/HOLD output with target price, entry range, stop‑loss, and confidence as a raw signal. eqats can map these to its internal signal format (direction, strength, price levels).
- **Time‑Horizon Adaptation**: The agent’s short‑term (1‑7 days) and medium‑term (1‑4 weeks) horizons can be translated into eqats’ signal expiry or order‑duration fields.
- **Execution Hook**: When a signal confidence exceeds a configurable threshold (e.g., HIGH), eqats can trigger a limit order at the suggested entry price, attach the agent‑provided stop‑loss, and set a take‑profit at the target price.

## Risk Engineering Integration
- **Stop‑Loss Adoption**: Directly use the agent’s stop‑loss level (e.g., 3.2 % below entry) as eqats’ initial stop‑loss for the position.
- **Position Sizing Guidance**: Incorporate the agent’s volatility‑based position sizing recommendation into eqats’ risk‑module to compute lot size.
- **Risk‑Reward Filter**: Enforce the agent’s minimum 1:2 risk‑reward ratio as a pre‑trade filter in eqats.
- **Confidence Scoring**: Map the agent’s HIGH/MEDIUM/LOW confidence to eqats’ signal confidence score, allowing the portfolio manager to weight signals accordingly.
- **Time‑Horizon Specification**: Use the agent’s time horizon to set the maximum holding period or to trigger a time‑based exit if the target is not reached.

## Implementation Steps
1. **Environment Setup** – Add Bright Data MCP, OpenAI, and Streamlit dependencies to eqats’ `requirements.txt`.
2. **API Keys** – Store `BRIGHTDATA_TOKEN` and `OPENAI_API_KEY` in eqats’ secret manager.
3. **Wrapper Service** – Create a thin Python service (`nse_agent_wrapper.py`) that launches the Stock Finder, Market Data, News Analyst, and Recommendation agents and returns a normalized JSON signal.
4. **Signal Adapter** – In eqats’ signal ingestion layer, call the wrapper, map fields:
   - `direction` ← recommendation (BUY→+1, SELL→-1, HOLD→0)
   - `entry_low`, `entry_high` ← entry strategy range
   - `stop_loss` ← stop loss level
   - `take_profit` ← target price
   - `confidence` ← map HIGH→0.9, MEDIUM→0.6, LOW→0.3
   - `horizon` ← time horizon string
5. **Risk Module Update** – Feed `stop_loss`, `confidence`, and `horizon` into eqats’ position‑sizing and risk‑limit functions.
6. **Testing & Deployment** – Run the wrapper in a staging environment, validate CSV exports, and gradually roll out to live trading with paper‑trading first.

## Expected Benefits
- Immediate access to real‑time NSE data and news sentiment without building new scrapers.
- Enhanced signal quality through multi‑agent consensus (technical + fundamental + sentiment).
- Built‑in risk controls (stop‑loss, position sizing, risk‑reward) that reduce manual rule‑engineering.
- Flexible time‑horizon signals enabling both intraday and swing‑trading strategies within eqats.

---
*This blueprint reuses the existing agentic‑stock‑research‑system codebase; no duplication of effort is required.*