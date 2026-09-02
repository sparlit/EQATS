# TODO TASKS FOR EQATS VERSION 8.3j

## Phase 1: Architecture Baseline & Zero-Mock Verification
- [x] Verify zero synthetic mock data across all institutional modules.
- [x] Enforce modular monolith core isolation for active order execution.
- [x] Maintain microservices decoupling for pre-trade ingestion and post-trade persistence.

## Phase 2: GIL Bypass & Multi-Agent Swarm Isolation
- [x] Validate `ProcessPoolExecutor` isolation for all 13 trading strategy AI agents.
- [x] Validate `ProcessPoolExecutor` isolation for all 4 trading method AI agents.
- [x] Verify native PyO3 Rust thread releases (`allow_threads`) during heavy numerical routines.

## Phase 3: Hardware Capacity Auto-Detection & Auto-Tuning
- [x] Implement hardware auto-detection for CPU physical/logical cores, RAM, Disk, and GPU/VRAM in `institutional_integrations/system_autotune.py`.
- [x] Implement dynamic performance tier mapping (`LOW`, `MEDIUM`, `HIGH`, `ULTRA`).
- [x] Integrate hardware capacity controls and dynamic tuning into GUI `VTL <GO>` screen.

## Phase 4: Self-Learning Trade Post-Mortem Feedback Loop
- [ ] Extend `TradeMemoryProtocol` in `institutional_integrations/trade_memory_protocol.py` with post-mortem trade outcome analysis (`PROFIT`, `LOSS`, `NO_TRADE`).
- [ ] Extract regime and indicator feature correlations for winning vs losing trades.
- [ ] Implement adaptive retraining method to update strategy confidence weights based on post-mortem trade history.

## Phase 5: GUI Vitals & Graphic Telemetry Enhancements
- [ ] Add real-time graphics and system resource utilization meters on `VTL <GO>` screen.
- [ ] Ensure exception safety (`.winfo_exists()`) during rapid screen transitions.

## Phase 6: Exhaustive System Testing & Verification
- [ ] Add `test_v8_3j_self_learning_and_vitals.py` to cover self-learning post-mortem loops and hardware auto-tuning.
- [ ] Run complete system test suite and verify 100% pass rate.
- [ ] Update version strings to `EQATS VERSION 8.3j` in `pyproject.toml`, `gui.py`, `main.py`, and `README.md`.
