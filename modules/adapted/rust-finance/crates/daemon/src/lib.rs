#![forbid(unsafe_code)]
//! Rust finance daemon: market data, strategy, risk, execution.

pub mod bootstrap;
pub mod engine;
#[allow(unused_imports, dead_code)]
pub mod hybrid_pipeline;
pub mod processor;
pub mod strategy;