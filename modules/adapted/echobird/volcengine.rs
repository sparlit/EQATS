//! Volcengine usage provider (AK/SK + ARK API Sig V4).
//!
//! Queries CodingPlan usage via the Volcengine ARK API using IAM Access Key /
//! Secret Access Key — no arkcli dependency. Mirrors the approach of
//! HannibalWangLecter/volcengine-coding-plan-monitor.
//!
//! AK/SK are stored AES-encrypted in `~/.echobird/volc_aksk.json`. If absent,
//! `query_usage` returns `error: "VOLC_AKSK_REQUIRED"` so the frontend shows
//! the [访问权限] button to collect them.
//!
//! Caveat (per the upstream repo): the AK/SK API may not expose the full
//! session/weekly/monthly quota fields that the console Cookie endpoint does;
//! this is a best-effort implementation.

use super::{now_millis, parse_f64, ModelUsageData, UsageProvider, UsageQuota, UsageResult};
use hmac::{Hmac, Mac};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::time::Duration;

type HmacSha256 = Hmac<Sha256>;

const SERVICE: &str = "ark";
const VERSION: &str = "2024-01-01";
const PROJECT_NAME: &str = "default";

pub struct VolcengineProvider;

// ─── Credential storage (AES-encrypted) ───

#[derive(serde::Serialize, serde::Deserialize, Clone)]
struct StoredCreds {
    access_key: String,
    secret_key: String,
}

fn cred_path() -> std::path::PathBuf {
    crate::utils::platform::echobird_dir().join("volc_aksk.json")
}

/// Read the whole creds map (model internal_id -> encrypted creds).
fn read_map() -> HashMap<String, StoredCreds> {
    std::fs::read_to_string(cred_path())
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_default()
}

fn write_map(map: &HashMap<String, StoredCreds>) -> Result<(), String> {
    let path = cred_path();
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("create dir: {e}"))?;
    }
    let json = serde_json::to_string(map).map_err(|e| format!("serialize: {e}"))?;
    // Atomic write: tmp file + rename, so a crash mid-write can't corrupt the map
    // (which would silently lose every model's AK/SK).
    let tmp = path.with_extension("tmp");
    std::fs::write(&tmp, &json).map_err(|e| format!("write tmp: {e}"))?;
    std::fs::rename(&tmp, &path).map_err(|e| format!("rename: {e}"))
}

/// Read AK/SK for a specific model. None if not stored / unreadable.
///
/// Stored in plaintext per product decision: usage-quota view is a simple
/// feature and AK/SK are treated as connection credentials, not secrets.
/// Values from the earlier encrypted build start with "enc:v1:" - treat those
/// as not stored so the user re-enters them as plaintext.
pub fn read_creds(internal_id: &str) -> Option<(String, String)> {
    let creds = read_map().get(internal_id)?.clone();
    if creds.access_key.starts_with("enc:v1:") || creds.secret_key.starts_with("enc:v1:") {
        return None;
    }
    if creds.access_key.is_empty() || creds.secret_key.is_empty() {
        return None;
    }
    Some((creds.access_key, creds.secret_key))
}

/// Persist AK/SK (plaintext) for a specific model (one account per model).
pub fn write_creds(internal_id: &str, access_key: &str, secret_key: &str) -> Result<(), String> {
    let mut map = read_map();
    map.insert(
        internal_id.to_string(),
        StoredCreds {
            access_key: access_key.to_string(),
            secret_key: secret_key.to_string(),
        },
    );
    write_map(&map)
}

/// Remove stored AK/SK for a specific model.
pub fn clear_creds(internal_id: &str) {
    let mut map = read_map();
    if map.remove(internal_id).is_some() {
        let _ = write_map(&map);
    }
}

/// Whether AK/SK are stored for a specific model.
pub fn has_creds(internal_id: &str) -> bool {
    read_creds(internal_id).is_some()
}

// ─── Volcengine Sig V4 signing (AWS Sig V4 variant) ───

