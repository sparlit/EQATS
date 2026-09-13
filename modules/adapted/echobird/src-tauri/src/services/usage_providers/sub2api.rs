//! Sub2Api usage provider
//!
//! Sub2Api is the backend used by many AI relay/proxy sites (e.g. cc-vibe.com).
//! GET {base}/v1/usage with Bearer api-key returns quota mode:
//! { planName, unit, subscription: { daily_limit_usd, ... }, usage: { total: {...} } }
//! or wallet mode:
//! { planName, unit, mode: "unrestricted", balance, remaining, usage: {...} }
//!
//! This is a fallback provider (can_handle always true) - it sits last in
//! detect_provider so official providers (DeepSeek/Kimi/...) match first.
//! Any unmatched base_url (relay/proxy) is tried against /v1/usage; if the
//! site runs sub2api it returns 200 and we render bars, otherwise (404, bad
//! key, non-JSON, wrong shape) we silently show "暂无用量数据".

use super::{now_millis, parse_f64, ModelUsageData, UsageProvider, UsageQuota, UsageResult};
use chrono::TimeZone;
use reqwest;
use std::time::Duration;

pub struct Sub2ApiProvider;

/// Build the /v1/usage endpoint from a base_url.
/// cc-vibe.com/v1 (OpenAI) or cc-vibe.com (Anthropic) both -> https://cc-vibe.com/v1/usage
fn build_usage_url(base_url: &str) -> String {
    if let Ok(u) = url::Url::parse(base_url) {
        if let Some(host) = u.host_str() {
            return format!("{}://{}/v1/usage", u.scheme(), host);
        }
    }
    let trimmed = base_url.trim_end_matches('/');
    if trimmed.ends_with("/v1") {
        format!("{}/usage", trimmed)
    } else {
        format!("{}/v1/usage", trimmed)
    }
}

/// Extract the first number from a plan name (e.g. "日卡 每日200刀" -> 200).
fn parse_plan_limit(plan_name: &str) -> f64 {
    let mut num = String::new();
    let mut started = false;
    for c in plan_name.chars() {
        if c.is_ascii_digit() || (c == '.' && started) {
            num.push(c);
            started = true;
        } else if started {
            break;
        }
    }
    num.parse().unwrap_or(0.0)
}

/// Parse an RFC-3339 timestamp (e.g. "2026-07-17T17:27:45+08:00") to unix ms.
fn parse_iso_ms(s: &str) -> Option<i64> {
    chrono::DateTime::parse_from_rfc3339(s)
        .ok()
        .map(|dt| dt.timestamp_millis())
}

/// Daily quota resets at next midnight in CC Vibe's timezone (CST, +08:00).
/// Computed from the current time rather than the response's `daily_usage`
/// date, which can be stale and yield a past reset (-> "0m" countdown).
fn daily_reset_ms() -> i64 {
    let cst = chrono::FixedOffset::east_opt(8 * 3600).unwrap();
    let now_cst = chrono::Utc::now().with_timezone(&cst);
    let tomorrow = now_cst.date_naive() + chrono::Duration::days(1);
    // FixedOffset has no DST, so from_local_datetime is always Single.
    cst.from_local_datetime(&tomorrow.and_hms_opt(0, 0, 0).unwrap())
        .unwrap()
        .timestamp_millis()
}

