//! Cline CLI and Desktop share native providers and have separate selectors.
mod desktop;

use super::{ApplyResult, ModelInfo};
use serde_json::{json, Value};
use std::{
    fs,
    io::Write,
    path::{Path, PathBuf},
};

pub(crate) fn config_path() -> PathBuf {
    resolve_config_path(
        |key| std::env::var(key).ok(),
        dirs::home_dir().unwrap_or_default(),
    )
}

fn resolve_config_path(env: impl Fn(&str) -> Option<String>, home: PathBuf) -> PathBuf {
    let value = |key| {
        env(key)
            .map(|v| v.trim().to_owned())
            .filter(|v| !v.is_empty())
    };
    if let Some(path) = value("CLINE_PROVIDER_SETTINGS_PATH") {
        return PathBuf::from(path);
    }
    value("CLINE_DATA_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            value("CLINE_DIR")
                .map(PathBuf::from)
                .unwrap_or_else(|| home.join(".cline"))
                .join("data")
        })
        .join("settings/providers.json")
}

fn load(path: &Path) -> Result<Value, String> {
    let state: Value = match fs::read(path) {
        Ok(bytes) => serde_json::from_slice(&bytes).map_err(|_| "Invalid Cline provider JSON")?,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            json!({"version":1,"modes":{},"providers":{}})
        }
        Err(_) => return Err("Cannot read Cline provider settings".into()),
    };
    if state["version"] != 1
        || !state["providers"].is_object()
        || state.get("modes").is_some_and(|m| !m.is_object())
    {
        return Err("Unsupported Cline provider settings format".into());
    }
    Ok(state)
}

fn write(path: &Path, state: &Value) -> Result<(), String> {
    let parent = path.parent().ok_or("Invalid Cline settings path")?;
    fs::create_dir_all(parent).map_err(|_| "Cannot create Cline settings directory")?;
    let temp = path.with_extension(format!("{}.tmp", uuid::Uuid::new_v4()));
    let result = (|| {
        let mut options = fs::OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut file = options
            .open(&temp)
            .map_err(|_| "Cannot stage Cline provider settings")?;
        let bytes = serde_json::to_vec_pretty(state)
            .map_err(|_| "Cannot serialize Cline provider settings")?;
        file.write_all(&bytes)
            .and_then(|_| file.sync_all())
            .map_err(|_| "Cannot save Cline provider settings")?;
        drop(file);
        fs::rename(&temp, path).map_err(|_| "Cannot replace Cline provider settings".to_string())
    })();
    if result.is_err() {
        let _ = fs::remove_file(temp);
    }
    result
}

fn provider_settings(info: &ModelInfo) -> Result<Value, String> {
    let model = info
        .model
        .as_deref()
        .filter(|m| !m.trim().is_empty())
        .ok_or("Model ID is empty")?;
    // Custom provider IDs appear in Cline's catalog but are not registered with
    // the 3.0.66 runtime gateway. Use its native providers for actual requests.
    let (protocol, client, provider) = match info.protocol.as_deref().unwrap_or("openai") {
        "openai" => ("openai-chat", "openai-compatible", "openai-compatible"),
        "openai-responses" => ("openai-responses", "openai", "openai"),
        "anthropic" => ("anthropic", "anthropic", "anthropic"),
        _ => return Err("Unsupported Cline model protocol".into()),
    };
    let base = if protocol == "anthropic" {
        info.anthropic_url.as_deref().or(info.base_url.as_deref())
    } else {
        info.base_url.as_deref()
    };
    let base = base
        .filter(|s| !s.trim().is_empty())
        .ok_or("API URL is empty")?
        .trim_end_matches('/');
    let url = reqwest::Url::parse(base).map_err(|_| "Invalid Cline API URL")?;
    if !matches!(url.scheme(), "http" | "https") {
        return Err("Invalid Cline API URL scheme".into());
    }
    Ok(
        json!({"provider":provider,"model":model,"baseUrl":base,"apiKey":info.api_key.as_deref().unwrap_or(""),"protocol":protocol,"client":client}),
    )
}

