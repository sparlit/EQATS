# Integration Blueprint for NSE-BSE-Arbitrage-bot into eqats

## Overview
The NSE-BSE-Arbitrage-bot repository provides a simple arbitrage trading algorithm for the NSE and BSE exchanges. Its core components are:
- **Data Import**: Pulls market data directly from the broker API.
- **Signal Generation**: Scans price differences between exchanges to detect arbitrage opportunities.
- **Execution**: Places buy and sell orders when an opportunity is found.
- **Risk Management**: Includes position sizing limits and a kill switch to halt trading under adverse conditions.

## How to Map to eqats Domains

### Data Engines
- Replace or augment eqats' current market data feeder with the bot's broker import module.
- The import function can be wrapped as a reusable connector that supplies real‑time tick data for NSE and BSE instruments.
- Storage: The bot does not persist data; eqats can add its own time‑series database (e.g., TimescaleDB) to archive the incoming ticks for later analysis.

### Signal & Execution Logic
- The opportunity scanner can be extracted as a signal generator that outputs a signal when the cross‑exchange spread exceeds a configurable threshold.
- eqats can plug this signal into its existing strategy engine, using the bot's order‑placement functions as the execution adapter.
- The bot's buy/sell logic can be refactored to use eqats' order management system (OMS) while preserving the same price‑ and quantity‑calculation.

### Risk Engineering
- The risk management module (position limits, stop‑loss checks) can be mapped onto eqats' risk engine.
- The kill switch (a global flag that disables further trading) maps directly to eqats' emergency halt mechanism.
- By exposing configurable risk parameters (max notional per trade, daily loss limit), the bot's risk controls can be tuned within eqats' risk‑settings UI.

## Integration Steps
1. **Isolate the broker import** into a standalone package (`eqats-data-broker`).
2. **Wrap the scanning logic** in a signal plugin (`eqats-signal-arbitrage`) that consumes the broker feed.
3. **Adapt the order execution** to call eqats' OMS API instead of the bot's direct broker calls.
4. **Plug the risk controls** into eqats' risk service, mapping limits and the kill switch to existing risk limits and emergency stop.
5. **Configure** the new components via eqats' YAML/JSON config, reusing the bot's threshold and limit parameters.
6. **Test** in a sandbox environment, verifying that data flow, signal generation, order execution, and risk limits behave as expected.
7. **Deploy** to production with monitoring (eqats' existing observability stack) to track arbitrage P&L and risk metrics.

## Benefits
- Leverages a proven, simple arbitrage detection algorithm to expand eqats' strategy library.
- Provides a ready‑made broker connector reducing development time for NSE/BSE market data.
- Adds a clear kill‑switch pattern that can be hardened within eqats' risk framework.

## Considerations
- The bot is marked educational; ensure compliance with broker regulations and exchange rules before live deployment.
- The original code lacks error handling and logging; these should be strengthened to meet eqats' production standards.
- Since the bot does not persist data, eqats must add its own storage for audit and back‑testing purposes.