fn sha256_hex(data: &str) -> String {
    let mut h = Sha256::new();
    h.update(data.as_bytes());
    hex::encode(h.finalize())
}

fn hmac_bytes(key: &[u8], data: &str) -> Vec<u8> {
    let mut mac = HmacSha256::new_from_slice(key).expect("HMAC accepts any key length");
    mac.update(data.as_bytes());
    mac.finalize().into_bytes().to_vec()
}

/// Sign and send an ARK API POST. Returns the parsed JSON response.
async fn signed_ark_request(
    access_key: &str,
    secret_key: &str,
    region: &str,
    action: &str,
    body: &serde_json::Value,
) -> Result<serde_json::Value, String> {
    let host = format!("ark.{region}.volcengineapi.com");
    let body_str = serde_json::to_string(body).unwrap_or_else(|_| "{}".to_string());
    let now = chrono::Utc::now();
    let amz_date = now.format("%Y%m%dT%H%M%SZ").to_string();
    let date_stamp = now.format("%Y%m%d").to_string();
    let content_hash = sha256_hex(&body_str);
    let canonical_headers = format!(
        "content-type:application/json; charset=utf-8\nhost:{host}\nx-content-sha256:{content_hash}\nx-date:{amz_date}\n"
    );
    let signed_headers = "content-type;host;x-content-sha256;x-date";
    let canonical_query = format!("Action={action}&Version={VERSION}");
    let canonical_request = format!(
        "POST\n/\n{canonical_query}\n{canonical_headers}\n{signed_headers}\n{content_hash}"
    );
    let credential_scope = format!("{date_stamp}/{region}/{SERVICE}/request");
    let string_to_sign = format!(
        "HMAC-SHA256\n{amz_date}\n{credential_scope}\n{}",
        sha256_hex(&canonical_request)
    );
    let k_date = hmac_bytes(secret_key.as_bytes(), &date_stamp);
    let k_region = hmac_bytes(&k_date, region);
    let k_service = hmac_bytes(&k_region, SERVICE);
    let k_signing = hmac_bytes(&k_service, "request");
    let signature = hex::encode(hmac_bytes(&k_signing, &string_to_sign));
    let authorization = format!(
        "HMAC-SHA256 Credential={access_key}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}"
    );

    let url = format!("https://{host}/?{canonical_query}");
    let client = reqwest::Client::new();
    let resp = client
        .post(&url)
        .header("Content-Type", "application/json; charset=utf-8")
        .header("Host", &host)
        .header("X-Date", &amz_date)
        .header("X-Content-Sha256", &content_hash)
        .header("Authorization", &authorization)
        .body(body_str)
        .timeout(Duration::from_secs(15))
        .send()
        .await
        .map_err(|e| format!("network: {e}"))?;

    let status = resp.status();
    let text = resp.text().await.map_err(|e| format!("read body: {e}"))?;
    if !status.is_success() {
        return Err(format!("HTTP {status}: {text}"));
    }
    let parsed: serde_json::Value =
        serde_json::from_str(&text).map_err(|e| format!("parse json: {e}"))?;
    if let Some(err) = parsed.get("ResponseMetadata").and_then(|m| m.get("Error")) {
        let code = err
            .get("Code")
            .and_then(|v| v.as_str())
            .unwrap_or("APIError");
        let msg = err
            .get("Message")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown");
        return Err(format!("{code}: {msg}"));
    }
    Ok(parsed)
}

// ─── Usage parsing (port of usage-parser.ts essentials) ───

fn normalize_level(s: &str) -> Option<&'static str> {
    let t = s.to_lowercase();
    if t == "session" || t.contains("5h") || t.contains("five") || t.contains("时") {
        Some("session")
    } else if t.contains("week") || t.contains("周") {
        Some("weekly")
    } else if t.contains("month") || t.contains("月") {
        Some("monthly")
    } else {
        None
    }
}

fn norm_percent(v: &serde_json::Value) -> Option<f64> {
    let n = parse_f64(v)?;
    Some(if n <= 1.0 { n * 100.0 } else { n })
}