/// Build one quota bar per enforced limit found in the `subscription` object
/// (daily/weekly/monthly). sub2api populates only the limits a plan enforces,
/// so a 天卡 yields 1 bar (daily) and a 月卡 yields 3 (daily+weekly+monthly).
/// Returns None when there is no subscription or no usable limit, so the
/// caller can fall back to the plan-name heuristic.
fn parse_subscription_quotas(body: &serde_json::Value) -> Option<Vec<UsageQuota>> {
    let sub = body.get("subscription")?;
    let mut quotas: Vec<UsageQuota> = Vec::new();
    let week_ms = 7 * 24 * 60 * 60 * 1000;
    let month_ms = 30 * 24 * 60 * 60 * 1000;
    let pct = |usage: f64, limit: f64| (usage / limit * 100.0).clamp(0.0, 100.0);

    if let Some(limit) = sub.get("daily_limit_usd").and_then(parse_f64) {
        if limit > 0.0 {
            // `subscription.daily_usage_usd` is STALE: it holds the previous
            // day's spend and does NOT reset to 0 at the start of a new day
            // until new usage arrives. So a fresh day with 0 usage still reads
            // yesterday's value (e.g. 200.70 against a 200 limit) -> bogus
            // 100%. The authoritative current-day figure is
            // `usage.today.actual_cost`; fall back to `daily_usage_usd` only
            // when the upstream omits `usage.today` (older sub2api builds).
            let usage = body
                .get("usage")
                .and_then(|u| u.get("today"))
                .and_then(|t| t.get("actual_cost"))
                .and_then(parse_f64)
                .or_else(|| sub.get("daily_usage_usd").and_then(parse_f64))
                .unwrap_or(0.0);
            quotas.push(UsageQuota {
                percentage: pct(usage, limit),
                reset_at: daily_reset_ms(),
                balance: None,
                balance_unit: None,
            });
        }
    }

    if let Some(limit) = sub.get("weekly_limit_usd").and_then(parse_f64) {
        if limit > 0.0 {
            let usage = sub
                .get("weekly_usage_usd")
                .and_then(parse_f64)
                .unwrap_or(0.0);
            let reset = sub
                .get("weekly_window_start")
                .and_then(|v| v.as_str())
                .and_then(parse_iso_ms)
                .map(|ms| ms + week_ms)
                .unwrap_or_else(|| now_millis() + week_ms);
            quotas.push(UsageQuota {
                percentage: pct(usage, limit),
                reset_at: reset,
                balance: None,
                balance_unit: None,
            });
        }
    }

    if let Some(limit) = sub.get("monthly_limit_usd").and_then(parse_f64) {
        if limit > 0.0 {
            let usage = sub
                .get("monthly_usage_usd")
                .and_then(parse_f64)
                .unwrap_or(0.0);
            // expires_at = subscription end = monthly quota reset (CC Vibe plans
            // are monthly; the API exposes no separate monthly-reset field).
            let reset = sub
                .get("expires_at")
                .and_then(|v| v.as_str())
                .and_then(parse_iso_ms)
                .unwrap_or_else(|| now_millis() + month_ms);
            quotas.push(UsageQuota {
                percentage: pct(usage, limit),
                reset_at: reset,
                balance: None,
                balance_unit: None,
            });
        }
    }

    if quotas.is_empty() {
        None
    } else {
        Some(quotas)
    }
}

fn parse_balance_quota(body: &serde_json::Value) -> Option<UsageQuota> {
    let balance = body
        .get("remaining")
        .and_then(parse_f64)
        .or_else(|| body.get("balance").and_then(parse_f64))?;
    let unit = body
        .get("unit")
        .or_else(|| body.get("currency"))
        .and_then(|v| v.as_str())
        .filter(|s| !s.trim().is_empty())
        .unwrap_or("USD");

    Some(UsageQuota {
        percentage: 0.0,
        reset_at: now_millis() + 30 * 24 * 60 * 60 * 1000,
        balance: Some(balance),
        balance_unit: Some(unit.to_string()),
    })
}

/// Empty result: no usage data. Sub2Api is the catch-all fallback provider, so
/// every failure mode (unreachable host, non-2xx, non-JSON, or a 200 that isn't
/// sub2api-shaped) collapses to this - the UI shows "暂无用量数据" instead of a
/// provider-specific error toast.
fn no_data() -> UsageResult {
    UsageResult {
        success: false,
        data: None,
        error: None,
    }
}