fn update(state: &mut Value, settings: Value) {
    let provider = settings["provider"].as_str().unwrap().to_owned();
    // Cline's Zod datetime schema requires a UTC Z suffix (not +00:00).
    state["providers"][&provider] = json!({"settings":settings,"updatedAt":chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true),"tokenSource":"manual"});
    state["lastUsedProvider"] = json!(provider);
}

fn result(result: Result<(), String>) -> ApplyResult {
    ApplyResult {
        success: result.is_ok(),
        message: result.err().unwrap_or_else(|| {
            "Cline model configured. Existing sessions keep their own model.".into()
        }),
    }
}

pub(super) async fn apply(info: &ModelInfo, is_desktop: bool) -> ApplyResult {
    let settings = match provider_settings(info) {
        Ok(settings) => settings,
        Err(e) => return result(Err(e)),
    };
    let path = config_path();
    // Validate before closing a native client or changing either file.
    if let Err(e) = load(&path) {
        return result(Err(e));
    }
    let sync_desktop =
        is_desktop || crate::services::tool_manager::get_tool_exe_path("clinedesktop").is_some();
    if sync_desktop {
        if let Err(e) = desktop::read() {
            return result(Err(e));
        }
        crate::services::process_manager::stop_desktop_for_config("clinedesktop").await;
    }
    let mut storage = if sync_desktop {
        match desktop::Storage::open() {
            Ok(storage) => Some(storage),
            Err(e) => return result(Err(e)),
        }
    } else {
        None
    };
    result(apply_at(&path, settings, storage.as_mut()))
}

fn apply_at(
    path: &Path,
    settings: Value,
    storage: Option<&mut desktop::Storage>,
) -> Result<(), String> {
    let existed = path.exists();
    let previous = load(path)?;
    let mut next = previous.clone();
    update(&mut next, settings.clone());
    if let Some(storage) = storage {
        let previous_selection = storage.read()?;
        let selected = desktop::select(
            previous_selection.clone(),
            settings["provider"].as_str().unwrap(),
            settings["model"].as_str().unwrap(),
        )?;
        write(path, &next)?;
        if let Err(error) = storage.write(&selected) {
            let restored = if existed {
                write(path, &previous)
            } else {
                fs::remove_file(path).map_err(|e| e.to_string())
            };
            restored.map_err(|_| "Cline desktop selection failed and provider rollback failed")?;
            // A flush failure may happen after the key was changed in memory.
            storage.write(&previous_selection).map_err(|_| "Cline desktop selection failed; providers restored, but desktop storage could not be restored")?;
            return Err(error);
        }
        Ok(())
    } else {
        write(path, &next)
    }
}

pub(super) fn read(is_desktop: bool) -> Option<ModelInfo> {
    let state = load(&config_path()).ok()?;
    let (provider, selected_model) = if is_desktop {
        let selection = desktop::read().ok()?;
        let provider = selection["lastProvider"].as_str()?.to_owned();
        let model = selection["lastModelByProvider"][&provider]
            .as_str()?
            .to_owned();
        (provider, Some(model))
    } else {
        (state["lastUsedProvider"].as_str()?.to_owned(), None)
    };
    model_info(&state, &provider, selected_model.as_deref())
}

