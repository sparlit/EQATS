mod runtime;
mod server;

use std::collections::HashSet;
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU16, Ordering};
use std::sync::{Mutex, OnceLock};

use rand::rngs::OsRng;
use rand::RngCore;
use serde::{Deserialize, Serialize};

use crate::models::model::{ModelConfig, ModelScope, ModelType};
use crate::services::model_manager;
use crate::utils::platform::echobird_dir;

pub const SMART_ROUTER_PORT: u16 = 53683;
pub const SMART_ROUTER_INTERNAL_ID: &str = "smart-router";
pub const SMART_ROUTER_MODEL_ID: &str = "auto";

static CONFIG_LOCK: OnceLock<Mutex<()>> = OnceLock::new();
static RUNNING: AtomicBool = AtomicBool::new(false);
static PORT: AtomicU16 = AtomicU16::new(SMART_ROUTER_PORT);
static SERVER: tokio::sync::Mutex<Option<runtime::ServerControl>> =
    tokio::sync::Mutex::const_new(None);

pub fn port() -> u16 {
    PORT.load(Ordering::Relaxed)
}

fn is_router_url(raw: &str) -> bool {
    is_loopback_url_on_port(raw, port()) || is_loopback_url_on_port(raw, SMART_ROUTER_PORT)
}

fn is_loopback_url_on_port(raw: &str, port: u16) -> bool {
    url::Url::parse(raw.trim()).ok().is_some_and(|url| {
        matches!(url.host_str(), Some("127.0.0.1" | "localhost" | "[::1]"))
            && url.port_or_known_default() == Some(port)
    })
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct StoredConfig {
    #[serde(default = "default_enabled")]
    enabled: bool,
    #[serde(default = "default_version")]
    version: u32,
    #[serde(default)]
    candidate_ids: Vec<String>,
    #[serde(default)]
    api_key: String,
}

impl Default for StoredConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            version: default_version(),
            candidate_ids: Vec::new(),
            api_key: String::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PublicConfig {
    pub enabled: bool,
    pub candidate_ids: Vec<String>,
    pub usable_candidate_count: usize,
    pub base_url: String,
    pub model_id: String,
    pub port: u16,
    pub running: bool,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PublicActivity {
    pub candidate_id: Option<String>,
    pub active: bool,
    pub sequence: u64,
    pub updated_at_ms: u64,
}

fn default_version() -> u32 {
    1
}

fn default_enabled() -> bool {
    true
}

fn config_path() -> PathBuf {
    echobird_dir().join("config").join("smart-router.json")
}

fn config_lock() -> &'static Mutex<()> {
    CONFIG_LOCK.get_or_init(|| Mutex::new(()))
}

fn generate_api_key() -> String {
    let mut bytes = [0_u8; 32];
    OsRng.fill_bytes(&mut bytes);
    format!("eb-local-{}", hex::encode(bytes))
}

fn save_config_unlocked(config: &StoredConfig) -> Result<(), String> {
    let path = config_path();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|e| format!("create smart router config directory failed: {e}"))?;
    }
    let content = serde_json::to_string_pretty(config)
        .map_err(|e| format!("serialize smart router config failed: {e}"))?;
    fs::write(&path, content).map_err(|e| format!("write {} failed: {e}", path.display()))
}

fn load_config_unlocked() -> Result<StoredConfig, String> {
    let path = config_path();
    let mut config = if path.exists() {
        let content = fs::read_to_string(&path)
            .map_err(|e| format!("read {} failed: {e}", path.display()))?;
        serde_json::from_str(&content)
            .map_err(|e| format!("parse {} failed: {e}", path.display()))?
    } else {
        StoredConfig::default()
    };

    if config.api_key.is_empty() {
        config.api_key = model_manager::encrypt_key_for_storage(&generate_api_key());
        save_config_unlocked(&config)?;
    } else if !config.api_key.starts_with("enc:v1:") {
        config.api_key = model_manager::encrypt_key_for_storage(&config.api_key);
        save_config_unlocked(&config)?;
    }

    Ok(config)
}

