//! Usage query providers
//!
//! Each provider is implemented in its own module for easy maintenance and extension.

use serde::{Deserialize, Serialize};

pub mod deepseek;
pub mod kimi;
pub mod minimax;
pub mod novita;
pub mod openrouter;
pub mod siliconflow;
pub mod stepfun;
pub mod sub2api;
pub mod volcengine;
pub mod zenmux;
pub mod zhipu;

/// Single usage quota data (progress bar)
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct UsageQuota {
    pub percentage: f64, // 0-100
    pub reset_at: i64,   // Unix timestamp (ms)
    // Balance display (for providers like DeepSeek that show remaining balance)
    pub balance: Option<f64>,         // Remaining balance (e.g., 10.50 USD)
    pub balance_unit: Option<String>, // Currency unit (e.g., "USD", "CNY", "Credits")
}

/// Model usage data
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ModelUsageData {
    pub quotas: Vec<UsageQuota>,
    pub last_updated: Option<i64>, // Unix timestamp (ms)
}

/// Usage query result
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UsageResult {
    pub success: bool,
    pub data: Option<ModelUsageData>,
    pub error: Option<String>,
}

/// Provider trait - each provider implements this
#[async_trait::async_trait]
pub trait UsageProvider {
    /// Query usage from provider API
    async fn query_usage(&self, api_key: &str, base_url: &str) -> Result<UsageResult, String>;

    /// Check if this provider can handle the given base_url
    fn can_handle(&self, base_url: &str) -> bool;

    /// Provider name for logging
    fn name(&self) -> &'static str;
}

/// Provider enum - concrete type wrapper
pub enum Provider {
    DeepSeek(deepseek::DeepSeekProvider),
    Kimi(kimi::KimiProvider),
    MiniMax(minimax::MiniMaxProvider),
    Novita(novita::NovitaProvider),
    OpenRouter(openrouter::OpenRouterProvider),
    SiliconFlow(siliconflow::SiliconFlowProvider),
    StepFun(stepfun::StepFunProvider),
    ZenMux(zenmux::ZenMuxProvider),
    Zhipu(zhipu::ZhipuProvider),
    Sub2Api(sub2api::Sub2ApiProvider),
    Volcengine(volcengine::VolcengineProvider),
}

impl Provider {
    pub async fn query_usage(&self, api_key: &str, base_url: &str) -> Result<UsageResult, String> {
        match self {
            Provider::DeepSeek(p) => p.query_usage(api_key, base_url).await,
            Provider::Kimi(p) => p.query_usage(api_key, base_url).await,
            Provider::MiniMax(p) => p.query_usage(api_key, base_url).await,
            Provider::Novita(p) => p.query_usage(api_key, base_url).await,
            Provider::OpenRouter(p) => p.query_usage(api_key, base_url).await,
            Provider::SiliconFlow(p) => p.query_usage(api_key, base_url).await,
            Provider::StepFun(p) => p.query_usage(api_key, base_url).await,
            Provider::ZenMux(p) => p.query_usage(api_key, base_url).await,
            Provider::Zhipu(p) => p.query_usage(api_key, base_url).await,
            Provider::Sub2Api(p) => p.query_usage(api_key, base_url).await,
            Provider::Volcengine(p) => p.query_usage(api_key, base_url).await,
        }
    }
}

/// Detect provider from base_url and return appropriate implementation
pub fn detect_provider(base_url: &str) -> Option<Provider> {
    let url = base_url.to_lowercase();

    if deepseek::DeepSeekProvider.can_handle(&url) {
        return Some(Provider::DeepSeek(deepseek::DeepSeekProvider));
    }
    if kimi::KimiProvider.can_handle(&url) {
        return Some(Provider::Kimi(kimi::KimiProvider));
    }
    if minimax::MiniMaxProvider.can_handle(&url) {
        return Some(Provider::MiniMax(minimax::MiniMaxProvider));
    }
    if novita::NovitaProvider.can_handle(&url) {
        return Some(Provider::Novita(novita::NovitaProvider));
    }
    if openrouter::OpenRouterProvider.can_handle(&url) {
        return Some(Provider::OpenRouter(openrouter::OpenRouterProvider));
    }
    if siliconflow::SiliconFlowProvider.can_handle(&url) {
        return Some(Provider::SiliconFlow(siliconflow::SiliconFlowProvider));
    }
    if stepfun::StepFunProvider.can_handle(&url) {
        return Some(Provider::StepFun(stepfun::StepFunProvider));
    }
    if zenmux::ZenMuxProvider.can_handle(&url) {
        return Some(Provider::ZenMux(zenmux::ZenMuxProvider));
    }
    if zhipu::ZhipuProvider.can_handle(&url) {
        return Some(Provider::Zhipu(zhipu::ZhipuProvider));
    }
    if volcengine::VolcengineProvider.can_handle(&url) {
        return Some(Provider::Volcengine(volcengine::VolcengineProvider));
    }
    if sub2api::Sub2ApiProvider.can_handle(&url) {
        return Some(Provider::Sub2Api(sub2api::Sub2ApiProvider));
    }

    None
}

/// Main entry point - query usage for a model
pub async fn query_model_usage(
    base_url: &str,
    api_key: &str,
    internal_id: &str,
) -> Result<UsageResult, String> {
    let provider = match detect_provider(base_url) {
        Some(p) => p,
        None => {
            return Ok(UsageResult {
                success: false,
                data: None,
                error: Some("Provider does not support usage query".to_string()),
            });
        }
    };

    // Volcengine usage uses per-model AK/SK (keyed by internal_id), not the
    // inference api_key - route it through the per-model entrypoint so the
    // empty-api-key check below doesn't block it.
    if let Provider::Volcengine(p) = &provider {
        return p.query_usage_for_model(internal_id, base_url).await;
    }

    if api_key.trim().is_empty() {
        return Ok(UsageResult {
            success: false,
            data: None,
            error: Some("API key is empty".to_string()),
        });
    }

    provider.query_usage(api_key, base_url).await
}

/// Helper function to get current timestamp in milliseconds
pub(crate) fn now_millis() -> i64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as i64
}

/// Helper function to parse f64 from JSON value (supports both number and string)
pub(crate) fn parse_f64(value: &serde_json::Value) -> Option<f64> {
    value
        .as_f64()
        .or_else(|| value.as_str().and_then(|s| s.parse().ok()))
}
