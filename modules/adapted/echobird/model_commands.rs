// Tauri Commands for model operations �?exposed to frontend via invoke()

use crate::models::model::{ModelConfig, PingResult, TestResult};
use crate::services::model_manager::{self, AddModelInput, UpdateModelInput};
use crate::services::usage_providers::{self, UsageResult};

/// Get all models (user + built-in + local)
#[tauri::command]
pub fn get_models() -> Vec<ModelConfig> {
    model_manager::get_models()
}

/// Add a new model
#[tauri::command]
pub fn add_model(input: AddModelInput) -> ModelConfig {
    model_manager::add_model(input)
}

/// Delete a model by internal ID
#[tauri::command]
pub fn delete_model(internal_id: String) -> bool {
    let deleted = model_manager::delete_model(&internal_id);
    if deleted {
        if let Err(error) = crate::services::smart_router::remove_candidate(&internal_id) {
            log::warn!("Failed to remove deleted model from Smart Router: {error}");
            crate::services::smart_router::forget_candidate_memory(&internal_id);
        }
    }
    deleted
}

/// Update a model
#[tauri::command]
pub fn update_model(internal_id: String, updates: UpdateModelInput) -> Option<ModelConfig> {
    let resets_route_memory = updates.base_url.is_some()
        || updates.anthropic_url.is_some()
        || updates.api_key.is_some()
        || updates.model_id.is_some();
    let updated = model_manager::update_model(&internal_id, updates);
    if resets_route_memory && updated.is_some() {
        crate::services::smart_router::forget_candidate_memory(&internal_id);
    }
    updated
}

/// Persist a user-defined model display order (full visible list of
/// internal_ids in the new order).
#[tauri::command]
pub fn reorder_models(ordered_ids: Vec<String>) -> bool {
    model_manager::reorder_models(ordered_ids)
}

/// Test model with API request
#[tauri::command]
pub async fn test_model(
    internal_id: String,
    prompt: String,
    protocol: String,
) -> Result<TestResult, String> {
    Ok(model_manager::test_model(&internal_id, &prompt, &protocol).await)
}

/// Ping model server
#[tauri::command]
pub async fn ping_model(internal_id: String) -> Result<PingResult, String> {
    Ok(model_manager::ping_model(&internal_id).await)
}

/// Check if encrypted key is destroyed
#[tauri::command]
pub fn is_key_destroyed(internal_id: String) -> bool {
    model_manager::is_key_destroyed(&internal_id)
}

/// Query model usage (quota/balance)
#[tauri::command]
pub async fn query_model_usage(internal_id: String) -> Result<UsageResult, String> {
    let models = model_manager::get_models();
    let model = models
        .iter()
        .find(|m| m.internal_id == internal_id)
        .ok_or_else(|| format!("Model not found: {}", internal_id))?;

    // Determine base_url and api_key
    let base_url = if !model.base_url.is_empty() {
        &model.base_url
    } else if let Some(ref url) = model.anthropic_url {
        url
    } else {
        return Err("Model has no base URL configured".to_string());
    };

    let api_key = model_manager::decrypt_key_for_use(&model.api_key);

    // Query usage from provider (internal_id lets the Volcengine provider look
    // up per-model AK/SK).
    usage_providers::query_model_usage(base_url, &api_key, &internal_id).await
}

/// Save Volcengine IAM Access Key / Secret Access Key (encrypted) for a specific
/// model's usage queries. One account per model.
#[tauri::command]
pub fn save_volc_aksk(
    internal_id: String,
    access_key: String,
    secret_key: String,
) -> Result<(), String> {
    if access_key.trim().is_empty() || secret_key.trim().is_empty() {
        return Err("Access Key and Secret Access Key must not be empty".to_string());
    }
    usage_providers::volcengine::write_creds(&internal_id, access_key.trim(), secret_key.trim())
}

/// Whether Volcengine AK/SK are stored for a specific model.
#[tauri::command]
pub fn has_volc_aksk(internal_id: String) -> bool {
    usage_providers::volcengine::has_creds(&internal_id)
}

/// Remove stored Volcengine AK/SK for a specific model.
#[tauri::command]
pub fn clear_volc_aksk(internal_id: String) -> bool {
    usage_providers::volcengine::clear_creds(&internal_id);
    true
}

/// Stored AK/SK pair (plaintext) returned to the frontend to pre-fill the modal.
#[derive(serde::Serialize)]
pub struct VolcAksk {
    pub access_key: String,
    pub secret_key: String,
}

/// Read stored AK/SK (plaintext) for a model, to pre-fill the config modal.
#[tauri::command]
pub fn get_volc_aksk(internal_id: String) -> Option<VolcAksk> {
    usage_providers::volcengine::read_creds(&internal_id).map(|(ak, sk)| VolcAksk {
        access_key: ak,
        secret_key: sk,
    })
}
