# Integration Blueprint for eqats from RupeezyTech/algo_ai_skill

## Overview
The algo_ai_skill repository provides a comprehensive framework for building production-quality Indian market algo strategies. Its modular structure and reference library can be leveraged to enhance eqats in three domains: Data Engines, Signal & Execution Logic, and Risk Engineering.

## Data Engines Integration
- **Market Calendar & Timings**: Incorporate the Indian market timings, expiry calendar, STT, circuit limits, and auction risk rules from `indian-market.md` into eqats' market data validator to reject orders outside allowed windows.
- **Alternative Data Feeds**: Use the FII/DII flows, OI analysis, PCR, max pain, delivery % signals from `india-data-edge.md` as additional feature columns in eqats' feature store.
- **Realistic Transaction Cost Modeling**: Adopt the cost model guidelines from `backtesting.md` (including slippage, impact cost, STT, GST, stamp duty) to improve eqats' backtesting engine.
- **Execution Algorithms**: Integrate TWAP, VWAP, iceberg, and impact cost tactics from `execution-alpha.md` into eqats' execution module for large-order handling.
- **Broker Connectivity**: Leverage the Vortex SDK reference (`brokers/rupeezy-vortex.md`) to add a new broker adapter for Rupeezy/Vortex, following the existing broker template pattern in eqats.

## Signal & Execution Logic Integration
- **Strategy Templates**: Use the scaffold script (`scaffold_strategy.py`) to generate eqats-compatible strategy skeletons with separation of concerns (main, strategy, execution, risk_manager, config).
- **Signal Libraries**: Import the strategy patterns (`strategy-patterns.md`) and options Greeks (`options-greeks.md`) into eqats' signal library to expand the pool of alpha factors.
- **Regime Detection**: Plug the HMM‑based regime detection from `regime-detection.md` into eqats' strategy selector to dynamically allocate capital based on trending/volatile/sideways regimes.
- **Validation & Linting**: Adopt the `validate_strategy.py` AST linter as a pre‑commit hook in eqats to enforce best‑practice checks (no hardcoded values, proper stop‑loss, margin checks).
- **Execution Module**: Align eqats' execution.py with the reference implementation: order state machine, fill tracking, graceful shutdown on SIGTERM, and IST timezone handling.

## Risk Engineering Integration
- **Risk Management Core**: Merge the position sizing, drawdown limits, and margin monitoring rules from `risk-management.md` into eqats' risk engine.
- **Psychological Guardrails**: Implement the daily loss breaker, consecutive loss pause, and killswitch from `psychological-guardrails.md` as circuit‑breaker mechanisms in eqats.
- **Tax‑Aware P&L**: Incorporate the STCG/LTCG logic and tax‑loss harvesting guidelines from `tax-optimization.md` into eqats' performance reporting.
- **Portfolio Construction**: Use the correlation‑aware sizing and multi‑strategy allocation framework from `portfolio-construction.md` to improve eqats' portfolio optimizer.
- **Robustness Testing**: Add walk‑forward, Monte Carlo, and sensitivity analysis procedures from `robustness-testing.md` to eqats' research pipeline.
- **Error Handling**: Adopt the order state machine and partial‑fill handling from `error-handling.md` to increase eqats' execution reliability.
- **Code Quality Standards**: Enforce the logging, testing, and type‑hint practices from `code-quality.md` across eqats' codebase.

## Implementation Steps
1. **Fork & Clone**: Add the algo_ai_skill as a submodule or copy the `plugins/indian-algo-trading/skills/indian-algo-trading` directory into eqats' `contrib/` folder.
2. **Data Layer**: Update eqats' market data validator and feature engineering pipelines with the market calendar and alternative data signals.
3. **Execution Layer**: Replace or extend eqats' order execution module with the Vortex SDK adapter and execution algorithm templates.
4. **Signal Layer**: Merge the strategy pattern and options Greeks documentation into eqats' signal library; expose new alpha functions.
5. **Risk Layer**: Integrate the risk‑management, guardrails, tax, and portfolio construction modules into eqats' risk service.
6. **Testing & CI**: Add the validate_strategy script and robustness testing procedures to eqats' CI pipeline.
7. **Documentation**: Cross‑reference the imported reference files in eqats' docs to maintain traceability.

## Expected Benefits
- Improved fidelity of backtests for Indian markets via realistic costs and market‑specific rules.
- Expanded alpha pool with momentum, mean‑reversion, options, and regime‑aware strategies.
- Safer live trading through broker‑specific safeguards, margin checks, and psychological circuit‑breakers.
- Enhanced portfolio performance via correlation‑aware allocation and tax‑optimized P&L.
- Reduced technical debt by adopting proven code‑quality and validation practices.