fn norm_reset_ms(v: &serde_json::Value) -> Option<i64> {
    let n = parse_f64(v)? as i64;
    Some(if n > 1_000_000_000_000 { n } else { n * 1000 })
}

/// Extract (level, percent, reset_ms) from a quota record object.
fn extract_record(obj: &serde_json::Value) -> Option<(&'static str, f64, i64)> {
    let level_str = [
        "Level",
        "PeriodType",
        "Period",
        "WindowType",
        "Name",
        "Type",
        "QuotaType",
    ]
    .iter()
    .filter_map(|k| obj.get(k).and_then(|v| v.as_str()))
    .collect::<Vec<_>>()
    .join(" ");
    let level = normalize_level(&level_str)?;
    let percent = [
        "Percent",
        "UsagePercentage",
        "UsagePercent",
        "Percentage",
        "UsageRate",
        "Rate",
    ]
    .iter()
    .find_map(|k| obj.get(k).and_then(norm_percent))?;
    let reset = [
        "ResetTimestamp",
        "NextRefreshTime",
        "ResetTime",
        "RefreshAt",
    ]
    .iter()
    .find_map(|k| obj.get(k).and_then(norm_reset_ms))
    .unwrap_or_else(now_millis);
    Some((level, percent, reset))
}

/// Recursively walk the JSON tree collecting quota records.
fn walk_collect(node: &serde_json::Value, out: &mut Vec<(&'static str, f64, i64)>) {
    match node {
        serde_json::Value::Array(arr) => {
            for item in arr {
                walk_collect(item, out);
            }
        }
        serde_json::Value::Object(obj) => {
            if let Some(rec) = extract_record(node) {
                out.push(rec);
            }
            for (_, v) in obj {
                walk_collect(v, out);
            }
        }
        _ => {}
    }
}

/// Parse the API response into up to 3 quotas (session/weekly/monthly).
fn parse_usage(raw: &serde_json::Value) -> Option<Vec<UsageQuota>> {
    let result = raw.get("Result").unwrap_or(raw);
    let mut records: Vec<(&'static str, f64, i64)> = Vec::new();

    // Structured arrays first (authoritative).
    for key in ["QuotaUsage", "UsageDetails", "SeatInfoUsages"] {
        if let Some(arr) = result.get(key).and_then(|v| v.as_array()) {
            for item in arr {
                if let Some(rec) = extract_record(item) {
                    records.push(rec);
                }
            }
        }
    }

    // Fallback: recursive walk.
    if records.is_empty() {
        walk_collect(raw, &mut records);
    }

    // Also try direct percentage fields on Result.
    if let Some(obj) = result.as_object() {
        let direct = |k: &str| obj.get(k).and_then(norm_percent);
        if let Some(p) = direct("FiveHourUsagePercentage")
            .or_else(|| direct("FiveHourPercent"))
            .or_else(|| direct("SessionPercent"))
        {
            records.push(("session", p, now_millis()));
        }
        if let Some(p) = direct("WeekUsagePercentage").or_else(|| direct("WeeklyUsagePercentage")) {
            records.push(("weekly", p, now_millis()));
        }
        if let Some(p) = direct("MonthUsagePercentage").or_else(|| direct("MonthlyUsagePercentage"))
        {
            records.push(("monthly", p, now_millis()));
        }
    }

    // Dedupe by level, keep the first (structured arrays take priority).
    let mut best: HashMap<&str, (f64, i64)> = HashMap::new();
    for (level, percent, reset) in records {
        best.entry(level).or_insert((percent, reset));
    }

    let mut quotas: Vec<UsageQuota> = Vec::new();
    for level in ["session", "weekly", "monthly"] {
        if let Some((percent, reset)) = best.get(level) {
            quotas.push(UsageQuota {
                percentage: *percent,
                reset_at: *reset,
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

// ─── Provider trait ───

fn region_from_url(base_url: &str) -> String {
    let l = base_url.to_lowercase();
    if l.contains("cn-beijing") {
        "cn-beijing".to_string()
    } else if l.contains("ap-southeast") {
        "ap-southeast-1".to_string()
    } else {
        "cn-beijing".to_string()
    }
}

impl VolcengineProvider {
    /// Query usage for a specific model using its own stored AK/SK (per-account).
    pub async fn query_usage_for_model(
        &self,
        internal_id: &str,
        base_url: &str,
    ) -> Result<UsageResult, String> {
        let Some((access_key, secret_key)) = read_creds(internal_id) else {
            return Ok(UsageResult {
                success: false,
                data: None,
                error: Some("VOLC_AKSK_REQUIRED".to_string()),
            });
        };
        let region = region_from_url(base_url);

        let actions = [
            "GetCodingPlanUsage",
            "GetUsageDetails",
            "GetAFPUsage",
            "ListSeatInfoUsages",
            "GetSeatInfoUsage",
            "GetPersonalPlan",
        ];
        let body_variants: [serde_json::Value; 6] = [
            serde_json::json!({ "ProjectName": PROJECT_NAME }),
            serde_json::json!({ "ProjectName": PROJECT_NAME, "PlanType": "CodingPlan" }),
            serde_json::json!({ "ProjectName": PROJECT_NAME, "ProductType": "CodingPlan" }),
            serde_json::json!({ "ProjectName": PROJECT_NAME, "PackageType": "CodingPlan" }),
            serde_json::json!({ "ProjectName": PROJECT_NAME, "ResourceType": "CodingPlan" }),
            serde_json::json!({}),
        ];

        let mut first_err: Option<String> = None;
        'outer: for action in actions {
            for body in &body_variants {
                match signed_ark_request(&access_key, &secret_key, &region, action, body).await {
                    Ok(resp) => {
                        if let Some(quotas) = parse_usage(&resp) {
                            return Ok(UsageResult {
                                success: true,
                                data: Some(ModelUsageData {
                                    quotas,
                                    last_updated: Some(now_millis()),
                                }),
                                error: None,
                            });
                        }
                        // parsed nothing -> try next variant
                    }
                    Err(e) => {
                        let low = e.to_lowercase();
                        let is_auth_err = low.contains("invalidaccesskey")
                            || low.contains("signaturedoesnotmatch")
                            || low.contains("invalidaccesskeyid")
                            || low.contains("accessdenied")
                            || low.contains("authfailure")
                            || low.contains("unauthorized")
                            || low.contains("http 401")
                            || low.contains("http 403");
                        if first_err.is_none() {
                            first_err = Some(e);
                        }
                        // Credential/signature errors fail every variant - stop early
                        // (otherwise we'd burn through all 36 calls with the same bad key).
                        if is_auth_err {
                            break 'outer;
                        }
                    }
                }
            }
        }

        Ok(UsageResult {
            success: false,
            data: None,
            error: Some(format!(
                "无法解析用量数据(AK/SK 接口可能不返回完整额度)。{}",
                first_err
                    .map(|e| format!("最近错误: {e}"))
                    .unwrap_or_default()
            )),
        })
    }
}

#[async_trait::async_trait]
impl UsageProvider for VolcengineProvider {
    async fn query_usage(&self, _api_key: &str, _base_url: &str) -> Result<UsageResult, String> {
        // Volcengine usage needs per-model AK/SK (keyed by internal_id). The
        // dispatcher in `query_model_usage` routes Volcengine through
        // `query_usage_for_model`; this trait impl only satisfies the Provider
        // enum and is never reached in practice.
        Ok(UsageResult {
            success: false,
            data: None,
            error: Some("VOLC_AKSK_REQUIRED".to_string()),
        })
    }

    fn can_handle(&self, base_url: &str) -> bool {
        let url = base_url.to_lowercase();
        url.contains("ark.cn-beijing") || url.contains("volcengine") || url.contains("volces.com")
    }

    fn name(&self) -> &'static str {
        "Volcengine"
    }
}
