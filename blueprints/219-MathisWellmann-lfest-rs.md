# Integration Blueprint: lfest-rs into eqats

## Overview
`lfest-rs` is a high‑performance simulated perpetual futures exchange written in Rust. It offers a market data ingestion pipeline, a type‑safe order execution engine, and a built‑in isolated margin risk engine. These components map cleanly onto the three eqats domains: Data Engines, Signal & Execution Logic, and Risk Engineering.

## Data Engines
- **MarketUpdate trait** – defines a uniform way to feed external market data (`Bba`, `Trade`, `Candle`, `SmartCandle`) into the exchange. In eqats this trait can be wrapped as a `MarketDataIngestor` that publishes updates to a shared `MarketState`.
- **MarketState** – aggregates the order book and derives best bid/ask, last price, etc. eqats can reuse this structure as the canonical market view consumed by strategy modules.
- **Fixed‑point arithmetic (`const-decimal`)** – provides deterministic, high‑precision math without floating‑point error. eqats can adopt `const-decimal` for all price, size, and PnL calculations to guarantee cross‑platform consistency.
- **Newtype pattern** – `BaseCurrency`, `QuoteCurrency`, `Fee`, `Leverage`, etc., enforce compile‑time dimensional safety. Adopting similar wrappers in eqats would prevent mixing of quote vs. base units.

## Signal & Execution Logic
- **Order types** – `LimitOrder` (passive, partial fills) and `MarketOrder` (aggressive). eqats can expose these as first‑class order objects; the matching engine from lfest‑rs can be invoked when a strategy emits a signal.
- **Execution trigger** – limit orders are automatically matched when the `MarketState` updates (price crosses the order price). This decouples strategy logic from execution timing; eqats strategies would simply submit orders and let the engine handle fills.
- **Rate limiting** – built‑in throttling for order submissions/cancellations protects the exchange from abusive traffic. eqats can enable the same limits on its order gateway.
- **Leverage & margin mode** – `Leverage` newtype and the choice of margin currency (`QuoteCurrency` for linear, `BaseCurrency` for inverse) let eqats model both perpetual and inverse futures contracts without code duplication.

## Risk Engineering
- **IsolatedMarginRiskEngine** – computes per‑position margin requirements and liquidation prices in real time. Integrating this engine into eqats would give each strategy an isolated risk account, simplifying portfolio‑level risk aggregation.
- **PriceFilter & QuantityFilter** – validate that incoming orders respect tick size, lot size, and min/max notional. eqats can plug these filters into its order validation layer.
- **Fee & Leverage types** – ensure that trading fees, funding rates, and leverage multipliers are applied with correct types, avoiding costly mistakes.
- **Linear vs. inverse contracts** – by setting the margin currency, eqats can support both contract families with a single code base.
- **Future work** – the repository’s TODO list (funding rate settlement, dynamic leverage) maps directly to eqats’ roadmap; implementing `settle_funding_period` and leverage‑adjustment APIs would complete the risk engine.

## Integration Steps
1. **Add lfest‑rs as a dependency** (git submodule or crates.io version).
2. **Wrap MarketUpdate** in an eqats‑specific ingestor that translates external data feeds (WebSocket, Kafka, etc.) into `Bba`/`Trade` structs.
3. **Create a shared MarketState singleton** that strategies read for signal generation and that the matching engine writes to upon fills.
4. **Replace eqats’ numeric primitives** with `const-decimal` wrappers and adopt the newtype patterns for currencies, fees, and leverage.
5. **Plug in the order execution module**: expose `submit_limit_order`, `submit_market_order`, and let lfest‑rs handle the order book and matching.
6. **Enable risk checks**: instantiate `IsolatedMarginRiskEngine` per account, call it before order submission and after each fill to update margin and check liquidation.
7. **Configure filters**: apply `PriceFilter` and `QuantityFilter` derived from contract specifications.
8. **Set margin mode**: choose `QuoteCurrency` (linear) or `BaseCurrency` (inverse) when initializing the `ContractSpecification`.
9. **Monitor & extend**: implement funding rate settlement using the `ClearingHouse` hook; add dynamic leverage API as needed.

## Benefits
- **Deterministic math** eliminates drift in PnL calculations.
- **Type safety** reduces bugs caused by unit mismatches.
- **High throughput** (hundreds of millions of updates per second) meets eqats’ low‑latency requirements.
- **Modular risk engine** enables isolated margin trading without redesigning existing portfolio risk code.

## Conclusion
By adopting lfest‑rs’s market data pipeline, execution engine, and isolated risk components, eqats can gain a battle‑tested, high‑performance foundation for simulated and live leveraged futures trading while preserving its own strategy‑centric architecture.