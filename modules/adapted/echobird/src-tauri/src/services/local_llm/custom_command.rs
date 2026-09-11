//! Global custom launch command for the local LLM page (llama-server).
//!
//! When a custom command is stored, `server::start` spawns the user's own
//! executable + args instead of the auto-computed launch — e.g. an AMD user
//! points at their own Vulkan-compiled llama-server build. It is GLOBAL (one
//! override for the engine, not per-model): a BYO engine is the same across
//! models, so the model is orthogonal. EchoBird forces the model / `--host` /
//! `--port` onto the command at launch (see `server::ensure_managed_llama_args`)
//! so the server always loads the model selected in the UI and listens where
//! our proxy connects — the user customizes the executable + flags, never the
//! model/host/port. A missing entry falls back to the auto path, so the default
//! experience is untouched; the dialog's "reset" clears it.

use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CustomCommand {
    /// Executable to spawn (the user's own build — e.g. a Vulkan llama-server).
    pub exe: String,
    /// Arguments, one element each (no shell parsing — paths with spaces are
    /// safe because each element is passed to the process verbatim).
    pub args: Vec<String>,
}

fn store_path() -> Option<PathBuf> {
    dirs::home_dir().map(|h| h.join(".echobird").join("llama-custom-command.json"))
}

/// The stored global custom command, if one is set.
pub fn get() -> Option<CustomCommand> {
    store_path()
        .and_then(|p| std::fs::read_to_string(p).ok())
        .and_then(|t| serde_json::from_str(&t).ok())
}

/// Store (or replace) the global custom command.
pub fn set(cmd: CustomCommand) -> Result<(), String> {
    let path = store_path().ok_or_else(|| "no home directory".to_string())?;
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    let text = serde_json::to_string_pretty(&cmd).map_err(|e| e.to_string())?;
    std::fs::write(&path, text).map_err(|e| e.to_string())
}

/// Clear the global custom command — reverts to the auto-computed launch.
pub fn clear() -> Result<(), String> {
    if let Some(path) = store_path() {
        if path.exists() {
            std::fs::remove_file(&path).map_err(|e| e.to_string())?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trips_exe_and_args_with_spaces() {
        // Args with spaces survive because each is a separate Vec element.
        let cmd = CustomCommand {
            exe: r"C:\Program Files\llama-vulkan\llama-server.exe".to_string(),
            args: vec![
                "-m".to_string(),
                r"C:\models\my model.gguf".to_string(),
                "--device".to_string(),
                "Vulkan0".to_string(),
            ],
        };
        let json = serde_json::to_string(&cmd).unwrap();
        let back: CustomCommand = serde_json::from_str(&json).unwrap();
        assert_eq!(back, cmd);
        assert_eq!(back.args[1], r"C:\models\my model.gguf");
    }
}