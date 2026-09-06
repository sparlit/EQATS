//! DeepSeek usage provider
//!
//! API: GET https://api.deepseek.com/user/balance
//! Response: { balance_infos: [{ currency, total_balance, granted_balance, topped_up_balance }], is_available }

use super::{now_millis, parse_f64, ModelUsageData, UsageProvider, UsageQuota, UsageResult};
use reqwest;
use std::time::Duration;

pub struct DeepSeekProvider;

#[async_trait::async_trait]
impl UsageProvider for DeepSeekProvider {
    async fn query_usage(&self, api_key: &str, _base_url: &str) -> Result<UsageResult, String> {
        let client = reqwest::Client::new();

        let resp = client
            .get("https://api.deepseek.com/user/balance")
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

        // DeepSeek returns balance, show as balance instead of percentage
        let total_balance = body
            .get("balance_infos")
            .and_then(|v| v.as_array())
            .and_then(|arr| arr.first())
            .and_then(|info| info.get("total_balance"))
            .and_then(parse_f64)
            .unwrap_or(0.0);

        let currency = body
            .get("balance_infos")
            .and_then(|v| v.as_array())
            .and_then(|arr| arr.first())
            .and_then(|info| info.get("currency"))
            .and_then(|v| v.as_str())
            .unwrap_or("CNY");

        // For balance display, percentage is not meaningful, set to 0
        // UI will detect balance field and show balance instead
        Ok(UsageResult {
            success: true,
            data: Some(ModelUsageData {
                quotas: vec![UsageQuota {
                    percentage: 0.0,
                    reset_at: now_millis() + 30 * 24 * 60 * 60 * 1000, // 30 days from now
                    balance: Some(total_balance),
                    balance_unit: Some(currency.to_string()),
                }],
                last_updated: Some(now_millis()),
            }),
            error: None,
        })
    }

    fn can_handle(&self, base_url: &str) -> bool {
        base_url.contains("api.deepseek.com")
    }

    fn name(&self) -> &'static str {
        "DeepSeek"
    }
}