fn load_config() -> Result<StoredConfig, String> {
    let _guard = config_lock()
        .lock()
        .map_err(|_| "smart router config lock poisoned".to_string())?;
    load_config_unlocked()
}

fn public_config(config: StoredConfig) -> PublicConfig {
    let port = port();
    let usable_candidate_count = usable_candidate_count(&config.candidate_ids);
    PublicConfig {
        enabled: config.enabled,
        candidate_ids: config.candidate_ids,
        usable_candidate_count,
        base_url: format!("http://127.0.0.1:{port}/v1"),
        model_id: SMART_ROUTER_MODEL_ID.to_string(),
        port,
        running: RUNNING.load(Ordering::Relaxed),
    }
}

pub fn get_public_config() -> Result<PublicConfig, String> {
    load_config().map(public_config)
}

pub fn get_public_activity() -> PublicActivity {
    server::public_activity()
}

pub fn set_candidate_ids(candidate_ids: Vec<String>) -> Result<PublicConfig, String> {
    let valid_user_ids: HashSet<String> = model_manager::get_user_models()
        .into_iter()
        .map(|model| model.internal_id)
        .collect();
    let mut seen = HashSet::new();
    let candidate_ids: Vec<String> = candidate_ids
        .into_iter()
        .filter(|id| id != SMART_ROUTER_INTERNAL_ID)
        .filter(|id| valid_user_ids.contains(id) || id == "local-server")
        .filter(|id| seen.insert(id.clone()))
        .collect();
    if candidate_ids.len() > server::MAX_ROUTE_CANDIDATES {
        return Err(format!(
            "Smart Router supports up to {} candidate models",
            server::MAX_ROUTE_CANDIDATES
        ));
    }

    let _guard = config_lock()
        .lock()
        .map_err(|_| "smart router config lock poisoned".to_string())?;
    let mut config = load_config_unlocked()?;
    config.candidate_ids = candidate_ids;
    save_config_unlocked(&config)?;
    server::retain_candidate_memory(&config.candidate_ids);
    Ok(public_config(config))
}

pub fn get_candidate_models() -> Vec<ModelConfig> {
    let candidate_ids: HashSet<String> = candidate_ids().into_iter().collect();
    let mut models: Vec<ModelConfig> = model_manager::get_user_models()
        .into_iter()
        .filter(|model| candidate_ids.contains(&model.internal_id))
        .collect();
    if candidate_ids.contains("local-server") {
        let local_server = crate::services::local_llm::get_server_info_sync();
        if local_server_is_routable(&local_server) {
            models.push(ModelConfig {
                internal_id: "local-server".to_string(),
                name: local_server.model_name.clone(),
                model_id: Some(local_server.model_name),
                base_url: format!("http://127.0.0.1:{}/v1", local_server.port),
                api_key: local_server.api_key,
                anthropic_url: Some(format!("http://127.0.0.1:{}/anthropic", local_server.port)),
                model_type: Some(ModelType::Local),
                openai_tested: None,
                anthropic_tested: None,
                openai_latency: None,
                anthropic_latency: None,
                scope: ModelScope::ModelCenter,
            });
        }
    }
    models
}

fn model_is_routable(model: &ModelConfig) -> bool {
    model.internal_id != SMART_ROUTER_INTERNAL_ID
        && model
            .model_id
            .as_deref()
            .is_some_and(|model_id| !model_id.trim().is_empty())
        && !model.base_url.trim().is_empty()
        && !is_router_url(&model.base_url)
        && !model_manager::decrypt_key_for_use(&model.api_key)
            .trim()
            .is_empty()
}

fn local_server_is_routable(server: &crate::services::local_llm::LocalServerInfo) -> bool {
    server.running
        && server.port != 0
        && !server.model_name.trim().is_empty()
        && !server.api_key.is_empty()
}

fn router_owns_model(model: &ModelConfig) -> bool {
    model.scope == ModelScope::SmartRouter
}

