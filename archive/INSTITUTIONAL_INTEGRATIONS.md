# Institutional Integrations Catalog

The Autonomous Trading System bundles 30 specialized integration modules under
`institutional_integrations/`. Each module is independently importable and
participates in the broader event bus / risk-gated order pipeline.

## Categories

### Execution & Order Management
| Module | Purpose |
|---|---|
| `universal_broker_adapter.py` | Broker-agnostic order routing shim. |
| `drl_execution_agent.py` | DRL (SAC/DDPG) execution agent. |
| `execution_slicing.py` | TWAP/VWAP order slicing. |
| `go_gateway.py` | Go-bridge gateway for low-latency calls. |
| `rust_bridge.py` | Rust-bridge gateway for compute-heavy paths. |

### Portfolio & Risk
| Module | Purpose |
|---|---|
| `portfolio_optimizer.py` | CVXPY/QAOA portfolio solver. |
| `mcts_risk_engine.py` | Monte Carlo Tree Search risk engine. |
| `cointegration_pairs.py` | Pairs trading via cointegration. |
| `options_gex_engine.py` | Options gamma exposure engine. |
| `trade_memory_protocol.py` | Trade journal/memory protocol. |

### Market Microstructure & Flow
| Module | Purpose |
|---|---|
| `order_flow_imbalance.py` | Order book imbalance signals. |
| `whale_tracker.py` | Large-order/whale flow detection. |
| `smc_ict_engine.py` | Smart Money Concepts / ICT engine. |
| `spatial_supply_chain.py` | Spatial supply/demand analysis. |

### Prediction & ML
| Module | Purpose |
|---|---|
| `tft_tcn_predictor.py` | Temporal Fusion Transformer + TCN. |
| `machine_learning.py` | Classical ML toolkit. |
| `causal_inference_engine.py` | Causal graph inference. |
| `advanced_math.py` | Numerical helpers (linear algebra, opt). |
| `data_science.py` | EDA, feature engineering, statistics. |
| `natural_language.py` | NLP for news/earnings transcripts. |

### Backtesting & Validation
| Module | Purpose |
|---|---|
| `backtest_engine.py` | Vectorized backtest runner. |
| `comprehensive_suite.py` | Aggregated institutional test suite. |
| `alert_dispatcher.py` | Multi-channel alert fan-out. |

### Self-Healing & Ops
| Module | Purpose |
|---|---|
| `brain_self_healer.py` | Anomaly detection + auto-recovery. |
| `fix_engine.py` | Auto-remediation patch engine. |
| `databases.py` | Specialized DB adapters (QuestDB ILP etc.). |

### Quantum / Experimental
| Module | Purpose |
|---|---|
| `quantum_local_llm.py` | Local LLM for offline reasoning. |
| `quantum_quantum_engine.py` | Quantum-inspired simulator. |

## Integration Pattern

All modules:
1. Subscribe to `event_bus.py` events
2. Emit signals via the same bus
3. Are wrapped by `brain_agents_orchestrator.py` for lifecycle management
4. Pass through the risk gate before any order is sent

## Adding a New Module

1. Create `institutional_integrations/<name>.py`
2. Implement `setup(bus)` and `teardown()` lifecycle hooks
3. Register the module in `brain_agents_orchestrator.py`
4. Add a unit test under `test_<name>.py`
5. Update this catalog

## Total: 30 modules, 6 categories, fully covered by event bus.
