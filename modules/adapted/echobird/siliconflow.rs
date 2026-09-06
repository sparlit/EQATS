//! SiliconFlow usage provider
//!
//! API: GET https://api.siliconflow.cn/v1/user/info (or .com for EN)
//! Response: { code, data: { balance, chargeBalance, totalBalance, status } }

use super::{now_millis, parse_f64, ModelUsageData, UsageProvider, UsageQuota, UsageResult};
use reqwest;
use std::time::Duration;

pub struct SiliconFlowProvider;

#[async_trait::async_trait]
impl UsageProvider for SiliconFlowProvider {
    async fn query_usage(&self, api_key: &str, base_url: &str) -> Result<UsageResult, String> {
        let client = reqwest::Client::new();

        // Detect CN or EN domain
        let is_cn = base_url.contains("siliconflow.cn");
        let domain = if is_cn {
            "api.siliconflow.cn"
        } else {
            "api.siliconflow.com"
        };
        let url = format!("https://{}/v1/user/info", domain);

        let resp = client
            .get(&url)
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

        let data = body.get("data").ok_or("Missing 'data' field")?;
        let total_balance = data.get("totalBalance").and_then(parse_f64).unwrap_or(0.0);

        // Assume 100 as total for percentage (arbitrary)
        let assumed_total = 100.0;
        let percentage = if assumed_total > 0.0 {
            ((assumed_total - total_balance) / assumed_total * 100.0).clamp(0.0, 100.0)
        } else {
            0.0
        };

        Ok(UsageResult {
            success: true,
            data: Some(ModelUsageData {
                quotas: vec![UsageQuota {
                    percentage,
                    reset_at: now_millis() + 30 * 24 * 60 * 60 * 1000,
                    balance: None,
                    balance_unit: None,
                }],
                last_updated: Some(now_millis()),
            }),
            error: None,
        })
    }

    fn can_handle(&self, base_url: &str) -> bool {
        base_url.contains("siliconflow.cn") || base_url.contains("siliconflow.com")
    }

    fn name(&self) -> &'static str {
        "SiliconFlow"
    }
}
