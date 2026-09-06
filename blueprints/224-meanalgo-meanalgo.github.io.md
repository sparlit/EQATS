# Integration Blueprint for ShoonyaApi into eqats

## Overview
The `meanalgo/meanalgo.github.io` repository provides a thin Python wrapper (`ShoonyaApi`) around the Shoonya OMS REST and WebSocket APIs. It offers comprehensive market data retrieval, order management, and position/risk monitoring capabilities for NSE India equities and futures. This blueprint outlines how to plug these features into the eqats quantitative trading architecture across its three domains: Data Engines, Signal & Execution Logic, and Risk Engineering.

---

## 1. Data Engines

### Features to Integrate
- **get_quotes(symbol)** – Real‑time LTP, bid/ask, volume.
- **get_time_price_series(exchange, token, start, end)** – Intraday OHLCV series.
- **get_daily_price_series(exchange, token, start, end)** – Daily OHLCV series.
- **get_option_chain(exchange, symbol)** – Full option chain for volatility surface construction.
- **get_security_info(symbol)** – Instrument metadata (lot size, tick size, etc.).
- **WebSocket API** (`start_websocket`, `subscribe`, `unsubscribe`) – Low‑latency tick stream for signal generation.

### Integration Steps
1. **Create a Data Engine Adapter** (`eqats/data/adapters/shoonya.py`) that wraps the above methods.
2. **Normalize Output** – Convert Shoonya JSON responses into eqats canonical `MarketTick`, `Bar`, and `OptionChain` objects.
3. **Historical Backfill** – Use `get_daily_price_series` and `get_time_price_series` to populate the eqats historical store on startup.
4. **Real‑time Subscription** – Launch a background websocket listener per instrument; push ticks into eqats’ `TickBus` for downstream signal processors.
5. **Error Handling & Retry** – Map Shoonya `stat: Not_Ok` responses to eqats retry logic with exponential backoff.

---

## 2. Signal & Execution Logic

### Features to Integrate
- **Order Submission** – `place_order` (supports LIMIT, MARKET, SL‑LMT, SL‑MKT, etc.).
- **Order Management** – `modify_order`, `cancel_order`, `exit_order`.
- **Product Conversion** – `product_convertion` for switching between CNC/MIS/NRML.
- **Order & Trade Book** – `get_orderbook`, `get_tradebook`, `get_singleorderhistory` for reconciliation and audit.
- **WebSocket Callbacks** – Use tick data to generate mean‑reversion signals (e.g., Z‑score, Bollinger Band).

### Integration Steps
1. **Execution Adapter** (`eqats/execution/brokers/shoonya.py`) exposing `send_order`, `cancel_order`, `modify_order`, `close_position`.
2. **Order Object Mapping** – Translate eqats `Order` (side, quantity, price, type, product) to Shoonya API parameters (`trantype`, `prctyp`, `prd`, etc.).
3. **Execution Engine Hook** – Register the adapter with eqats’ `ExecutionEngine`; on signal generation, call `send_order`.
4. **Order Status Sync** – Periodically poll `get_orderbook`/`get_tradebook` to update eqats’ internal order state and fill reconciliation.
5. **Signal Generation** – In `eqats/signals/mean_reversion.py`, subscribe to the websocket tick stream, compute rolling statistics, and emit `Signal` objects when thresholds are breached.
6. **Product Handling** – Use `get_security_info` to fetch lot size and tick size; enforce correct quantity rounding before calling `place_order`.

---

## 3. Risk Engineering

### Features to Integrate
- **Position Monitoring** – `get_holdings` (demat holdings) and `get_positions` (intraday MIS/NRML).
- **Limits & Margin** – `get_limits` for available cash, margin utilized, and exposure limits.
- **Risk‑Based Order Reduction** – Use `exit_order` to flatten positions when risk limits are breached.

### Integration Steps
1. **Risk Adapter** (`eqats/risk/brokers/shoonya.py`) providing `get_current_positions`, `get_available_margin`, `get_holdings`.
2. **Pre‑Trade Risk Checks** – Before sending an order, query `get_limits` to ensure sufficient margin; compute proposed position change and reject if it would exceed configured VaR or leverage limits.
3. **Post‑Trade Monitoring** – Run a periodic task (e.g., every 30 s) that calls `get_positions` and `get_holdings` to update eqats’ risk engine; trigger alerts or automatic `exit_order` if drawdown or concentration limits are breached.
4. **Margin Calls** – If `get_limits` shows `marginused` approaching `marginavailable`, reduce position sizes via `exit_order` proportional to excess usage.
5. **Integration with eqats Risk Engine** – Expose the adapter as a `RiskProvider`; the eqats `RiskManager` will call its methods to compute real‑time P&L, leverage, and margin utilization.

---

## 4. Deployment & Configuration

- **Credentials** – Store Shoonya API keys (`userid`, `password`, `twoFA`, `vendor_code`, `api_secret`, `imei`) in eqats’ secrets manager; inject them into the adapter at initialization.
- **Environment Variables** – `SHOONYA_API_KEY`, `SHOONYA_USERID`, etc.
- **Logging** – Adapter logs request/response payloads (masking secrets) to eqats’ structured logger for audit.
- **Testing** – Use the provided example scripts in the repository as integration test scaffolding; mock the HTTP layer for unit tests.

---

## 5. Summary

By wrapping the ShoonyaApi endpoints in eqats‑specific adapters, we gain:
- **Robust market data feed** (historical + real‑time) for strategy development.
- **Direct order routing** with full support for complex order types and product conversions.
- **Real‑time risk visibility** via holdings, positions, and limits, enabling automated risk‑based order adjustments.

This integration enables eqats to execute mean‑reversion strategies on NSE India futures and equities while maintaining strict risk controls and seamless data flow.

---

*Generated from the ShoonyaApi README (meanalgo/meanalgo.github.io).*