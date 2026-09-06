# Integration Blueprint: MO's Trading SIMD Engine into eqats

## Overview
Integrate the portable SIMD‑accelerated market data preprocessing from wangrunji0408/most into eqats as a Data Engine component.

## Components
- **Data Engine**: eqats/src/data_engines/most_simd.rs provides SIMD‑vectorized VWAP calculation.
- **Signal & Execution Logic**: No direct changes; the engine can be called by strategy modules.
- **Risk Engineering**: No direct changes; risk modules can consume the engine’s outputs.

## Interface
rust
pub fn vwap_simd(prices: &[f32], volumes: &[f32]) -> f32


## Build & Test
- Ensure Rust toolchain ≥1.68 (stable SIMD).
- cargo test runs the unit test.
- Feature flag most-simd can enable the module.

## Performance Expectations
- Processes 8 prices/volumes per SIMD lane, reducing latency ~4x on AVX512-capable CPUs.
- Falls back to scalar tail for non‑multiple‑of‑8 lengths.

## Future Work
- Extend to order‑book depth updates, level‑2 aggregation, and latency‑aware networking (UEFI inspiration).