//! Kimi Coding usage windows.
use super::{
    api_url, fetch_usage, parse_f64, parse_reset_time, QuotaPeriod, UsageProvider, UsageQuota,
    UsageResult,
};
use serde_json::Value;

pub struct KimiProvider;

fn usage_url(base_url: &str) -> Option<String> {
    let url = api_url(base_url, &["api.kimi.com", "api.kimi.ai"])?;
    (url.path() == "/coding" || url.path().starts_with("/coding/"))
        .then(|| format!("https://{}/coding/v1/usages", url.host_str().unwrap()))
}

fn parse_window(detail: &Value, period: QuotaPeriod) -> Option<UsageQuota> {
    let limit = parse_f64(&detail["limit"]).filter(|value| value.is_finite() && *value > 0.0)?;
    let remaining = parse_f64(&detail["remaining"])?;
    UsageQuota::window(
        period,
        (1.0 - remaining / limit) * 100.0,
        parse_reset_time(&detail["resetTime"]),
    )
}

fn parse_quotas(body: &Value) -> Vec<UsageQuota> {
    let mut quotas = Vec::new();
    if let Some(limits) = body["limits"].as_array() {
        for item in limits {
            if let Some(quota) = parse_window(&item["detail"], QuotaPeriod::FiveHour) {
                quotas.push(quota);
                break;
            }
        }
    }
    if let Some(quota) = parse_window(&body["usage"], QuotaPeriod::Weekly) {
        quotas.push(quota);
    }
    quotas
}

#[async_trait::async_trait]
impl UsageProvider for KimiProvider {
    async fn query_usage(&self, api_key: &str, base_url: &str) -> Result<UsageResult, String> {
        let endpoint = usage_url(base_url).ok_or("Unsupported Kimi endpoint")?;
        Ok(
            match fetch_usage(&endpoint, &format!("Bearer {api_key}")).await {
                Ok(body) => UsageResult::from_quotas(parse_quotas(&body)),
                Err(error) => UsageResult::failure(error),
            },
        )
    }
    fn can_handle(&self, base_url: &str) -> bool {
        usage_url(base_url).is_some()
    }
    fn name(&self) -> &'static str {
        "Kimi"
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn parses_both_windows_and_never_invents_a_reset() {
        let quotas = parse_quotas(&json!({
            "limits":[{"detail":{"limit":"100","remaining":"45","resetTime":"2027-01-01T12:00:00Z"}}],
            "usage":{"limit":1000,"remaining":800}
        }));
        assert_eq!(quotas.len(), 2);
        assert!((quotas[0].percentage - 55.0).abs() < 0.001);
        assert_eq!(quotas[1].period, Some(QuotaPeriod::Weekly));
        assert_eq!(quotas[1].reset_at, 0);
        assert!(
            parse_quotas(&json!({"limits":[{"detail":{"limit":0}}],"usage":{"limit":100}}))
                .is_empty()
        );
    }
    #[test]
    fn detects_coding_hosts_without_matching_platform_or_spoofed_urls() {
        assert!(KimiProvider.can_handle("https://api.kimi.ai/coding/v1"));
        assert!(!KimiProvider.can_handle("https://api.kimi.com/coding-other"));
        assert!(!KimiProvider.can_handle("https://api.kimi.com.evil.test/coding"));
        assert!(!KimiProvider.can_handle("https://api.moonshot.cn/v1"));
    }
}