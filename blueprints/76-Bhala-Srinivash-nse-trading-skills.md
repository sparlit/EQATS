# Integration Blueprint: nse-trading-skills into eqats

## Overview
The nse-trading-skills repository provides a set of Claude Code skills that encapsulate Indian‑equity‑focused trading analysis frameworks. Each skill is a self‑contained prompt module that can be invoked by an AI agent to perform tasks such as technical analysis, position sizing, stop‑loss placement, etc. Because the skills are dependency‑free and rely only on supplied price data (or optional live/historical feeds via Groww MCP or yfinance), they can be plugged into eqats as interchangeable analytical components.

## Mapping to eqats Domains

| eqats Domain | Corresponding nse‑trading‑skills Features |
|--------------|-------------------------------------------|
| Data Engines | • Groww MCP connector – live quotes, bid/ask depth, technical indicators (RSI, MACD, Bollinger, ADX, ATR), historical candles.
• Optional yfinance wrapper – historical OHLCV for NSE/BSE symbols (.NS, .BO).
• Manual price input path – skills work with user‑supplied numbers, enabling eqats to feed its own market‑data cache.

| Signal & Execution Logic | • technical-analysis – trend identification, support/resistance, volume, indicator dashboard (RSI, MACD, Bollinger, ADX).
• multi-timeframe-analysis – 3‑screen method (weekly/daily/hourly) with confluence scoring.
• rsi-divergence – regular & hidden divergence detection with confirmation rules.
• fibonacci-trading – retracement entry zones, extension targets, confluence zone identification.
• nse-trading-toolkit – master orchestrator that runs the above in sequence and outputs a structured trade idea (entry, stop, target, scenarios).

| Risk Engineering | • position-sizing – fixed fractional, ATR‑based, Kelly criterion sizing, leverage adjustments.
• stop-loss-strategies – structure‑based, ATR‑based, S/R‑based, moving‑average stops with buffer rules.
• trailing-stops – ATR trail, structure trail, MA trail, chandelier exit, hybrid approach.
• risk-reward-ratio – R:R calculation, minimum R:R by win‑rate, trade filtering, expected value.

## Integration Steps

1. **Skill Packaging**
   - Clone the repo or download the SKILL.md files for each desired skill.
   - Place them under eqats/skills/<skill-name>/ (mirroring the .claude/skills layout) so that eqats’ skill loader can discover them.

2. **Data Engine Adapter**
   - Implement a thin adapter in eqats’ data layer that can:
     - Query the Groww MCP endpoint (via the MCP client) for live quotes and indicator bundles when a skill requests market data.
     - Fall back to yfinance (or eqats’ internal historical store) for historical candles.
     - Provide a simple JSON payload {symbol, price, timestamp, indicators...} that matches the format expected by the skill prompts (the skills currently expect the user to give numbers; we can inject them as part of the prompt context).
   - The adapter will be invoked by the skill execution layer before prompting the LLM.

3. **Signal Engine Hook**
   - Extend eqats’ signal engine to register each skill as a signal provider.
   - When a new bar/tick arrives, the engine:
     1. Gathers the latest data via the adapter.
     2. Constructs a prompt for the skill (e.g., 'Analyze RELIANCE' plus the data JSON).
     3. Calls the LLM (Claude) with the skill’s SKILL.md as system guidance.
     4. Parses the LLM output into a standardized signal object (direction, strength, entry zone, stop‑loss, target, confidence).
   - The orchestrator skill (nse-trading-toolkit) can be used to combine multiple provider outputs into a single consolidated signal.

4. **Risk Engine Integration**
   - Feed the signal’s suggested entry, stop, and target into eqats’ risk engine.
   - The risk engine will:
     - Run the position-sizing skill to compute lot size based on account equity and risk per trade.
     - Validate or adjust stop‑loss/trailing‑stop levels using the stop-loss-strategies and trailing-stops skills.
     - Apply the risk-reward-ratio skill to filter out setups that do not meet the portfolio’s minimum R:R threshold.
   - Because the skills are prompt‑based, the risk engine can also request explanations (e.g., 'Why is this ATR‑based stop chosen?') for audit trails.

5. **Execution & Monitoring**
   - Once the risk‑approved order is generated, eqats’ execution module places the order via the broker API (e.g., Groww via MCP or another broker).
   - The trailing-stops skill can be re‑invoked on each market update to dynamically adjust the stop price, with the updated stop fed back to the execution layer for order amendment.

6. **Configuration & Extensibility**
   - Provide a YAML config to enable/disable individual skills, choose data source (Groww vs yfinance vs internal), and set parameters like risk‑per‑trade, max leverage, etc.
   - Contribute new skills (Ichimoku, Elliott Wave, VWAP, options) by following the same SKILL.md template and adding them to the eqats skills directory.

## Benefits

- Zero‑dependency analysis: The core logic lives in prompts, making it easy to audit and modify without touching code.
- Indian‑market specificity: All examples, currency (INR), exchange symbols, settlement (T+1), circuit limits, and cost assumptions are already baked into the skills.
- Leverages eqats’ strengths: eqats supplies robust, low‑latency market data and order routing; the skills supply sophisticated, explainable analytics.
- Rapid experimentation: Traders can toggle skills on/off or swap in new ones without redeploying the entire strategy engine.

## Example Flow

1. User asks eqats: 'Should I buy TATAMOTORS at current levels?'
2. eqats fetches live quote for TATAMOTORS.NS via Groww MCP.
3. The technical-analysis skill receives the prompt and data, returns trend, S/R, indicator dashboard.
4. The multi-timeframe-analysis skill adds weekly/daily/hourly confluence.
5. The rsi-divergence skill checks for divergence on the daily chart.
6. The fibonacci-trading skill plots retracement levels from the recent swing.
7. The nse-trading-toolkit skill synthesizes the above into a trade idea: entry 1800, stop 1720, target 2050, with three probabilistic scenarios.
8. The risk engine runs position-sizing (account ₹5 L, risk 1% → ₹5 k → 62 shares), validates stop via stop-loss-strategies, checks R:R (≈4.6) passes filter.
9. eqats places a limit order for 62 shares at 1800, attaches a trailing‑stop rule from the trailing-stops skill (ATR trail with 1.5×ATR).
10. On each new tick, eqats re‑runs the trailing‑stop skill to update the stop price and amends the order if needed.

## Conclusion

By treating each nse-trading-skills module as a pluggable, prompt‑driven analytics block, eqats can instantly gain a comprehensive suite of Indian‑equity‑focused technical, sizing, and risk tools without writing new quantitative code. The integration hinges on thin adapters for data and a uniform skill‑invocation interface, preserving eqats’ high‑performance core while enriching its decision‑making with explainable, AI‑augmented analysis.
