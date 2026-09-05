// Model configuration structures — mirrors old modelManager.ts types

use serde::{Deserialize, Serialize};

/// Model type indicator
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "UPPERCASE")]
pub enum ModelType {
    Cloud,
    Local,
    Tunnel,
    Demo,
}

#[derive(Debug, Clone, Copy, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub enum ModelScope {
    #[default]
    ModelCenter,
    SmartRouter,
}

impl ModelScope {
    fn is_model_center(&self) -> bool {
        *self == Self::ModelCenter
    }
}

/// Model configuration (stored in ~/.echobird/models.json)
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ModelConfig {
    pub internal_id: String,
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub model_id: Option<String>,
    pub base_url: String,
    #[serde(default)]
    pub api_key: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub anthropic_url: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    #[serde(rename = "type")]
    pub model_type: Option<ModelType>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub openai_tested: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub anthropic_tested: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub openai_latency: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub anthropic_latency: Option<f64>,
    #[serde(default, skip_serializing_if = "ModelScope::is_model_center")]
    pub scope: ModelScope,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn missing_scope_defaults_to_model_center() {
        let model: ModelConfig = serde_json::from_value(serde_json::json!({
            "internalId": "existing",
            "name": "Existing",
            "baseUrl": "https://example.com/v1",
            "apiKey": "key"
        }))
        .unwrap();

        assert_eq!(model.scope, ModelScope::ModelCenter);
    }

    #[test]
    fn smart_router_scope_is_serialized() {
        let value = serde_json::to_value(ModelConfig {
            internal_id: "router-model".to_string(),
            name: "Router Model".to_string(),
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
        })
        .unwrap();

        assert_eq!(value["scope"], "smartRouter");
    }
}

/// Model test result (returned to frontend)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TestResult {
    pub success: bool,
    pub latency: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub response: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    pub protocol: String,
}

/// Model ping result
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PingResult {
    pub success: bool,
    pub latency: f64,
    pub url: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}
