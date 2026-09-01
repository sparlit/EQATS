# EQATS VERSION 8.4 MASTER TODO TASKS LIST

## Phase 1: Core Execution Core & Pending Orders
- [x] 1.1 Verify Safety Kernel Invariants (`INV-001` through `INV-015`) in `brain.py`.
- [x] 1.2 Implement Limit/Stop Pending Order execution rules with strict SL/TP/TSL/TTP.
- [x] 1.3 Upgrade dynamic adaptive volatility slippage controls in `connector.py` / `brain.py`.

## Phase 2: Microservices Mesh & Data Fabric
- [x] 2.1 Integrate Tokio/Rust C-extensions in `eqats_rust_core`.
- [x] 2.2 Wire PostgreSQL, ClickHouse, Valkey, and Pulsar streaming adapters in `institutional_integrations/enterprise_gateway.py`.
- [x] 2.3 Integrate adapted Fincept Terminal engines (`options_derivatives_engine`, `finagent_hedgefund_swarm`, `extended_market_connectors`, `quant_portfolio_analytics`, `alpha_strategies_library`).

## Phase 3: Swarm Agents & Hardware Auto-Tuning
- [x] 3.1 Verify Multi-Agent strategy swarm parallel evaluation in `brain_agents_orchestrator.py`.
- [x] 3.2 Auto-detect hardware vitals (CPU, RAM, GPU, Ping) and display real-time metrics on VTL screen.

## Phase 4: Full Integration Verification & Version 8.4 Upgrades
- [x] 4.1 Update all version tags, headers, documentation, GUI dialogs, and MT5 EA to Version 8.4.
- [x] 4.2 Run full test suite across all strategy rules, options pricing, hedge fund agents, ML models, hardware vitals, and v8.4 upgrades.
- [x] 4.3 Complete pre-commit review and submit changes.
