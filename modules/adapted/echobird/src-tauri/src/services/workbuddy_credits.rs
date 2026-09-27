use super::{authorized, client, response, success, text, Edition, Saved};
use chrono::{Local, TimeZone};
use serde_json::{json, Value};

pub(super) struct Quota {
    pub remaining: f64,
    pub total: f64,
    pub expires_at: Option<i64>,
    pub plan: Option<String>,
}

pub(super) fn timestamp(value: Option<&Value>) -> Option<i64> {
    let value = value?;
    if let Some(number) = number(value) {
        return Some(if number.abs() > 10_000_000_000.0 {
            (number / 1000.0) as i64
        } else {
            number as i64
        });
    }
    let raw = value.as_str()?;
    if let Ok(date) = chrono::DateTime::parse_from_rfc3339(raw) {
        return Some(date.timestamp());
    }
    chrono::NaiveDateTime::parse_from_str(raw, "%Y-%m-%d %H:%M:%S%.f")
        .ok()
        .or_else(|| {
            chrono::NaiveDate::parse_from_str(raw, "%Y-%m-%d")
                .ok()?
                .and_hms_opt(23, 59, 59)
        })
        .and_then(|date| Local.from_local_datetime(&date).single())
        .map(|date| date.timestamp())
}
fn number(v: &Value) -> Option<f64> {
    v.as_f64()
        .or_else(|| v.as_str()?.parse::<f64>().ok())
        .filter(|v| v.is_finite())
}
fn amount(v: &Value, suffix: &str) -> Option<f64> {
    let alias = match suffix {
        "Size" => "CycleTotalCapacity",
        "Remain" => "CycleRemainCapacity",
        _ => "CycleUsedCapacity",
    };
    for prefix in ["CycleCapacity", "Capacity", "SlicePeriodCapacity"] {
        for ending in [format!("{suffix}Precise"), suffix.to_string()] {
            if let Some(n) = v.get(format!("{prefix}{ending}")).and_then(number) {
                return Some(n.max(0.0));
            }
        }
        if prefix == "CycleCapacity" {
            if let Some(n) = v.get(alias).and_then(number) {
                return Some(n.max(0.0));
            }
        }
    }
    None
}
fn resources<'a>(body: &'a Value, kind: &str) -> Option<&'a Vec<Value>> {
    for prefix in [
        "/data",
        "/data/data",
        "/data/Response/Data",
        "/data/data/Response/Data",
    ] {
        for key in [kind.to_string(), kind.to_lowercase()] {
            if let Some(items) = body
                .pointer(&format!("{prefix}/{key}"))
                .and_then(Value::as_array)
            {
                return Some(items);
            }
        }
    }
    None
}
fn expiry(v: &Value, now: i64) -> Option<i64> {
    let deduction = [
        "DeductionEndTime",
        "deductionEndTime",
        "ExpiredTime",
        "expiredTime",
    ]
    .iter()
    .find_map(|k| timestamp(v.get(k)));
    let cycle = timestamp(v.get("CycleEndTime").or_else(|| v.get("cycleEndTime")));
    let result = match (deduction, cycle) {
        (Some(a), Some(b)) if a.saturating_sub(b) > 365 * 86400 => Some(b),
        (Some(a), _) => Some(a),
        (_, b) => b,
    };
    result.filter(|v| v.saturating_sub(now) <= 730 * 86400)
}
fn summarize(items: &[Value], now: i64) -> (f64, f64, Option<i64>) {
    let mut remaining = 0.0;
    let mut total = 0.0;
    let mut expires = None;
    for item in items {
        let end = expiry(item, now);
        if end.is_some_and(|v| v <= now) {
            continue;
        }
        let slice = item
            .get("SlicePeriodUsageDetails")
            .or_else(|| item.get("slicePeriodUsageDetails"))
            .and_then(Value::as_array)
            .and_then(|a| a.first());
        let get = |key| amount(item, key).or_else(|| slice.and_then(|s| amount(s, key)));
        let capacity = get("Size");
        let left = get("Remain");
        let used = get("Used");
        let capacity = capacity
            .or_else(|| left.zip(used).map(|(a, b)| a + b))
            .or(left)
            .or(used)
            .unwrap_or(0.0);
        let left = left.unwrap_or_else(|| (capacity - used.unwrap_or(0.0)).max(0.0));
        total += capacity;
        remaining += left;
        if left > 0.0 {
            if let Some(end) = end {
                expires = Some(expires.map_or(end, |v: i64| v.min(end)));
            }
        }
    }
    (remaining, total, expires)
}

