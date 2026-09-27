//! Update existing client and relay URLs when a local listener changes port.

use super::{claudedesktop, mimodesktop};
use crate::services::{codex_runtime, local_proxy, tool_manager};
use std::collections::HashSet;

pub(crate) fn migrate_local_proxy_port(old: u16, new: u16) -> Result<(), String> {
    let mut paths = tool_manager::model_config_paths();
    if let Some(home) = dirs::home_dir() {
        // Split settings/providers and JSONC alternatives to configFile.
        for relative in [
            ".claude/settings.json",
            ".echobird/claudecode.json",
            ".echobird/claudedesktop.json",
            ".pi/agent/models.json",
            ".omp/agent/models.yml",
            ".omp/agent/models.yaml",
            ".dsh/.credentials.yaml",
            ".config/opencode/opencode.json",
            ".config/opencode/opencode.jsonc",
            ".config/mimocode/mimocode.json",
            ".config/mimocode/mimocode.jsonc",
            ".config/kilo/kilo.json",
            ".config/kilo/kilo.jsonc",
            ".config/openscience/openscience.json",
            ".config/openscience/openscience.jsonc",
        ] {
            paths.push(home.join(relative));
        }
    }
    if let Some(dir) = codex_runtime::default_codex_dir() {
        paths.push(dir.join("config.toml"));
    }
    if let Some(layout) = claudedesktop::resolve_claudedesktop_paths() {
        paths.push(
            layout
                .lib_dir
                .join(format!("{}.json", claudedesktop::CLAUDE_DESKTOP_PROFILE_ID)),
        );
    }
    if let Ok(dir) = mimodesktop::config_dir() {
        paths.extend(mimodesktop::CONFIG_NAMES.iter().map(|name| dir.join(name)));
    }
    let mut seen = HashSet::new();
    let mut errors = Vec::new();
    for path in paths {
        if seen.insert(path.clone()) {
            if let Err(error) = local_proxy::migrate_file(&path, old, new) {
                errors.push(error);
            }
        }
    }
    if errors.is_empty() {
        Ok(())
    } else {
        Err(errors.join("; "))
    }
}