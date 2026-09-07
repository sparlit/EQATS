# Integration Blueprint: RustQuant → eqats

## Overview
RustQuant is a pure‑Rust quantitative finance library offering modules for data handling, instrument pricing, stochastic modeling, machine learning, and a basic limit‑order book. Its permissive dual MIT/Apache‑2.0 license and active CI/CD make it a suitable candidate for integration into the eqats quantitative trading platform.

## Data Engines
- **Data module**: Provides CSV, JSON, and Parquet readers/writers plus a Yahoo! Finance downloader. eqats can reuse these components to ingest historical market data, term‑structures, and curves directly into its feature store or time‑series database.
- **ISO module**: Supplies ISO‑4217 currency, ISO‑3166 country, and ISO‑10383 market identifier codes. This can standardise symbol mapping across eqats’ data pipelines, ensuring consistent instrument identifiers.

## Signal & Execution Logic
- **Instruments module**: Implements pricing for Bonds, Options, and Money market instruments. eqats can call these pricers to generate fair‑value signals or to mark‑to‑market positions in real time.
- **Trading module**: Contains a basic limit‑order book (LOB) implementation. eqats could embed this LOB as a matching engine for back‑testing or for simulating execution venues.
- **Portfolio module**: Defines a `HashMap`‑based `Position` collection. Integrating this gives eqats a ready‑made position‑keeping layer that can be synced with risk checks.
- **ML module**: Offers linear/logistic regression and k‑nearest neighbours. These can be used to build alpha signals or to predict transaction costs within eqats’ signal generation pipeline.

## Risk Engineering
- **Math module**: Includes statistical distributions, PDF/CDF, risk‑reward metrics, and optimisation routines. eqats can leverage these for VaR, ES calculations, and portfolio optimisation.
- **Autodiff module**: Provides algorithmic adjoint differentiation for fast gradient computation. This enables efficient sensitivity analysis (Greeks) and gradient‑based risk metrics.
- **Stochastics module**: Generates Brownian motions and short‑rate processes (CIR, OU, Vasicek, Hull‑White). Useful for Monte‑Carlo risk simulation and stress testing inside eqats.
- **Models module**: Hosts various quantitative finance models (Brownian Motion variants, short‑rate models, curve models). eqats can plug these into its risk engine for scenario generation and model‑based P&L attribution.

## Integration Steps
1. **Dependency addition** – Add `RustQuant` as a crate dependency in eqats’ `Cargo.toml`.
2. **Data layer** – Replace custom CSV/JSON parsers with RustQuant’s `data::read_*` functions; use `iso` codes for instrument master data.
3. **Signal generation** – Call `instruments::bond_price`, `instruments::option_price`, etc., to compute fair‑value signals; feed ML outputs from `ml::regression` into strategy logic.
4. **Execution simulation** – Use `trading::LimitOrderBook` to simulate order matching during back‑tests; hook portfolio updates via `portfolio::Position` updates.
5. **Risk calculations** – Invoke `math::var`, `math::expected_shortfall`, and `autodiff::gradient` for Greeks; run Monte‑Carlo paths with `stochastics::cir_process` etc.; aggregate risk via portfolio positions.
6. **Testing & CI** – Leverage existing RustQuant CI (GitHub Actions) to run eqats’ test suite; ensure compatibility via version pinning.

## Conclusion
By adopting RustQuant’s well‑tested, pure‑Rust components, eqats can accelerate development of its data ingestion, signal generation, execution simulation, and risk monitoring subsystems while benefiting from a permissive license and active maintenance.