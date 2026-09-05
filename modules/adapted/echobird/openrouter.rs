//! OpenRouter usage provider
//!
//! API: GET https://openrouter.ai/api/v1/credits
//! Response: { data: { total_credits, total_usage } }

use super::{now_millis, parse_f64, ModelUsageData, UsageProvider, UsageQuota, UsageResult};
use reqwest;
use std::time::Duration;

pub struct OpenRouterProvider;

#[async_trait::async_trait]
impl UsageProvider for OpenRouterProvider {
    async fn query_usage(&self, api_key: &str, _base_url: &str) -> Result<UsageResult, String> {
        let client = reqwest::Client::new();

        let resp = client
            .get("https://openrouter.ai/api/v1/credits")
            .header("Authorization", format!("Bearer {}", api_key))
            .header("Accept", "application/json")
            .timeout(Duration::from_secs(15))
            .send()
            .await
            .map_err(|e| format!("Network error: {}", e))?;

        let status = resp.status();
        if status == reqwest::StatusCode::UNAUTHORIZED || status == reqwest::StatusCode::FORBIDDEN {
            return Ok(UsageResult {
                success: false,
                data: None,
                error: Some(format!("Authentication failed (HTTP {})", status)),
            });
        }

        if !status.is_success() {
            let body = resp.text().await.unwrap_or_default();
            return Ok(UsageResult {
                success: false,
                data: None,
                error: Some(format!("API error (HTTP {}): {}", status, body)),
            });
        }

        let body: serde_json::Value = resp
            .json()
            .await
            .map_err(|e| format!("Failed to parse response: {}", e))?;

        let data = body.get("data").unwrap_or(&body);
        let total_credits = data.get("total_credits").and_then(parse_f64).unwrap_or(0.0);
        let total_usage = data.get("total_usage").and_then(parse_f64).unwrap_or(0.0);

        let percentage = if total_credits > 0.0 {
            (total_usage / total_credits * 100.0).clamp(0.0, 100.0)
        } else {
            100.0 // No credits = 100% used
        };

        Ok(UsageResult {
            success: true,
            data: Some(ModelUsageData {
                quotas: vec![UsageQuota {
                    percentage,
                    reset_at: now_millis() + 30 * 24 * 60 * 60 * 1000, // 30 days
                    balance: None,
                    balance_unit: None,
                }],
                last_updated: Some(now_millis()),
            }),
            error: None,
        })
    }

    fn can_handle(&self, base_url: &str) -> bool {
        base_url.contains("openrouter.ai")
    }

    fn name(&self) -> &'static str {
        "OpenRouter"
    }
}