fn summary_field<'a>(body: &'a Value, key: &str) -> Option<&'a Value> {
    [
        "/data",
        "/data/data",
        "/data/Response/Data",
        "/data/data/Response/Data",
    ]
    .iter()
    .find_map(|prefix| body.pointer(&format!("{prefix}/{key}")))
}

fn subscription_plan(items: &[Value], summary: Option<&Value>, now: i64) -> Option<String> {
    let subscription = summary
        .and_then(|v| summary_field(v, "SubscriptionPackageCode"))
        .and_then(Value::as_str)
        .filter(|v| !v.is_empty());
    let paid = summary
        .and_then(|v| summary_field(v, "IsPaidUser"))
        .and_then(Value::as_bool);
    let plan = items
        .iter()
        .filter_map(|item| {
            if expiry(item, now).is_some_and(|end| end <= now)
                || timestamp(
                    item.get("DeductionStartTime")
                        .or_else(|| item.get("deductionStartTime")),
                )
                .is_some_and(|start| start > now)
                || item
                    .get("Status")
                    .or_else(|| item.get("status"))
                    .and_then(Value::as_i64)
                    .is_some_and(|status| !matches!(status, 0 | 3))
            {
                return None;
            }
            let code = text(item, "PackageCode").or_else(|| text(item, "packageCode"));
            if subscription.is_some() && code != subscription {
                return None;
            }
            let name = text(item, "PackageName")
                .or_else(|| text(item, "packageName"))?
                .to_lowercase();
            // Credit top-ups and promotional gifts do not establish a subscription tier.
            if [
                "top-up", "top up", "addon", "add-on", "bonus", "赠", "加量", "补充", "活动",
                "运营",
            ]
            .iter()
            .any(|word| name.contains(word))
            {
                return None;
            }
            let words: Vec<_> = name.split(|c: char| !c.is_ascii_alphanumeric()).collect();
            let is_plan =
                name.contains("subscription") || words.contains(&"plan") || words.len() == 1;
            if (is_plan && words.contains(&"team")) || name.contains("团队版") {
                Some((2, "Team"))
            } else if (is_plan && words.contains(&"pro")) || name.contains("专业版") {
                Some((1, "Pro"))
            } else if paid != Some(true)
                && ((is_plan && words.contains(&"free"))
                    || name.contains("免费版")
                    || name.contains("个人体验版"))
            {
                Some((0, "Free"))
            } else {
                None
            }
        })
        .max_by_key(|(rank, _)| *rank)
        .map(|(_, name)| name.to_string());
    plan.or_else(|| (subscription.is_none() && paid == Some(false)).then(|| "Free".to_string()))
}

fn quota(items: &[Value], summary: Option<&Value>, now: i64) -> Quota {
    let (remaining, total, expires_at) = summarize(items, now);
    Quota {
        remaining,
        total,
        expires_at,
        plan: subscription_plan(items, summary, now),
    }
}
fn base(saved: &Saved) -> &'static str {
    if saved.summary.edition == Edition::Ai {
        return Edition::Ai.api();
    }
    match text(&saved.session["auth"], "domain") {
        Some("www.workbuddy.cn" | "workbuddy.cn") => "https://www.workbuddy.cn",
        _ => Edition::Cn.api(),
    }
}
async fn post(saved: &Saved, path: &str, body: Value) -> Result<Value, String> {
    let base = base(saved);
    let paths = if saved.summary.edition == Edition::Ai {
        vec![path.to_string(), format!("/v2{path}")]
    } else {
        vec![path.to_string()]
    };
    for (index, path) in paths.iter().enumerate() {
        let result = response(
            authorized(&client()?, saved, &format!("{base}{path}"))?
                .header("Origin", base)
                .header("Referer", format!("{base}/profile/plans-usage"))
                .json(&body),
        )
        .await;
        let value = match result {
            Err(e) if e.ends_with("HTTP 404") && index + 1 < paths.len() => continue,
            other => other?,
        };
        if matches!(value["code"].as_i64(), Some(401 | 10085)) {
            return Err("accountError.loginRequired".into());
        }
        if value["code"].as_i64() == Some(404) && index + 1 < paths.len() {
            continue;
        }
        if !success(&value) {
            return Err("accountError.quota".into());
        }
        return Ok(value);
    }
    Err("accountError.quota".into())
}