fn usable_candidate_count(candidate_ids: &[String]) -> usize {
    let user_models = model_manager::get_user_models();
    let local_server = crate::services::local_llm::get_server_info_sync();
    candidate_ids
        .iter()
        .filter(|candidate_id| {
            (candidate_id.as_str() == "local-server" && local_server_is_routable(&local_server))
                || user_models.iter().any(|model| {
                    model.internal_id == candidate_id.as_str() && model_is_routable(model)
                })
        })
        .count()
}

pub fn remove_candidate(internal_id: &str) -> Result<PublicConfig, String> {
    let configured_ids = candidate_ids();
    let is_configured = configured_ids.iter().any(|id| id == internal_id);
    let stored_model = model_manager::get_user_models()
        .into_iter()
        .find(|model| model.internal_id == internal_id);
    let delete_owned_model = is_configured
        && internal_id != "local-server"
        && stored_model.as_ref().is_some_and(router_owns_model);

    let remaining = configured_ids
        .into_iter()
        .filter(|id| id != internal_id)
        .collect();
    let config = set_candidate_ids(remaining)?;
    if delete_owned_model && !model_manager::delete_model(internal_id) {
        return Err(format!("Smart Router candidate not found: {internal_id}"));
    }
    Ok(config)
}

pub(crate) fn forget_candidate_memory(internal_id: &str) {
    server::forget_candidate_memory(internal_id);
}

pub(crate) fn candidate_ids() -> Vec<String> {
    load_config()
        .map(|config| config.candidate_ids)
        .unwrap_or_else(|e| {
            log::error!("[SmartRouter] Failed to load candidates: {e}");
            Vec::new()
        })
}

pub(crate) fn api_key_for_use() -> Result<String, String> {
    let config = load_config()?;
    let api_key = model_manager::decrypt_key_for_use(&config.api_key);
    if api_key.is_empty() {
        Err("smart router API key could not be decrypted".to_string())
    } else {
        Ok(api_key)
    }
}

pub fn model_config() -> Option<ModelConfig> {
    let port = port();
    let config = load_config().ok()?;
    if usable_candidate_count(&config.candidate_ids) == 0 {
        return None;
    }

    Some(ModelConfig {
        internal_id: SMART_ROUTER_INTERNAL_ID.to_string(),
        name: "Auto Router".to_string(),
        model_id: Some(SMART_ROUTER_MODEL_ID.to_string()),
        base_url: format!("http://127.0.0.1:{port}/v1"),
        api_key: config.api_key,
        anthropic_url: Some(format!("http://127.0.0.1:{port}")),
        model_type: Some(ModelType::Local),
        openai_tested: None,
        anthropic_tested: None,
        openai_latency: None,
        anthropic_latency: None,
        scope: ModelScope::ModelCenter,
    })
}

pub fn spawn_proxy_task() {
    if let Err(error) = tauri::async_runtime::block_on(async {
        let mut server = SERVER.lock().await;
        PORT.store(
            super::local_proxy::saved_port("smart-router", SMART_ROUTER_PORT)?,
            Ordering::Relaxed,
        );
        if load_config()?.enabled {
            *server = Some(start_server()?);
        }
        Ok::<_, String>(())
    }) {
        log::error!("[SmartRouter] {error}");
    }
}

fn start_server() -> Result<runtime::ServerControl, String> {
    let listener = super::local_proxy::bind("smart-router", SMART_ROUTER_PORT)?;
    PORT.store(
        listener.local_addr().expect("bound listener").port(),
        Ordering::Relaxed,
    );
    server::start(listener)
}

fn save_enabled(enabled: bool) -> Result<(), String> {
    let _guard = config_lock()
        .lock()
        .map_err(|_| "smart router config lock poisoned".to_string())?;
    let mut config = load_config_unlocked()?;
    config.enabled = enabled;
    save_config_unlocked(&config)
}

