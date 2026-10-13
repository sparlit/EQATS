//! Codex and ChatGPT launch support.
//!
//! Model traffic no longer passes through EchoBird: model application writes
//! the provider's Responses endpoint directly to `~/.codex/config.toml`.

mod codex_binary;
mod config_manager;
mod onboarding_bypass;

pub use codex_binary::{resolve_codex_cli_binary, resolve_codex_cli_shim};
pub use config_manager::{default_codex_dir, migrate_legacy_proxy_config};
pub use onboarding_bypass::bypass_onboarding;