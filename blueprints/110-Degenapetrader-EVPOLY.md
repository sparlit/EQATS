# EVPoly Integration Blueprint for eqats

## Overview
EVPoly provides a Rust‑based trading engine for Polymarket with multiple strategy loops, a shared risk arbiter, persistent tracking, and remote alpha feeds. These components can be mapped onto the eqats domains as follows.

## Data Engines
- **Persistent tracking database** (`tracking.db`): a SQLite file that stores fills, orders, and state. eqats can adopt a similar SQLite‑backed journal for audit and replay.
- **Remote alpha ingestion**: Premarket, Endgame, EVcurve, and S‑Band strategies pull signals from `https://alpha.evplus.ai/` with fallback to `https://alpha2.evplus.ai/` and hard‑coded 1‑second timeouts. eqats can plug in a generic alpha client with retry logic and configurable endpoints.
- **Shared timeframe discovery**: Uses a remote discovery endpoint first, then a local fallback. eqats can implement a discovery service that queries a central metadata API and caches locally.
- **Wallet‑sync worker**: A background task that keeps the proxy wallet balance in sync with on‑chain data. eqats can add a balance‑monitoring actor that updates risk limits in real time.
- **Disk‑guard pruning**: Automatic removal of old tracking records to bound storage usage. eqats can enable a retention policy on its event store.

## Signal & Execution Logic
- **Strategy library**: Six pre‑built loops (`premarket_v1`, `endgame_sweep_v1`, `evcurve_v1`, `sessionband_v1`, `evsnipe_v1`, `mm_sport_v1`). eqats can import these as plug‑in modules or re‑implement their logic using its own strategy framework.
- **Manual execution API**: A standalone HTTP endpoint for ad‑hoc orders. eqats can expose a similar RPC/HTTP gateway for manual interventions.
- **Remote alpha auto‑onboarding**: When `EVPOLY_ALPHA_AUTO_ONBOARD=true` the bot registers an alpha key on first start. eqats can provide an onboarding script that registers API keys with external signal providers.
- **Strategy toggles & base sizes**: Each strategy can be turned on/off via env vars and has a configurable base size (USD). eqats should expose similar feature flags and position‑size parameters.
- **Live / dry‑run modes**: `./ev start live` vs `./ev start dry`. eqats can reuse its execution simulator for dry runs.
- **Process management**: The `./ev` wrapper handles tmux sessions, auto‑restart, logs, and status reporting. eqats can adopt a supervisory CLI that manages strategy processes and provides health checks.

## Risk Engineering
- **Shared risk arbiter**: A central component that enforces cross‑strategy limits (e.g., max exposure, max loss). eqats can integrate a global risk service that all strategies consult before sending orders.
- **Wallet‑sync & balance awareness**: The arbiter uses the synced wallet balance to cap total risk. eqats can feed real‑time balance data into its risk engine.
- **Builder fee awareness**: The engine knows Polymarket charges a 0.1% builder fee on both sides and factors it into EV calculations. eqats should incorporate exchange‑specific fees into its profit‑and‑loss models.
- **Configurable base sizes**: Defaults (e.g., 10 USD for premarket, 50 USD for endgame) act as per‑strategy risk caps. eqats can treat these as max‑order‑size parameters.
- **Disk‑guard & log rotation**: Prevents unbounded growth of the tracking store, indirectly protecting against resource exhaustion. eqats can apply similar retention limits to its databases and logs.

## Integration Steps
1. **Add a SQLite‑based event store** mirroring `tracking.db` for fills and strategy state.
2. **Implement an alpha client** with retry, fallback endpoints, and timeout configuration matching EVPoly’s 1‑second (or 2‑second for discovery) limits.
3. **Expose strategy modules** for the six EVPoly loops, allowing them to be toggled via environment variables and configured with base‑size and symbol lists.
4. **Build a manual execution endpoint** (HTTP/WS) that can submit orders directly through the exchange SDK.
5. **Create a risk arbiter service** that receives balance updates from a wallet‑sync worker and enforces global limits before any order is routed.
6. **Add a supervisory CLI** (similar to `./ev`) that manages tmux (or equivalent) sessions, provides start/stop/restart, logs, status, and autorestart functionality.
7. **Configure fee constants** (0.1% builder fee) in the exchange adapter so that expected value calculations are accurate.
8. **Set up disk‑guard pruning** on the event store to retain only the last N days or a maximum size.
9. **Write onboarding scripts** (Python + requests + eth‑account) to register API keys with remote signal providers, mirroring EVPoly’s `remote_onboard.py`.
10. **Validate environment coverage** with a script akin to `scripts/verify_env_coverage.sh` to ensure all required vars are present before launch.

By following this blueprint, eqats can incorporate EVPoly’s proven data pipelines, strategy execution patterns, and risk controls while preserving its own modular architecture.