pub(super) async fn fetch(saved: &Saved) -> Result<Quota, String> {
    let now = Local::now();
    if saved.summary.edition == Edition::Cn {
        // Package codes and request shapes follow workbuddy-switch's official billing adapter.
        let summary_request = post(saved, "/billing/meter/get-user-resource-summary", json!({}));
        let paid_request = post(
            saved,
            "/billing/meter/get-user-resource-paid-packages",
            json!({"PageNumber":1,"PageSize":200,"Status":[0,3],"NeedRenewInfo":true,"PackageCodes":["TCACA_code_002_AkiJS3ZHF5","TCACA_code_023_4xbGhMrE6q","TCACA_code_026_BaESVICNoi","TCACA_code_027_0FCGVA6vSa","TCACA_code_009_0XmEQc2xOf","TCACA_code_038_OhvqZtiPKr","TCACA_code_003_FAnt7lcmRT","TCACA_code_036_lupO5WgNdG"]}),
        );
        let free_request = post(
            saved,
            "/billing/meter/get-user-resource-free-packages",
            json!({"PageNumber":1,"PageSize":200,"Status":[0,3],"SlicePeriodStartTime":now.format("%Y-%m-%d 00:00:00").to_string(),"SlicePeriodEndTime":now.format("%Y-%m-%d 23:59:59").to_string(),"PackageCodes":["TCACA_code_008_cfWoLwvjU4","TCACA_code_007_nzdH5h4Nl0","TCACA_code_028_NtpWi0jzXs","TCACA_code_029_6wCGEWquYy","TCACA_code_030_BjSt89qTvr","TCACA_code_001_PqouKr6QWV","TCACA_code_006_DbXS0lrypC","TCACA_code_035_ArVxJcGDsm","TCACA_code_037_WxOD3MpI2o","TCACA_code_039_KRcQj7wUat","TCACA_code_040_mi9rCYg46x"]}),
        );
        let (summary, paid, free) = tokio::join!(summary_request, paid_request, free_request);
        for result in [&summary, &paid, &free] {
            if let Err(e) = result {
                if e.starts_with("accountError.loginRequired") {
                    return Err(e.clone());
                }
            }
        }
        // Require complete detail responses so a partial network failure cannot show a false balance.
        if let (Ok(summary), Ok(paid), Ok(free)) = (summary, paid, free) {
            if let (Some(packages), Some(paid), Some(free)) = (
                resources(&summary, "Packages"),
                resources(&paid, "Accounts"),
                resources(&free, "Accounts"),
            ) {
                let mut items = paid.clone();
                items.extend(free.clone());
                for package in packages {
                    let code = package
                        .get("PackageCode")
                        .or_else(|| package.get("packageCode"));
                    if !items.iter().any(|v| {
                        code.is_some()
                            && v.get("PackageCode").or_else(|| v.get("packageCode")) == code
                    }) {
                        items.push(package.clone());
                    }
                }
                return Ok(quota(&items, Some(&summary), now.timestamp()));
            }
        }
    }
    let path = if saved.summary.edition == Edition::Ai {
        "/billing/meter/get-user-resource"
    } else {
        "/v2/billing/meter/get-user-resource"
    };
    let body = post(saved,path,json!({"PageNumber":1,"PageSize":100,"ProductCode":"p_tcaca","Status":[0,3],"PackageEndTimeRangeBegin":now.format("%Y-%m-%d %H:%M:%S").to_string(),"PackageEndTimeRangeEnd":(now+chrono::Duration::days(365*101)).format("%Y-%m-%d %H:%M:%S").to_string()})).await?;
    Ok(quota(
        resources(&body, "Accounts").ok_or("accountError.quota")?,
        None,
        now.timestamp(),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn cycle_aliases_take_priority_over_lifetime_capacity() {
        let result = summarize(
            &[
                json!({"CycleTotalCapacity":100,"CycleRemainCapacity":25,"CycleUsedCapacity":75,
                "CapacitySize":1200,"CapacityRemain":900,"CapacityUsed":300}),
            ],
            1700000000,
        );
        assert_eq!(result, (25.0, 100.0, None));
    }
    #[test]
    fn detects_subscription_tiers_from_domestic_and_international_packages() {
        for (name, expected) in [
            ("CodeBuddy个人体验版", "Free"),
            ("CodeBuddy个人专业版", "Pro"),
            ("CodeBuddy团队版", "Team"),
            ("Free Plan Subscription", "Free"),
            ("Pro Plan Subscription", "Pro"),
            ("Team Plan Subscription", "Team"),
        ] {
            let items = [
                json!({"PackageName":name,"CapacityRemain":0,"Status":0,"CycleEndTime":1700001000}),
            ];
            assert_eq!(
                subscription_plan(&items, None, 1700000000).as_deref(),
                Some(expected)
            );
        }
    }
    #[test]
    fn respects_current_subscription_and_does_not_infer_plan_from_credit_topups() {
        let items = [
            json!({"PackageCode":"free","PackageName":"Free Plan Subscription"}),
            json!({"PackageCode":"pro","PackageName":"Pro Plan Subscription"}),
            json!({"PackageCode":"topup","PackageName":"Team Plan Top-up"}),
        ];
        assert_eq!(
            subscription_plan(&items, None, 1700000000).as_deref(),
            Some("Pro")
        );
        let summary = json!({"data":{"Response":{"Data":{"SubscriptionPackageCode":"free","IsPaidUser":false}}}});
        assert_eq!(
            subscription_plan(&items, Some(&summary), 1700000000).as_deref(),
            Some("Free")
        );
        let unknown = json!({"data":{"SubscriptionPackageCode":"unknown","IsPaidUser":true}});
        assert_eq!(subscription_plan(&items, Some(&unknown), 1700000000), None);
        assert_eq!(subscription_plan(&items[2..], None, 1700000000), None);
    }
    #[test]
    fn ignores_expired_future_and_inactive_plans_and_preserves_unknown_state() {
        let items = [
            json!({"PackageName":"Pro Plan Subscription","DeductionEndTime":1699999999}),
            json!({"PackageName":"Team Plan Subscription","DeductionStartTime":1700001000}),
            json!({"PackageName":"Pro Plan Subscription","Status":1}),
            json!({"packageName":"Free Plan Subscription","status":0}),
        ];
        assert_eq!(
            subscription_plan(&items, None, 1700000000).as_deref(),
            Some("Free")
        );
        assert_eq!(subscription_plan(&[], None, 1700000000), None);
        let free = json!({"data":{"SubscriptionPackageCode":"","IsPaidUser":false}});
        assert_eq!(
            subscription_plan(&[], Some(&free), 1700000000).as_deref(),
            Some("Free")
        );
        let paid = json!({"data":{"IsPaidUser":true}});
        assert_eq!(subscription_plan(&items, Some(&paid), 1700000000), None);
    }
    #[test]
    fn quota_uses_precise_values_and_nearest_nonempty_expiry() {
        let result = summarize(
            &[
                json!({"CycleCapacitySizePrecise":"100.5","CycleCapacityRemainPrecise":"75.25","ExpiredTime":1700001000}),
                json!({"CapacitySize":50,"CapacityRemain":0,"ExpiredTime":1700000100}),
                json!({"CapacityRemain":500,"ExpiredTime":1699999999}),
            ],
            1700000000,
        );
        assert_eq!(result, (75.25, 150.5, Some(1700001000)));
    }
    #[test]
    fn long_term_placeholder_uses_cycle_and_timestamps_are_seconds() {
        assert_eq!(timestamp(Some(&json!(1700000000000_i64))), Some(1700000000));
        assert_eq!(
            timestamp(Some(&json!("2023-11-14T22:13:20Z"))),
            Some(1700000000)
        );
        assert_eq!(
            expiry(
                &json!({"DeductionEndTime":2500000000_i64,"CycleEndTime":1700001000}),
                1700000000
            ),
            Some(1700001000)
        );
        assert_eq!(
            expiry(&json!({"DeductionEndTime":2500000000_i64}), 1700000000),
            None
        );
    }
    #[test]
    fn empty_and_missing_resource_lists_are_distinct() {
        assert!(resources(&json!({"data":{}}), "Accounts").is_none());
        assert_eq!(
            resources(
                &json!({"data":{"Response":{"Data":{"Accounts":[]}}}}),
                "Accounts"
            ),
            Some(&vec![])
        );
        assert_eq!(summarize(&[], 1700000000), (0.0, 0.0, None));
    }
}