#[async_trait::async_trait]
impl UsageProvider for Sub2ApiProvider {
    async fn query_usage(&self, api_key: &str, base_url: &str) -> Result<UsageResult, String> {
        let usage_url = build_usage_url(base_url);
        let client = reqwest::Client::new();
        let resp = match client
            .get(&usage_url)
            .header("Authorization", format!("Bearer {}", api_key))
            .header("Accept", "application/json")
            .timeout(Duration::from_secs(15))
            .send()
            .await
        {
            Ok(r) => r,
            // Can't reach the endpoint (DNS / network / timeout) -> no data.
            Err(_) => return Ok(no_data()),
        };

        // Any non-2xx (404 = not sub2api, 401/403, 5xx, ...) -> no data. As a
        // guess fallback we can't tell a bad key from a non-sub2api endpoint, so
        // we never surface a specific error; the UI shows "暂无用量数据".
        if !resp.status().is_success() {
            return Ok(no_data());
        }

        let body: serde_json::Value = match resp.json().await {
            Ok(b) => b,
            // 200 but not JSON / wrong shape -> no data.
            Err(_) => return Ok(no_data()),
        };

        // Prefer the structured `subscription` object: it carries explicit
        // per-window limits (daily/weekly/monthly), so we render one bar per
        // enforced limit (天卡=daily only, 月卡=daily+weekly+monthly).
        if let Some(quotas) = parse_subscription_quotas(&body) {
            return Ok(UsageResult {
                success: true,
                data: Some(ModelUsageData {
                    quotas,
                    last_updated: Some(now_millis()),
                }),
                error: None,
            });
        }

        // Wallet / API-call mode exposes a remaining balance instead of enforced
        // daily/weekly/monthly limits. Return a balance quota so the existing UI
        // takes the same display path as DeepSeek, without changing quota bars.
        if let Some(quota) = parse_balance_quota(&body) {
            return Ok(UsageResult {
                success: true,
                data: Some(ModelUsageData {
                    quotas: vec![quota],
                    last_updated: Some(now_millis()),
                }),
                error: None,
            });
        }

        // Legacy fallback (sub2api without `subscription`): single bar from
        // total cost vs the limit parsed out of the plan name. Only emit a bar
        // when we actually parsed a limit; otherwise the 200 isn't real sub2api
        // data -> no data (avoids a bogus 0% bar on non-sub2api endpoints).
        let plan_name = body
            .get("planName")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let plan_limit = parse_plan_limit(&plan_name);
        if plan_limit <= 0.0 {
            return Ok(no_data());
        }
        let actual_cost = body
            .get("usage")
            .and_then(|u| u.get("total"))
            .and_then(|u| u.get("actual_cost"))
            .and_then(parse_f64)
            .unwrap_or(0.0);
        let percentage = (actual_cost / plan_limit * 100.0).clamp(0.0, 100.0);
        // Reset window from plan name (日/周/月). sub2api returns no reset time.
        let reset_at = if plan_name.contains('月') {
            now_millis() + 30 * 24 * 60 * 60 * 1000
        } else if plan_name.contains('周') {
            now_millis() + 7 * 24 * 60 * 60 * 1000
        } else {
            now_millis() + 24 * 60 * 60 * 1000
        };

        Ok(UsageResult {
            success: true,
            data: Some(ModelUsageData {
                quotas: vec![UsageQuota {
                    percentage,
                    reset_at,
                    balance: None,
                    balance_unit: None,
                }],
                last_updated: Some(now_millis()),
            }),
            error: None,
        })
    }

    fn can_handle(&self, _base_url: &str) -> bool {
        // Fallback: try any base_url not matched by official providers above.
        true
    }

    fn name(&self) -> &'static str {
        "Sub2Api"
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn monthly_card_yields_three_bars() {
        let body = json!({
            "planName": "月卡 每日200刀",
            "unit": "USD",
            "subscription": {
                "daily_limit_usd": 200, "daily_usage_usd": 96.12,
                "weekly_limit_usd": 1400, "weekly_usage_usd": 96.12,
                "monthly_limit_usd": 6000, "monthly_usage_usd": 96.12,
                "weekly_window_start": "2026-07-14T00:00:00+08:00",
                "expires_at": "2026-07-17T17:27:45+08:00"
            },
            "daily_usage": [{ "date": "2026-07-14" }],
            "usage": { "total": { "actual_cost": 96.12 } }
        });
        let quotas = parse_subscription_quotas(&body).expect("subscription present");
        assert_eq!(quotas.len(), 3);
        assert!((quotas[0].percentage - 48.06).abs() < 0.1);
        assert!((quotas[1].percentage - 6.87).abs() < 0.1);
        assert!((quotas[2].percentage - 1.60).abs() < 0.1);
    }

    #[test]
    fn day_card_yields_one_bar_when_only_daily_limit() {
        let body = json!({
            "planName": "天卡 每日200刀",
            "subscription": {
                "daily_limit_usd": 200, "daily_usage_usd": 50.0
            },
            "daily_usage": [{ "date": "2026-07-14" }]
        });
        let quotas = parse_subscription_quotas(&body).expect("subscription present");
        assert_eq!(quotas.len(), 1);
        assert!((quotas[0].percentage - 25.0).abs() < 0.01);
    }