pub async fn set_enabled(enabled: bool) -> Result<PublicConfig, String> {
    let mut server = SERVER.lock().await;
    if enabled {
        if !RUNNING.load(Ordering::Relaxed) {
            if let Some(previous) = server.take() {
                previous.stop().await;
            }
            let started = start_server()?;
            if let Err(error) = save_enabled(true) {
                started.stop().await;
                return Err(error);
            }
            *server = Some(started);
        } else {
            save_enabled(true)?;
        }
    } else {
        save_enabled(false)?;
        if let Some(previous) = server.take() {
            previous.stop().await;
        }
    }
    get_public_config()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn enabled_defaults_on_and_persists_without_changing_candidates() {
        let mut config: StoredConfig =
            serde_json::from_str(r#"{"candidateIds":["first","second"],"apiKey":"key"}"#).unwrap();
        assert!(config.enabled);
        config.enabled = false;
        let restored: StoredConfig =
            serde_json::from_str(&serde_json::to_string(&config).unwrap()).unwrap();
        assert!(!restored.enabled);
        assert_eq!(restored.candidate_ids, vec!["first", "second"]);
        assert_eq!(restored.api_key, "key");
    }

    #[test]
    fn loopback_detection_uses_the_actual_port() {
        for host in ["127.0.0.1", "localhost", "[::1]"] {
            assert!(is_loopback_url_on_port(
                &format!("http://{host}:41234/v1"),
                41234
            ));
        }
        assert!(!is_loopback_url_on_port("http://127.0.0.1:41235/v1", 41234));
        assert!(!is_loopback_url_on_port(
            "https://example.com:41234/v1",
            41234
        ));
        assert!(is_router_url(&format!("http://127.0.0.1:{}/v1", port())));
    }

    #[test]
    fn generated_api_key_is_prefixed_and_random_sized() {
        let key = generate_api_key();
        assert!(key.starts_with("eb-local-"));
        assert_eq!(key.len(), "eb-local-".len() + 64);
    }

    #[test]
    fn candidate_requires_model_url_and_key() {
        let mut model = ModelConfig {
            internal_id: "candidate".to_string(),
            name: "Candidate".to_string(),
            model_id: Some("model-id".to_string()),
            base_url: "https://example.com/v1".to_string(),
            api_key: "key".to_string(),
            anthropic_url: None,
            model_type: Some(ModelType::Cloud),
            openai_tested: None,
            anthropic_tested: None,
            openai_latency: None,
            anthropic_latency: None,
            scope: ModelScope::SmartRouter,
        };
        assert!(model_is_routable(&model));
        model.name.clear();
        assert!(model_is_routable(&model));

        model.model_id = Some(String::new());
        assert!(!model_is_routable(&model));
        model.model_id = Some("model-id".to_string());
        model.base_url.clear();
        model.anthropic_url = Some("https://example.com/anthropic".to_string());
        assert!(!model_is_routable(&model));
        model.base_url = "https://example.com/v1".to_string();
        model.api_key.clear();
        assert!(!model_is_routable(&model));
        model.api_key = "   ".to_string();
        assert!(!model_is_routable(&model));
    }

    #[test]
    fn router_owns_only_router_scoped_models() {
        let mut model = ModelConfig {
            internal_id: "candidate".to_string(),
            name: "Candidate".to_string(),
            model_id: Some("model-id".to_string()),
            base_url: "https://example.com/v1".to_string(),
            api_key: "key".to_string(),
            anthropic_url: None,
            model_type: Some(ModelType::Cloud),
            openai_tested: None,
            anthropic_tested: None,
            openai_latency: None,
            anthropic_latency: None,
            scope: ModelScope::ModelCenter,
        };

        assert!(!router_owns_model(&model));
        model.scope = ModelScope::SmartRouter;
        assert!(router_owns_model(&model));
    }

    #[test]
    fn stopped_local_server_is_not_usable() {
        let server = crate::services::local_llm::LocalServerInfo {
            running: false,
            port: 53682,
            model_name: "local-model".to_string(),
            pid: None,
            api_key: "local-key".to_string(),
            runtime: "llama-server".to_string(),
        };
        assert!(!local_server_is_routable(&server));

        let running = crate::services::local_llm::LocalServerInfo {
            running: true,
            ..server
        };
        assert!(local_server_is_routable(&running));
    }
}