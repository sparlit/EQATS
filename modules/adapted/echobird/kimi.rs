//! Kimi For Coding usage provider
//!
//! API: GET https://api.kimi.com/coding/v1/usages
//! Response: { limits: [{detail: {limit, remaining, resetTime}}], usage: {limit, remaining, resetTime} }

use super::{now_millis, parse_f64, ModelUsageData, UsageProvider, UsageQuota, UsageResult};
use reqwest;
use std::time::Duration;

pub struct KimiProvider;

/// Extract reset time from JSON value, convert to milliseconds
fn extract_reset_time(value: &serde_json::Value) -> Option<i64> {
    if let Some(s) = value.as_str() {
        // ISO 8601 string, parse to timestamp
        if let Ok(dt) = chrono::DateTime::parse_from_rfc3339(s) {
            return Some(dt.timestamp_millis());
        }
    }
    if let Some(n) = value.as_i64() {
        if n <= 0 {
            return None;
        }
        // Check if seconds or milliseconds
        let ms = if n < 1_000_000_000_000 { n * 1000 } else { n };
        return Some(ms);
    }
    None
}

#[async_trait::async_trait]
impl UsageProvider for KimiProvider {
    async fn query_usage(&self, api_key: &str, _base_url: &str) -> Result<UsageResult, String> {
        let client = reqwest::Client::new();

        let resp = client
            .get("https://api.kimi.com/coding/v1/usages")
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

        let mut quotas = Vec::new();

        // 5-hour window limit (priority display)
        if let Some(limits) = body.get("limits").and_then(|v| v.as_array()) {
            for limit_item in limits {
                if let Some(detail) = limit_item.get("detail") {
                    let limit = detail.get("limit").and_then(parse_f64).unwrap_or(1.0);
                    let remaining = detail.get("remaining").and_then(parse_f64).unwrap_or(0.0);
                    let reset_at = detail
                        .get("resetTime")
                        .and_then(extract_reset_time)
                        .unwrap_or_else(|| now_millis() + 5 * 60 * 60 * 1000);

                    let used = (limit - remaining).max(0.0);
                    let percentage = if limit > 0.0 {
                        (used / limit) * 100.0
                    } else {
                        0.0
                    };

                    quotas.push(UsageQuota {
                        percentage,
                        reset_at,
                        balance: None,
                        balance_unit: None,
                    });
                }
            }
        }

        // Weekly limit
        if let Some(usage) = body.get("usage") {
            let limit = usage.get("limit").and_then(parse_f64).unwrap_or(1.0);
            let remaining = usage.get("remaining").and_then(parse_f64).unwrap_or(0.0);
            let reset_at = usage
                .get("resetTime")
                .and_then(extract_reset_time)
                .unwrap_or_else(|| now_millis() + 7 * 24 * 60 * 60 * 1000);

            let used = (limit - remaining).max(0.0);
            let percentage = if limit > 0.0 {
                (used / limit) * 100.0
            } else {
                0.0
            };

            quotas.push(UsageQuota {
                percentage,
                reset_at,
                balance: None,
                balance_unit: None,
            });
        }

        if quotas.is_empty() {
            return Ok(UsageResult {
                success: false,
                data: None,
                error: Some("No usage data available".to_string()),
            });
        }

        Ok(UsageResult {
            success: true,
            data: Some(ModelUsageData {
                quotas,
                last_updated: Some(now_millis()),
            }),
            error: None,
        })
    }

    fn can_handle(&self, base_url: &str) -> bool {
        base_url.contains("api.kimi.com/coding")
    }

    fn name(&self) -> &'static str {
        "Kimi"
    }
}
