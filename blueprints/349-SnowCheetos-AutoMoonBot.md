# Integration Blueprint for AutoMoonBot into eqats

## Overview
Integrate the heterogeneous GNN+RL trading core from AutoMoonBot as a strategy plugin within eqats.

## Modules

### Data Engines (eqats/src/data_engines/automoonbot/)
- graph_builder.rs: Constructs a heterogeneous graph where nodes represent assets, news entities, macro indicators; edges encode temporal, semantic, and correlation relationships.
- data_ingest.rs: Async scraper for public data (news RSS, HTML, macro APIs) feeding into the graph builder.
- feature_normalizer.rs: Standardizes node/edge features (z-score, log returns) for GNN consumption.

### Signal & Execution Logic (eqats/src/signal_execution/automoonbot/)
- gnn_model.rs: Wrapper around tch-rs Torch module implementing a Relational Graph Convolutional Network (RGCN) to produce node embeddings.
- rl_policy.rs: Actor‑critic network (MLP) consuming pooled graph embeddings to output action probabilities (long/short/flat) and value estimate.
- executor.rs: Translates policy actions into order requests, applying a fixed‑fraction kelly‑style sizing derived from the 0.75% edge.

### Risk Engineering (eqats/src/risk_engineering/automoonbot/)
- risk_manager.rs: Monitors portfolio VaR, enforces max drawdown, and adjusts position scales; implements hedging via inverse‑correlation assets.
- reward_shaper.rs: Adjusts RL reward with penalty for leverage excess and drawdown, encouraging the win‑small‑or‑lose‑big philosophy.

## Data Flow
1. data_ingest pulls raw public data → graph_builder creates/updates heterogeneous graph.
2. feature_normalizer processes graph → gnn_model emits embeddings.
3. Embeddings pooled → rl_policy outputs trade signals.
4. executor converts signals to orders, subject to risk_manager limits.
5. Post‑trade feedback updates reward signal for RL training.

## Build & Test
- Add automoonbot as a path dependency in Cargo.toml.
- Enable torch feature for tch-rs.
- Run cargo test --package eqats_strategies --lib to verify module compiles.

## Future Work
- Expose a Python/PyO3 binding for rapid prototyping.
- Replace placeholder data sources with production‑grade feeds.
- Tune GNN hyper‑parameters via eqats’ experiment tracking.