fn model_info(state: &Value, provider: &str, selected_model: Option<&str>) -> Option<ModelInfo> {
    let settings = &state["providers"][provider]["settings"];
    let model = selected_model.or_else(|| settings["model"].as_str())?;
    serde_json::from_value(json!({
        "model":model,"name":model,"baseUrl":settings.get("baseUrl"),"apiKey":settings.get("apiKey"),
        "protocol": if settings["protocol"] == "anthropic" || settings["client"] == "anthropic" || provider == "anthropic" { "anthropic" } else if settings["protocol"] == "openai-responses" { "openai-responses" } else { "openai" }
    })).ok()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn shared_selection_preserves_other_providers_and_native_preferences() {
        let original = json!({"version":1,"lastUsedProvider":"native","modes":{"voiceInput":{"providerId":"native","modelId":"voice"}},"providers":{"native":{"settings":{"apiKey":"preserved"}}},"repairs":{"bedrockProfile":true}});
        let mut state = original.clone();
        let mut selection =
            json!({"lastProvider":"native","lastModelByProvider":{"native":"old"},"other":"keep"});
        for (protocol, provider, native_protocol) in [
            ("openai", "openai-compatible", "openai-chat"),
            ("anthropic", "anthropic", "anthropic"),
            ("openai-responses", "openai", "openai-responses"),
        ] {
            let info: ModelInfo = serde_json::from_value(json!({"model":"vendor/test","baseUrl":"http://127.0.0.1:1234/v1/","apiKey":"fixture","protocol":protocol})).unwrap();
            update(&mut state, provider_settings(&info).unwrap());
            assert!(state["providers"][provider]["updatedAt"]
                .as_str()
                .unwrap()
                .ends_with('Z'));
            assert_eq!(
                state["providers"][provider]["settings"]["protocol"],
                native_protocol
            );
            selection = desktop::select(selection, provider, "vendor/test").unwrap();
            assert_eq!(state["lastUsedProvider"], provider);
            assert_eq!(selection["lastProvider"], provider);
            assert_eq!(
                state["providers"]["native"],
                original["providers"]["native"]
            );
            assert_eq!(state["modes"], original["modes"]);
            assert_eq!(state["repairs"], original["repairs"]);
            assert_eq!(selection["lastModelByProvider"]["native"], "old");
            assert_eq!(selection["other"], "keep");
            assert_eq!(
                model_info(&state, provider, Some("session-model"))
                    .unwrap()
                    .model
                    .as_deref(),
                Some("session-model")
            );
            assert_eq!(
                model_info(&state, provider, None)
                    .unwrap()
                    .protocol
                    .as_deref(),
                Some(protocol)
            );
        }
    }

    #[test]
    fn missing_and_invalid_configs_are_handled_without_destroying_data() {
        let root =
            std::env::temp_dir().join(format!("echobird-cline-test-{}", uuid::Uuid::new_v4()));
        let path = root.join("providers.json");
        let info: ModelInfo =
            serde_json::from_value(json!({"model":"test","baseUrl":"https://example.test/v1"}))
                .unwrap();
        let settings = provider_settings(&info).unwrap();
        apply_at(&path, settings.clone(), None).unwrap();
        assert_eq!(
            load(&path).unwrap()["providers"]["openai-compatible"]["settings"]["model"],
            "test"
        );
        for invalid in [
            "{broken",
            "null",
            r#"{"version":2,"providers":{},"modes":{}}"#,
            r#"{"version":1,"providers":[],"modes":{}}"#,
        ] {
            fs::write(&path, invalid).unwrap();
            assert!(apply_at(&path, settings.clone(), None).is_err());
            assert_eq!(fs::read_to_string(&path).unwrap(), invalid);
        }
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn native_config_overrides_follow_cline_precedence() {
        let mut values = std::collections::HashMap::new();
        let home = PathBuf::from("home");
        for (key, value, expected) in [
            (
                "CLINE_DATA_DIR",
                "  ",
                "home/.cline/data/settings/providers.json",
            ),
            ("CLINE_DIR", "root", "root/data/settings/providers.json"),
            ("CLINE_DATA_DIR", "data", "data/settings/providers.json"),
            (
                "CLINE_PROVIDER_SETTINGS_PATH",
                " custom.json ",
                "custom.json",
            ),
        ] {
            values.insert(key, value.to_owned());
            assert_eq!(
                resolve_config_path(|k| values.get(k).cloned(), home.clone()),
                PathBuf::from(expected)
            );
        }
    }
}