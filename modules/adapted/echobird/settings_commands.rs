use crate::utils::platform::echobird_dir;
use serde::{Deserialize, Serialize};
use tauri::Manager;

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct AppSettings {
    #[serde(default)]
    pub locale: Option<String>,
    // The TS side sends/expects camelCase `themeMode` (light | dark | undefined).
    // Without the rename + default, serde would drop unknown fields on save and
    // the user's theme choice would silently reset on every restart.
    #[serde(default, rename = "themeMode")]
    pub theme_mode: Option<String>,
    #[serde(default, rename = "closeToTray")]
    pub close_to_tray: Option<bool>,
    #[serde(default, rename = "closeWindowBehaviorSet")]
    pub close_window_behavior_set: Option<bool>,
    // "我的AI生涯" profile display name. The avatar is a separate PNG file
    // (see set_avatar / get_avatar) rather than inline base64 to keep
    // settings.json small.
    #[serde(default, rename = "displayName")]
    pub display_name: Option<String>,
}

fn settings_path() -> std::path::PathBuf {
    echobird_dir().join("settings.json")
}

/// Read app settings from ~/.echobird/settings.json
#[tauri::command]
pub fn get_settings() -> AppSettings {
    let path = settings_path();
    if !path.exists() {
        return AppSettings::default();
    }
    match std::fs::read_to_string(&path) {
        Ok(content) => serde_json::from_str(&content).unwrap_or_default(),
        Err(e) => {
            log::warn!("[Settings] Failed to read settings: {}", e);
            AppSettings::default()
        }
    }
}

/// Write app settings to ~/.echobird/settings.json
#[tauri::command]
pub fn save_settings(settings: AppSettings, app: tauri::AppHandle) -> Result<(), String> {
    let dir = echobird_dir();
    if !dir.exists() {
        std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    }
    let json = serde_json::to_string_pretty(&settings).map_err(|e| e.to_string())?;
    std::fs::write(settings_path(), json).map_err(|e| e.to_string())?;

    // Update tray menu locale if locale changed
    if let Some(locale) = &settings.locale {
        let state = app.state::<crate::TrayState>();
        let mut current_locale = state.locale.lock().unwrap();
        if *current_locale != *locale {
            *current_locale = locale.clone();
            drop(current_locale); // Release lock before calling rebuild
            crate::rebuild_tray_menu(&app);
        }
    }

    Ok(())
}

fn my_projects_path() -> std::path::PathBuf {
    echobird_dir().join("projects.json")
}

/// Read the user-authored AI-project registry from ~/.echobird/projects.json.
/// Returns an empty array when the file is missing/unreadable. The front-end
/// (`myProjectsStore`) owns the `MyProject` shape — we persist the array
/// verbatim as JSON so the registry survives a webview-storage clear, can be
/// backed up / hand-edited like the rest of ~/.echobird, and can be written by
/// the "一键安装" agent. Replaces the old localStorage-only persistence.
#[tauri::command]
pub fn get_my_projects() -> serde_json::Value {
    let path = my_projects_path();
    if !path.exists() {
        return serde_json::json!([]);
    }
    match std::fs::read_to_string(&path) {
        Ok(content) => serde_json::from_str(&content).unwrap_or_else(|_| serde_json::json!([])),
        Err(e) => {
            log::warn!("[MyProjects] Failed to read projects: {}", e);
            serde_json::json!([])
        }
    }
}

/// Write the user-authored AI-project registry to ~/.echobird/projects.json
/// (pretty-printed). The front-end sends the full array on every CRUD op.
#[tauri::command]
pub fn save_my_projects(projects: serde_json::Value) -> Result<(), String> {
    let dir = echobird_dir();
    if !dir.exists() {
        std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    }
    let json = serde_json::to_string_pretty(&projects).map_err(|e| e.to_string())?;
    std::fs::write(my_projects_path(), json).map_err(|e| e.to_string())?;
    Ok(())
}

fn avatar_path() -> std::path::PathBuf {
    echobird_dir().join("avatar.png")
}

/// Set the "我的AI生涯" profile avatar from a user-picked image file. The
/// source is decoded, downscaled to fit 256×256 (aspect preserved), and
/// re-encoded as PNG at `~/.echobird/avatar.png` so a large photo can't bloat
/// the stored file or the IPC payload.
#[tauri::command]
pub fn set_avatar(source_path: String) -> Result<(), String> {
    let img = image::open(&source_path).map_err(|e| format!("read image: {e}"))?;
    let thumb = img.thumbnail(256, 256);
    let dir = echobird_dir();
    if !dir.exists() {
        std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    }
    thumb
        .save_with_format(avatar_path(), image::ImageFormat::Png)
        .map_err(|e| format!("save avatar: {e}"))?;
    Ok(())
}

/// Read the stored avatar as a base64 PNG data URI, or `None` if unset.
#[tauri::command]
pub fn get_avatar() -> Option<String> {
    use base64::Engine as _;
    let bytes = std::fs::read(avatar_path()).ok()?;
    let b64 = base64::engine::general_purpose::STANDARD.encode(bytes);
    Some(format!("data:image/png;base64,{b64}"))
}
