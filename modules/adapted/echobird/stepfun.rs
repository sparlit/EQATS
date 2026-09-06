//! StepFun usage provider
//!
//! API: GET https://api.stepfun.com/v1/accounts
//! Response: { object, type, balance, total_cash_balance, total_voucher_balance }

use super::{now_millis, parse_f64, ModelUsageData, UsageProvider, UsageQuota, UsageResult};
use reqwest;
use std::time::Duration;

pub struct StepFunProvider;

#[async_trait::async_trait]
impl UsageProvider for StepFunProvider {
    async fn query_usage(&self, api_key: &str, _base_url: &str) -> Result<UsageResult, String> {
        let client = reqwest::Client::new();

        let resp = client
            .get("https://api.stepfun.com/v1/accounts")
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

        let balance = body.get("balance").and_then(parse_f64).unwrap_or(0.0);

        // Assume 100 CNY total for percentage calculation
        let assumed_total = 100.0;
        let percentage = if assumed_total > 0.0 {
            ((assumed_total - balance) / assumed_total * 100.0).clamp(0.0, 100.0)
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
        base_url.contains("api.stepfun.ai") || base_url.contains("api.stepfun.com")
    }

    fn name(&self) -> &'static str {
        "StepFun"
    }
}
