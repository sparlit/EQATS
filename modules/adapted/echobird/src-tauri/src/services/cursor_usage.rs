//! Read-only plan and usage queries for the editor and Grok Bot.
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::time::Duration;

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Usage {
    pub plan: Option<String>,
    pub remaining_percent: Option<f64>,
    pub reset_at: Option<i64>,
}

fn number(value: &Value) -> Option<f64> {
    value
        .as_f64()
        .or_else(|| value.as_str()?.parse().ok())
        .filter(|n| n.is_finite() && *n >= 0.0)
}

fn label(value: &Value) -> Option<String> {
    value
        .as_str()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(String::from)
}

fn editor_usage(value: &Value, plan: &Value) -> Usage {
    let used = number(&value["planUsage"]["totalPercentUsed"]).or_else(|| {
        let limit = number(&value["planUsage"]["limit"])?;
        if limit == 0.0 {
            return None;
        }
        number(&value["planUsage"]["includedSpend"]).map(|n| n / limit * 100.0)
    });
    Usage {
        plan: label(&plan["planInfo"]["planName"]),
        remaining_percent: used.map(|n| (100.0 - n).clamp(0.0, 100.0)),
        reset_at: number(&value["billingCycleEnd"])
            .filter(|n| *n > 0.0)
            .map(|n| (n / 1000.0) as i64),
    }
}

fn bot_usage(value: &Value) -> Usage {
    // Enterprise pooled allowances are not an individual weekly percentage.
    let remaining = if value["usesPooledEnterpriseAllowance"] == true {
        None
    } else if value["includedLimitZero"] == true {
        Some(0.0)
    } else {
        number(&value["usagePercent"]).map(|n| (100.0 - n).clamp(0.0, 100.0))
    };
    Usage {
        plan: label(&value["grokPlanLabel"])
            .filter(|name| !name.eq_ignore_ascii_case("Grok Bot Plan"))
            .or_else(|| label(&value["cursorPlanName"])),
        remaining_percent: remaining,
        reset_at: value["nextResetTimestampUtc"]
            .as_str()
            .and_then(|s| chrono::DateTime::parse_from_rfc3339(s).ok())
            .map(|d| d.timestamp())
            .filter(|n| *n > 0),
    }
}

async fn query(
    client: &reqwest::Client,
    token: &str,
    team: Option<u64>,
    bot: bool,
    method: &str,
) -> Result<Value, String> {
    let mut request = client
        .post(format!(
            "https://api2.cursor.sh/aiserver.v1.DashboardService/{method}"
        ))
        .bearer_auth(token)
        .header("Connect-Protocol-Version", "1")
        .header("x-cursor-client-type", if bot { "grok-bot" } else { "ide" })
        .json(&json!({}));
    if let Some(team) = team {
        request = request.header("x-cursor-team-id", team.to_string());
    }
    let response = request.send().await.map_err(|_| "accountError.network")?;
    if matches!(response.status().as_u16(), 401 | 403) {
        return Err("accountError.auth".into());
    }
    if !response.status().is_success() {
        return Err("accountError.network".into());
    }
    response
        .json()
        .await
        .map_err(|_| "accountError.format".into())
}

pub async fn fetch(token: &str, team: Option<u64>, bot: bool) -> Result<Usage, String> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(10))
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|_| "accountError.network")?;
    if bot {
        return Ok(bot_usage(
            &query(&client, token, team, true, "GetSandUsageStatus").await?,
        ));
    }
    let (usage, plan) = tokio::try_join!(
        query(&client, token, team, false, "GetCurrentPeriodUsage"),
        query(&client, token, team, false, "GetPlanInfo")
    )?;
    Ok(editor_usage(&usage, &plan))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn editor_remaining_uses_reported_percentage_and_millisecond_reset() {
        let usage = editor_usage(
            &json!({"planUsage":{"totalPercentUsed":32.5},"billingCycleEnd":"1800000000000"}),
            &json!({"planInfo":{"planName":"Pro+"}}),
        );
        assert_eq!(usage.plan.as_deref(), Some("Pro+"));
        assert_eq!(usage.remaining_percent, Some(67.5));
        assert_eq!(usage.reset_at, Some(1800000000));
        assert_eq!(
            editor_usage(&json!({"planUsage":{"totalPercentUsed":0}}), &json!({}))
                .remaining_percent,
            Some(100.0)
        );
        assert_eq!(
            editor_usage(
                &json!({"planUsage":{"limit":2000,"includedSpend":500}}),
                &json!({})
            )
            .remaining_percent,
            Some(75.0)
        );
    }

    #[test]
    fn missing_or_invalid_usage_remains_unknown() {
        for value in [
            json!({}),
            json!({"planUsage":{}}),
            json!({"planUsage":{"totalPercentUsed":-1}}),
            json!({"planUsage":{"limit":0}}),
        ] {
            assert!(editor_usage(&value, &json!({})).remaining_percent.is_none());
        }
        assert!(bot_usage(&json!({})).remaining_percent.is_none());
        assert!(bot_usage(&json!({"usagePercent":-1}))
            .remaining_percent
            .is_none());
        assert!(
            bot_usage(&json!({"usesPooledEnterpriseAllowance":true,"usagePercent":23}))
                .remaining_percent
                .is_none()
        );
    }

    #[test]
    fn bot_uses_its_own_weekly_meter_and_grant_label() {
        let usage = bot_usage(
            &json!({"usagePercent":25,"grokPlanLabel":"SuperGrok","cursorPlanName":"Free","nextResetTimestampUtc":"2027-01-15T08:00:00Z"}),
        );
        assert_eq!(usage.plan.as_deref(), Some("SuperGrok"));
        assert_eq!(usage.remaining_percent, Some(75.0));
        assert_eq!(usage.reset_at, Some(1800000000));
        assert_eq!(
            bot_usage(&json!({"includedLimitZero":true})).remaining_percent,
            Some(0.0)
        );
        assert_eq!(
            bot_usage(&json!({"usagePercent":123})).remaining_percent,
            Some(0.0)
        );
    }

    #[test]
    fn bot_generic_heading_falls_back_to_actual_cursor_tier() {
        for plan in ["Free", "Pro", "Pro+", "Ultra", "Teams"] {
            let usage = bot_usage(&json!({
                "grokPlanLabel":"Grok Bot Plan", "cursorPlanName":plan,
                "includedLimitZero":true
            }));
            assert_eq!(usage.plan.as_deref(), Some(plan));
            assert_eq!(usage.remaining_percent, Some(0.0));
        }
        assert!(bot_usage(&json!({"grokPlanLabel":"Grok Bot Plan"}))
            .plan
            .is_none());
    }
}