    #[test]
    fn zero_or_absent_limits_are_skipped() {
        let body = json!({
            "subscription": {
                "daily_limit_usd": 200, "daily_usage_usd": 10.0,
                "weekly_limit_usd": 0, "monthly_limit_usd": 0
            },
            "daily_usage": [{ "date": "2026-07-14" }]
        });
        let quotas = parse_subscription_quotas(&body).expect("subscription present");
        assert_eq!(quotas.len(), 1);
    }

    #[test]
    fn wallet_mode_yields_balance_display() {
        let body = json!({
            "balance": 5384.70840195,
            "remaining": 5384.70840195,
            "isValid": true,
            "mode": "unrestricted",
            "planName": "Wallet balance",
            "unit": "USD",
            "usage": {
                "today": { "actual_cost": 203.944362 },
                "total": { "actual_cost": 286.406855 }
            }
        });
        let quota = parse_balance_quota(&body).expect("balance present");
        assert_eq!(quota.balance_unit.as_deref(), Some("USD"));
        assert!((quota.balance.unwrap_or_default() - 5384.70840195).abs() < 0.000001);
    }

    #[test]
    fn wallet_mode_can_use_balance_when_remaining_absent() {
        let body = json!({
            "balance": "12.50",
            "planName": "Wallet balance",
            "unit": "CNY"
        });
        let quota = parse_balance_quota(&body).expect("balance present");
        assert_eq!(quota.balance_unit.as_deref(), Some("CNY"));
        assert!((quota.balance.unwrap_or_default() - 12.5).abs() < 0.000001);
    }

    #[test]
    fn no_subscription_falls_back_to_none() {
        let body = json!({
            "planName": "X",
            "usage": { "total": { "actual_cost": 10.0 } }
        });
        assert!(parse_subscription_quotas(&body).is_none());
    }

    #[test]
    fn fresh_day_with_zero_today_is_0_pct_not_100() {
        // Real cc-vibe.com shape on a new day with no usage yet: the upstream
        // leaves `subscription.daily_usage_usd` holding YESTERDAY's spend
        // (200.708 against a 200 limit) while `usage.today.actual_cost` is the
        // authoritative 0. We must read today's figure, else the bar wrongly
        // shows 100%.
        let body = json!({
            "planName": "月卡 每日200刀",
            "subscription": {
                "daily_limit_usd": 200, "daily_usage_usd": 200.7082975,
                "weekly_limit_usd": 1400, "weekly_usage_usd": 296.8321385,
                "monthly_limit_usd": 6000, "monthly_usage_usd": 296.8321385,
                "weekly_window_start": "2026-07-14T00:00:00+08:00",
                "expires_at": "2026-07-17T17:27:45+08:00"
            },
            "daily_usage": [
                { "date": "2026-07-14", "actual_cost": 96.123841 },
                { "date": "2026-07-15", "actual_cost": 200.7082975 }
            ],
            "usage": {
                "today": { "actual_cost": 0 },
                "total": { "actual_cost": 296.8321385 }
            }
        });
        let quotas = parse_subscription_quotas(&body).expect("subscription present");
        assert_eq!(quotas.len(), 3);
        // Daily bar must reflect today's 0 usage, not the stale 200.708.
        assert!(
            (quotas[0].percentage - 0.0).abs() < 0.01,
            "daily should be 0%, got {}",
            quotas[0].percentage
        );
        // Weekly/monthly are cumulative-over-window and keep including past days.
        assert!((quotas[1].percentage - 21.20).abs() < 0.1);
        assert!((quotas[2].percentage - 4.95).abs() < 0.1);
    }

    #[test]
    fn daily_falls_back_to_daily_usage_usd_when_today_absent() {
        // Older sub2api builds expose no `usage.today`; keep using
        // `subscription.daily_usage_usd` so we don't regress those sites.
        let body = json!({
            "planName": "天卡 每日200刀",
            "subscription": {
                "daily_limit_usd": 200, "daily_usage_usd": 50.0
            },
            "daily_usage": [{ "date": "2026-07-14" }]
        });
        let quotas = parse_subscription_quotas(&body).expect("subscription present");
        assert_eq!(quotas.len(), 1);
        assert!((quotas[0].percentage - 25.0).abs() < 0.01);
    }
}