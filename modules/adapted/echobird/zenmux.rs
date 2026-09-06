//! ZenMux usage provider
//!
//! API: ZenMux usage query
//! Token plan provider similar to other coding plan services

use super::{now_millis, parse_f64, ModelUsageData, UsageProvider, UsageQuota, UsageResult};
use reqwest;
use std::time::Duration;

pub struct ZenMuxProvider;

/// Extract reset time from JSON value
fn extract_reset_time(value: &serde_json::Value) -> Option<i64> {
    if let Some(s) = value.as_str() {
        // ISO 8601 string
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
impl UsageProvider for ZenMuxProvider {
    async fn query_usage(&self, api_key: &str, base_url: &str) -> Result<UsageResult, String> {
        let client = reqwest::Client::new();

        // Construct usage API URL from base_url
        let usage_url = if base_url.ends_with('/') {
            format!("{}usage", base_url)
        } else {
            format!("{}/usage", base_url)
        };

        let resp = client
            .get(&usage_url)
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

        // Parse ZenMux response
        let data = body.get("data").ok_or("Missing 'data' field")?;
        let limits = data.get("limits").and_then(|v| v.as_array());

        let mut quotas = Vec::new();

        if let Some(arr) = limits {
            for limit_item in arr.iter() {
                let limit = limit_item.get("limit").and_then(parse_f64).unwrap_or(1.0);
                let used = limit_item.get("used").and_then(parse_f64).unwrap_or(0.0);
                let reset_at = limit_item
                    .get("resetTime")
                    .and_then(extract_reset_time)
                    .unwrap_or_else(|| now_millis() + 24 * 60 * 60 * 1000);

                let percentage = if limit > 0.0 {
                    (used / limit * 100.0).clamp(0.0, 100.0)
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
        base_url.contains("zenmux")
    }

    fn name(&self) -> &'static str {
        "ZenMux"
    }
}
