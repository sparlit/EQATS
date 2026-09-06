# Integration Blueprint for netstrat Features into eqats

## Overview
netstrat is a Rust‑based backtesting and visualization tool built with egui. It provides a Binance tick‑data client, a graph‑based strategy constructor, a backtesting engine, and a graph analysis module for ML‑driven strategies.

## Data Engines
- **Binance client for tick data download and visualization** (~90% complete).
  This component can be extracted as a reusable Rust crate (`netstrat-data`) and plugged into eqats’ data‑engine layer to supply historical and real‑time market data.
  Integration steps:
  1. Publish the client as a crate with a simple API (`fetch_klines`, `subscribe_ticks`).
  2. Wrap it in eqats’ data‑ingest abstraction (e.g., `DataSource` trait) so eqats can swap between Binance, CSV, or other feeds.
  3. Store incoming ticks in eqats’ time‑series store (e.g., Arrow or InfluxDB) for downstream signal generation.

## Signal & Execution Logic
- **Graph‑based trading strategy constructor** (~10% complete).
  The visual node‑graph editor lets users build strategies by connecting indicator, signal, and order nodes.
  Integration ideas:
  - Reuse the egui‑based graph UI (or the upcoming `egui_graphs` replacement) as a front‑end for eqats’ strategy designer.
  - Define a canonical node library (moving average, RSI, crossover, etc.) that maps to eqats’ signal DSL.
  - On export, serialize the graph to eqats’ internal strategy representation (e.g., a directed acyclic graph of `Signal` and `Execution` structs).
  - The exported strategy can then be executed by eqats’ live‑trading or backtesting engine.

- **Backtesting tool** (0% complete).
  Although not yet implemented, netstrat’s planned backtesting workflow aligns with eqats’ engine.
  Once netstrat delivers a backtesting core, it could be offered as an alternative backend via a feature flag, allowing users to choose between eqats’ native backtester and the netstrat version.

- **Graph analysis tool to support ML based trading strategies** (~40% complete).
  This module performs feature extraction from strategy graphs (e.g., computing graph‑based metrics) useful for ML models.
  Integration:
  - Expose the analysis functions as a Rust library (`netstrat-graph-analysis`).
  - Feed its outputs into eqats’ ML pipeline as additional features for model training or inference.

## Risk Engineering
- No explicit risk‑management features are described in the netstrat README.
  Consequently, eqats would need to supply its own risk limits, position sizing, and monitoring layers when integrating netstrat’s strategy construction and execution components.

## Summary
By extracting netstrat’s Binance data client, egui‑based graph strategy builder, and analysis utilities into reusable crates, eqats can enrich its data‑ingestion options, provide a powerful visual strategy design environment, and augment its ML‑strategy workflow—while retaining its own risk‑engineering subsystem.
