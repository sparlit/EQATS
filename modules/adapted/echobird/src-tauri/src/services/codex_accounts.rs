use base64::Engine as _;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use tauri::AppHandle;
use tauri_plugin_shell::ShellExt;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;
use tokio_util::sync::CancellationToken;

const LEGACY_BACKUP_FILE: &str = "codex-auth.bak.json";
#[cfg(target_os = "macos")]
const KEYCHAIN_SERVICE: &str = "Codex Auth";
const OAUTH_TOKEN_URL: &str = "https://auth.openai.com/oauth/token";
const OAUTH_CLIENT_ID: &str = "app_EMoamEEZ73f0CkXaXp7hrann";
const OAUTH_AUTHORIZE_URL: &str = "https://auth.openai.com/oauth/authorize";
const OAUTH_HOSTED_AUTH_URL: &str = "https://chatgpt.com/codex/desktop-auth";
const OAUTH_REDIRECT_PORT: u16 = 1455;
const OAUTH_FALLBACK_REDIRECT_PORT: u16 = 1457;
const OAUTH_REDIRECT_PATH: &str = "/auth/callback";
const OAUTH_SCOPES: &str =
    "openid profile email offline_access api.connectors.read api.connectors.invoke";
const OAUTH_TIMEOUT_SECONDS: u64 = 60;
static PENDING_LOGIN: Mutex<Option<(String, CancellationToken)>> = Mutex::new(None);

pub fn start_login() -> Result<String, String> {
    let mut pending = PENDING_LOGIN.lock().map_err(|_| "accountError.busy")?;
    if let Some((_, cancel)) = pending.take() {
        cancel.cancel();
    }
    let id = uuid::Uuid::new_v4().to_string();
    *pending = Some((id.clone(), CancellationToken::new()));
    Ok(id)
}

pub fn cancel_login(id: &str) -> Result<(), String> {
    let mut pending = PENDING_LOGIN.lock().map_err(|_| "accountError.busy")?;
    if pending.as_ref().is_some_and(|(current, _)| current == id) {
        if let Some((_, cancel)) = pending.take() {
            cancel.cancel();
        }
    }
    Ok(())
}

async fn await_login<T>(
    cancel: &CancellationToken,
    attempt: impl std::future::Future<Output = Result<T, String>>,
) -> Result<T, String> {
    tokio::select! {
        biased;
        _ = cancel.cancelled() => Err("accountError.cancelled".into()),
        result = tokio::time::timeout(std::time::Duration::from_secs(OAUTH_TIMEOUT_SECONDS), attempt) => {
            result.map_err(|_| "accountError.expired".to_string())?
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct CodexAccountSummary {
    pub id: String,
    pub email: String,
    pub plan: Option<String>,
    pub subscription_end_at: Option<i64>,
    pub quota_windows: Vec<QuotaWindow>,
    pub quota_percent: Option<i32>,
    pub quota_reset_at: Option<i64>,
    pub active: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct QuotaWindow {
    pub label: Option<String>,
    pub remaining_percent: i32,
    pub reset_at: Option<i64>,
}

const USAGE_URL: &str = "https://chatgpt.com/backend-api/wham/usage";

#[derive(Debug)]
struct AccountMetadata {
    id: String,
    email: String,
    plan: Option<String>,
    subscription_end_at: Option<i64>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AccountQuotaCache {
    #[serde(default)]
    quota_windows: Vec<QuotaWindow>,
    #[serde(default)]
    quota_percent: Option<i32>,
    #[serde(default)]
    quota_reset_at: Option<i64>,
    #[serde(default)]
    plan: Option<String>,
}

fn echobird_dir() -> Result<PathBuf, String> {
    dirs::home_dir()
        .map(|home| home.join(".echobird"))
        .ok_or_else(|| "accountError.home".to_string())
}

pub(crate) fn codex_home() -> Result<PathBuf, String> {
    if let Ok(raw) = std::env::var("CODEX_HOME") {
        let trimmed = raw.trim().trim_matches('"').trim_matches('\'').trim();
        if !trimmed.is_empty() {
            return Ok(PathBuf::from(trimmed));
        }
    }
    dirs::home_dir()
        .map(|home| home.join(".codex"))
        .ok_or_else(|| "accountError.home".to_string())
}

fn account_store_dir() -> Result<PathBuf, String> {
    Ok(echobird_dir()?.join("codex-accounts"))
}

fn quota_path(store_dir: &Path, account_id: &str) -> PathBuf {
    store_dir.join(format!("{account_id}.quota.json"))
}

fn decode_jwt_payload(token: &str) -> Option<Value> {
    let payload = token.split('.').nth(1)?;
    let decoded = base64::engine::general_purpose::URL_SAFE_NO_PAD
        .decode(payload)
        .or_else(|_| base64::engine::general_purpose::URL_SAFE.decode(payload))
        .ok()?;
    serde_json::from_slice(&decoded).ok()
}

fn jwt_is_expired(token: &str) -> bool {
    decode_jwt_payload(token)
        .and_then(|payload| payload.get("exp").and_then(Value::as_i64))
        .is_some_and(|expiry| expiry <= chrono::Utc::now().timestamp())
}

async fn refresh_auth_tokens(auth: &mut Value) -> Result<(), String> {
    let refresh_token = auth
        .get("tokens")
        .and_then(|tokens| non_empty_string(tokens.get("refresh_token")))
        .ok_or_else(|| "accountError.loginRequired".to_string())?;
    let response = reqwest::Client::new()
        .post(OAUTH_TOKEN_URL)
        .header(reqwest::header::ACCEPT, "application/json")
        .header(reqwest::header::USER_AGENT, "Codex Desktop")
        .header("originator", "Codex Desktop")
        .json(&serde_json::json!({
            "client_id": OAUTH_CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }))
        .send()
        .await
        .map_err(|error| format!("accountError.network|{error}"))?;
    let status = response.status();
    let body: Value = response
        .json()
        .await
        .map_err(|error| format!("accountError.format|{error}"))?;
    if !status.is_success() {
        return Err(format!("accountError.auth|HTTP {}", status.as_u16()));
    }
    let access_token = non_empty_string(body.get("access_token"))
        .ok_or_else(|| "accountError.format".to_string())?;
    let tokens = auth
        .get_mut("tokens")
        .and_then(Value::as_object_mut)
        .ok_or_else(|| "accountError.invalidAccount".to_string())?;
    tokens.insert("access_token".to_string(), Value::String(access_token));
    if let Some(id_token) = non_empty_string(body.get("id_token")) {
        tokens.insert("id_token".to_string(), Value::String(id_token));
    }
    if let Some(next_refresh_token) = non_empty_string(body.get("refresh_token")) {
        tokens.insert(
            "refresh_token".to_string(),
            Value::String(next_refresh_token),
        );
    }
    Ok(())
}

async fn request_usage(
    access_token: &str,
    account_id: Option<&str>,
) -> Result<reqwest::Response, String> {
    let mut request = reqwest::Client::new()
        .get(USAGE_URL)
        .bearer_auth(access_token)
        .header(reqwest::header::ACCEPT, "application/json")
        .header(reqwest::header::USER_AGENT, "Codex Desktop")
        .header("originator", "Codex Desktop")
        .header("x-openai-target-path", "/backend-api/wham/usage")
        .header("x-openai-target-route", "/backend-api/wham/usage");
    if let Some(account_id) = account_id.filter(|value| !value.is_empty()) {
        request = request.header("ChatGPT-Account-Id", account_id);
    }
    request.send().await.map_err(|error| {
        if error.is_timeout() {
            "accountError.quotaTimeout".to_string()
        } else {
            "accountError.network".to_string()
        }
    })
}

fn quota_response_detail(body: &Value) -> Option<String> {
    let detail = body
        .get("error")
        .and_then(|error| {
            error
                .as_str()
                .or_else(|| error.get("code").and_then(Value::as_str))
                .or_else(|| error.get("message").and_then(Value::as_str))
        })
        .or_else(|| body.get("message").and_then(Value::as_str))?;
    let detail = detail.trim();
    if detail.is_empty() {
        return None;
    }
    Some(detail.chars().take(96).collect())
}

fn quota_http_error(status: u16, body: &Value) -> String {
    let message = match status {
        401 => "accountError.loginRequired",
        403 => "accountError.denied",
        429 => "accountError.rateLimited",
        500..=599 => "accountError.unavailable",
        _ => "accountError.quota",
    };
    match quota_response_detail(body) {
        Some(detail) => format!("{message}|HTTP {status}|{detail}"),
        None => format!("{message}|HTTP {status}"),
    }
}

fn non_empty_string(value: Option<&Value>) -> Option<String> {
    value
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
}

fn auth_claims(value: &Value) -> Option<&Value> {
    value.get("https://api.openai.com/auth")
}

fn account_id_from_auth(auth: &Value) -> Option<String> {
    auth.get("tokens")
        .and_then(|tokens| non_empty_string(tokens.get("account_id")))
        .or_else(|| {
            token_payload(auth, "access_token").and_then(|payload| {
                auth_claims(&payload).and_then(|claims| {
                    non_empty_string(claims.get("chatgpt_account_id"))
                        .or_else(|| non_empty_string(claims.get("account_id")))
                })
            })
        })
}

fn token_payload(auth: &Value, key: &str) -> Option<Value> {
    auth.get("tokens")
        .and_then(|tokens| tokens.get(key))
        .and_then(Value::as_str)
        .and_then(decode_jwt_payload)
}

#[cfg(target_os = "macos")]
fn keychain_account(base_dir: &Path) -> String {
    let resolved = fs::canonicalize(base_dir).unwrap_or_else(|_| base_dir.to_path_buf());
    format!(
        "cli|{}",
        &hex::encode(Sha256::digest(resolved.to_string_lossy().as_bytes()))[..16]
    )
}

#[cfg(target_os = "macos")]
fn read_keychain_raw(base_dir: &Path) -> Result<Option<Vec<u8>>, String> {
    let output = crate::utils::process::command("security")
        .args(["find-generic-password", "-s", KEYCHAIN_SERVICE, "-a"])
        .arg(keychain_account(base_dir))
        .args(["-w"])
        .output()
        .map_err(|error| format!("accountError.keychain|{error}"))?;
    if !output.status.success() {
        return Ok(None);
    }
    let raw = output.stdout;
    if raw.is_empty() {
        Ok(None)
    } else {
        Ok(Some(raw))
    }
}

#[cfg(not(target_os = "macos"))]
fn read_keychain_raw(_base_dir: &Path) -> Result<Option<Vec<u8>>, String> {
    Ok(None)
}

#[cfg(target_os = "macos")]
fn write_keychain_raw(base_dir: &Path, raw: &[u8]) -> Result<(), String> {
    let secret = String::from_utf8(raw.to_vec())
        .map_err(|error| format!("accountError.keychain|{error}"))?;
    let output = crate::utils::process::command("security")
        .args(["add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a"])
        .arg(keychain_account(base_dir))
        .arg("-w")
        .arg(&secret)
        .output()
        .map_err(|error| format!("accountError.keychain|{error}"))?;
    if output.status.success() {
        Ok(())
    } else {
        Err(format!(
            "accountError.keychain|{}",
            String::from_utf8_lossy(&output.stderr).trim()
        ))
    }
}

#[cfg(not(target_os = "macos"))]
fn write_keychain_raw(_base_dir: &Path, _raw: &[u8]) -> Result<(), String> {
    Ok(())
}

fn is_oauth_auth(auth: &Value) -> bool {
    let auth_mode = auth
        .get("auth_mode")
        .and_then(Value::as_str)
        .unwrap_or_default();
    if auth_mode.eq_ignore_ascii_case("apikey") {
        return false;
    }

    auth.get("tokens")
        .and_then(Value::as_object)
        .is_some_and(|tokens| {
            ["id_token", "access_token"]
                .iter()
                .any(|key| non_empty_string(tokens.get(*key)).is_some())
        })
}

fn metadata_from_auth(auth: &Value, raw: &[u8]) -> Result<AccountMetadata, String> {
    if !is_oauth_auth(auth) {
        return Err("accountError.noAccount".to_string());
    }

    let id_payload = token_payload(auth, "id_token");
    let access_payload = token_payload(auth, "access_token");
    let email = id_payload
        .as_ref()
        .and_then(|payload| non_empty_string(payload.get("email")))
        .or_else(|| {
            access_payload
                .as_ref()
                .and_then(|payload| non_empty_string(payload.get("email")))
        });
    let account_id = account_id_from_auth(auth);
    let plan = id_payload
        .as_ref()
        .and_then(auth_claims)
        .and_then(|claims| non_empty_string(claims.get("chatgpt_plan_type")))
        .or_else(|| {
            access_payload
                .as_ref()
                .and_then(auth_claims)
                .and_then(|claims| non_empty_string(claims.get("chatgpt_plan_type")))
        });
    let subscription_end_at = access_payload
        .as_ref()
        .and_then(auth_claims)
        .and_then(|claims| subscription_end_at(claims.get("chatgpt_subscription_active_until")))
        .or_else(|| {
            id_payload
                .as_ref()
                .and_then(auth_claims)
                .and_then(|claims| {
                    subscription_end_at(claims.get("chatgpt_subscription_active_until"))
                })
        });

    let identity = account_id
        .as_deref()
        .or(email.as_deref())
        .map(str::as_bytes)
        .unwrap_or(raw);
    let id = hex::encode(Sha256::digest(identity));
    let email = email
        .or(account_id)
        .unwrap_or_else(|| "OpenAI account".to_string());

    Ok(AccountMetadata {
        id,
        email,
        plan,
        subscription_end_at,
    })
}

fn subscription_end_at(value: Option<&Value>) -> Option<i64> {
    let value = value?;
    let timestamp = value.as_i64().or_else(|| value.as_str()?.parse().ok());
    if let Some(timestamp) = timestamp {
        return Some(if timestamp > 1_000_000_000_000 {
            timestamp / 1000
        } else {
            timestamp
        });
    }
    chrono::DateTime::parse_from_rfc3339(value.as_str()?)
        .ok()
        .map(|date| date.timestamp())
}

fn read_oauth_snapshot(path: &Path) -> Option<(Vec<u8>, Value)> {
    let raw = fs::read(path).ok()?;
    let auth: Value = serde_json::from_slice(&raw).ok()?;
    is_oauth_auth(&auth).then_some((raw, auth))
}

fn read_current_oauth_snapshot(auth_path: &Path) -> Option<(Vec<u8>, Value)> {
    read_oauth_snapshot(auth_path).or_else(|| {
        let base_dir = auth_path.parent()?;
        let raw = read_keychain_raw(base_dir).ok()??;
        let auth: Value = serde_json::from_slice(&raw).ok()?;
        is_oauth_auth(&auth).then_some((raw, auth))
    })
}

pub(crate) fn has_effective_oauth_snapshot(auth_path: &Path, backup_path: &Path) -> bool {
    effective_snapshot(auth_path, backup_path).is_ok()
}

fn effective_snapshot(auth_path: &Path, backup_path: &Path) -> Result<(Vec<u8>, Value), String> {
    if let Some(snapshot) = read_current_oauth_snapshot(auth_path) {
        return Ok(snapshot);
    }
    read_oauth_snapshot(backup_path).ok_or_else(|| "accountError.noAccount".to_string())
}

fn write_private_file(path: &Path, raw: &[u8]) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| format!("accountError.write|{error}"))?;
    }
    fs::write(path, raw).map_err(|error| format!("accountError.write|{error}"))?;

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(0o600))
            .map_err(|error| format!("accountError.write|{error}"))?;
    }
    Ok(())
}

fn save_snapshot(raw: &[u8], auth: &Value, store_dir: &Path) -> Result<AccountMetadata, String> {
    let metadata = metadata_from_auth(auth, raw)?;
    write_private_file(&store_dir.join(format!("{}.json", metadata.id)), raw)?;
    Ok(metadata)
}

fn read_quota_cache(store_dir: &Path, account_id: &str) -> Option<AccountQuotaCache> {
    let cache: AccountQuotaCache =
        serde_json::from_slice(&fs::read(quota_path(store_dir, account_id)).ok()?).ok()?;
    if cache
        .quota_percent
        .is_some_and(|value| !(0..=100).contains(&value))
    {
        return None;
    }
    Some(cache)
}

fn active_account_id(auth_path: &Path) -> Option<String> {
    read_current_oauth_snapshot(auth_path)
        .and_then(|(raw, auth)| metadata_from_auth(&auth, &raw).ok())
        .map(|metadata| metadata.id)
}

fn persist_active_snapshot(codex_dir: &Path, account_id: &str, raw: &[u8]) -> Result<(), String> {
    let auth_path = codex_dir.join("auth.json");
    if active_account_id(&auth_path).as_deref() != Some(account_id) {
        return Ok(());
    }

    let keychain_is_current = read_keychain_raw(codex_dir).ok().flatten().is_some()
        && read_oauth_snapshot(&auth_path).is_none();
    if keychain_is_current {
        write_keychain_raw(codex_dir, raw)
    } else {
        write_private_file(&auth_path, raw)
    }
}

fn build_summary(
    mut metadata: AccountMetadata,
    active_id: Option<&str>,
    store_dir: &Path,
) -> CodexAccountSummary {
    let quota = read_quota_cache(store_dir, &metadata.id);
    if let Some(plan) = quota.as_ref().and_then(|cache| cache.plan.clone()) {
        metadata.plan = Some(plan);
    }
    CodexAccountSummary {
        active: active_id == Some(metadata.id.as_str()),
        quota_percent: quota.as_ref().and_then(|cache| cache.quota_percent),
        quota_reset_at: quota.as_ref().and_then(|cache| cache.quota_reset_at),
        quota_windows: quota.map_or_else(Vec::new, |cache| cache.quota_windows),
        id: metadata.id,
        email: metadata.email,
        plan: metadata.plan,
        subscription_end_at: metadata.subscription_end_at,
    }
}

fn quota_window_from_usage(body: &Value) -> Option<&Value> {
    let rate_limit = body.get("rate_limit")?;
    rate_limit
        .get("secondary_window")
        .filter(|window| !window.is_null())
        .or_else(|| {
            rate_limit
                .get("primary_window")
                .filter(|window| !window.is_null())
        })
}

fn quota_percent_from_usage(body: &Value) -> Result<Option<i32>, String> {
    let Some(window) = quota_window_from_usage(body) else {
        return Ok(None);
    };
    Ok(quota_percent_from_window(window))
}

fn quota_percent_from_window(window: &Value) -> Option<i32> {
    let used = [
        "used_percent",
        "usedPercent",
        "used_percentage",
        "usedPercentage",
    ]
    .iter()
    .find_map(|key| window.get(*key).and_then(Value::as_f64));
    if let Some(used) = used {
        return Some((100.0 - used).round().clamp(0.0, 100.0) as i32);
    }

    let remaining = [
        "remaining_percent",
        "remainingPercent",
        "remaining_percentage",
        "remainingPercentage",
    ]
    .iter()
    .find_map(|key| window.get(*key).and_then(Value::as_f64));
    remaining.map(|value| value.round().clamp(0.0, 100.0) as i32)
}

fn quota_reset_at_from_usage(body: &Value) -> Option<i64> {
    let window = quota_window_from_usage(body)?;
    quota_reset_at_from_window(window)
}

fn quota_reset_at_from_window(window: &Value) -> Option<i64> {
    let normalize = |mut value: i64| {
        if value > 1_000_000_000_000 {
            value /= 1000;
        }
        value
    };
    if let Some(value) = window
        .get("reset_at")
        .or_else(|| window.get("resetAt"))
        .and_then(|value| {
            value
                .as_i64()
                .or_else(|| value.as_str().and_then(|text| text.parse().ok()))
        })
    {
        return Some(normalize(value));
    }
    window
        .get("reset_after_seconds")
        .or_else(|| window.get("resetAfterSeconds"))
        .and_then(|value| {
            value
                .as_i64()
                .or_else(|| value.as_str().and_then(|text| text.parse().ok()))
        })
        .filter(|value| *value >= 0)
        .map(|value| chrono::Utc::now().timestamp() + value)
}

fn quota_window(body: &Value, key: &str) -> Option<QuotaWindow> {
    let window = body
        .get("rate_limit")?
        .get(key)
        .filter(|value| !value.is_null())?;
    let label = window
        .get("limit_window_seconds")
        .and_then(Value::as_i64)
        .filter(|seconds| *seconds > 0)
        .map(|seconds| {
            if seconds >= 86400 {
                format!("{}d", (seconds + 86399) / 86400)
            } else if seconds >= 3600 {
                format!("{}h", (seconds + 3599) / 3600)
            } else {
                format!("{}m", (seconds + 59) / 60)
            }
        });
    Some(QuotaWindow {
        label,
        remaining_percent: quota_percent_from_window(window)?,
        reset_at: quota_reset_at_from_window(window),
    })
}

pub(crate) fn save_effective_snapshot_at(
    auth_path: &Path,
    backup_path: &Path,
    store_dir: &Path,
) -> Result<CodexAccountSummary, String> {
    let (raw, auth) = effective_snapshot(auth_path, backup_path)?;
    let metadata = save_snapshot(&raw, &auth, store_dir)?;
    let mut summary = build_summary(metadata, None, store_dir);
    summary.active = true;
    Ok(summary)
}

pub fn capture_current_account() -> Result<CodexAccountSummary, String> {
    let codex_dir = codex_home()?;
    let state_dir = echobird_dir()?;
    save_effective_snapshot_at(
        &codex_dir.join("auth.json"),
        &state_dir.join(LEGACY_BACKUP_FILE),
        &state_dir.join("codex-accounts"),
    )
}

fn valid_account_id(account_id: &str) -> bool {
    account_id.len() == 64
        && account_id
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn base64url(bytes: &[u8]) -> String {
    use base64::Engine as _;
    base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(bytes)
}

fn random_token() -> String {
    let mut bytes = [0u8; 32];
    rand::RngCore::fill_bytes(&mut rand::thread_rng(), &mut bytes);
    base64url(&bytes)
}

fn build_oauth_url(redirect_uri: &str, state: &str, code_challenge: &str) -> String {
    let mut inner_query = url::form_urlencoded::Serializer::new(String::new());
    inner_query.append_pair("response_type", "code");
    inner_query.append_pair("client_id", OAUTH_CLIENT_ID);
    inner_query.append_pair("redirect_uri", redirect_uri);
    inner_query.append_pair("scope", OAUTH_SCOPES);
    inner_query.append_pair("code_challenge", code_challenge);
    inner_query.append_pair("code_challenge_method", "S256");
    inner_query.append_pair("id_token_add_organizations", "true");
    inner_query.append_pair("codex_cli_simplified_flow", "true");
    inner_query.append_pair("codex_streamlined_login", "true");
    inner_query.append_pair("state", state);
    inner_query.append_pair("originator", "Codex Desktop");
    let inner_url = format!("{OAUTH_AUTHORIZE_URL}?{}", inner_query.finish());

    let mut hosted_query = url::form_urlencoded::Serializer::new(String::new());
    hosted_query.append_pair("authorize_url", &inner_url);
    hosted_query.append_pair("codex_streamlined_login", "true");
    hosted_query.append_pair("no_universal_links", "1");
    format!("{OAUTH_HOSTED_AUTH_URL}?{}", hosted_query.finish())
}

#[allow(deprecated)]
fn open_browser(app_handle: &AppHandle, url: &str) -> Result<(), String> {
    app_handle
        .shell()
        .open(url, None)
        .map_err(|error| format!("accountError.browser|{error}"))
}

fn callback_response(status: &str, body: &str) -> Vec<u8> {
    format!(
        "HTTP/1.1 {status}\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len(),
    )
    .into_bytes()
}

fn parse_callback_request(request: &str) -> Result<(String, String), String> {
    let line = request
        .lines()
        .next()
        .ok_or_else(|| "accountError.authResponse".to_string())?;
    let target = line
        .strip_prefix("GET ")
        .and_then(|value| value.split_whitespace().next())
        .ok_or_else(|| "accountError.authResponse".to_string())?;
    let url = url::Url::parse(&format!("http://localhost{target}"))
        .map_err(|error| format!("accountError.authResponse|{error}"))?;
    if url.path() != OAUTH_REDIRECT_PATH {
        return Err("accountError.authResponse".to_string());
    }
    let params = url
        .query_pairs()
        .into_owned()
        .collect::<std::collections::HashMap<_, _>>();
    let state = params
        .get("state")
        .cloned()
        .ok_or_else(|| "accountError.state".to_string())?;
    let code = params
        .get("code")
        .cloned()
        .ok_or_else(|| "accountError.authResponse".to_string())?;
    Ok((state, code))
}

async fn exchange_oauth_code(
    code: &str,
    verifier: &str,
    redirect_uri: &str,
) -> Result<Value, String> {
    let response = reqwest::Client::new()
        .post("https://auth.openai.com/oauth/token")
        .form(&[
            ("grant_type", "authorization_code"),
            ("code", code),
            ("redirect_uri", redirect_uri),
            ("client_id", OAUTH_CLIENT_ID),
            ("code_verifier", verifier),
        ])
        .send()
        .await
        .map_err(|error| format!("accountError.auth|{error}"))?;
    let status = response.status();
    let body: Value = response
        .json()
        .await
        .map_err(|error| format!("accountError.authResponse|{error}"))?;
    if !status.is_success() {
        return Err(format!("accountError.auth|HTTP {}", status.as_u16()));
    }
    Ok(body)
}

fn store_oauth_token_response(token_response: &Value) -> Result<CodexAccountSummary, String> {
    let access_token = non_empty_string(token_response.get("access_token"))
        .ok_or_else(|| "accountError.authResponse".to_string())?;
    let id_token = non_empty_string(token_response.get("id_token"))
        .ok_or_else(|| "accountError.authResponse".to_string())?;
    let refresh_token = non_empty_string(token_response.get("refresh_token"));
    let auth = serde_json::json!({
        "auth_mode": "chatgpt",
        "tokens": {
            "id_token": id_token,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "account_id": Value::Null,
        }
    });
    let raw =
        serde_json::to_vec_pretty(&auth).map_err(|error| format!("accountError.format|{error}"))?;
    let metadata = save_snapshot(&raw, &auth, &account_store_dir()?)?;
    Ok(build_summary(metadata, None, &account_store_dir()?))
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct OAuthCallbackMessages {
    complete: String,
    close_window: String,
    failed: String,
}

fn callback_page(title: &str, message: &str) -> String {
    fn escape(value: &str) -> String {
        value
            .replace('&', "&amp;")
            .replace('<', "&lt;")
            .replace('>', "&gt;")
            .replace('"', "&quot;")
            .replace('\'', "&#39;")
    }
    format!(
        "<html><head><meta charset=\"utf-8\"></head><body><h2>{}</h2><p>{}</p></body></html>",
        escape(title),
        escape(message)
    )
}

pub async fn add_account_via_oauth(
    app_handle: AppHandle,
    login_id: String,
    callback_messages: OAuthCallbackMessages,
) -> Result<CodexAccountSummary, String> {
    let cancel = PENDING_LOGIN
        .lock()
        .map_err(|_| "accountError.busy")?
        .as_ref()
        .filter(|(id, _)| id == &login_id)
        .map(|(_, cancel)| cancel.clone())
        .ok_or("accountError.cancelled")?;
    let result = await_login(
        &cancel,
        complete_oauth(app_handle, &login_id, callback_messages),
    )
    .await;
    cancel_login(&login_id)?;
    result
}

async fn complete_oauth(
    app_handle: AppHandle,
    login_id: &str,
    callback_messages: OAuthCallbackMessages,
) -> Result<CodexAccountSummary, String> {
    let verifier = random_token();
    let challenge = base64url(&Sha256::digest(verifier.as_bytes()));
    let state = random_token();
    let mut listener = None;
    for port in [OAUTH_REDIRECT_PORT, OAUTH_FALLBACK_REDIRECT_PORT] {
        if let Ok(candidate) = TcpListener::bind(("127.0.0.1", port)).await {
            listener = Some(candidate);
            break;
        }
    }
    let listener = listener.ok_or_else(|| {
        format!(
            "accountError.ports|{} {}",
            OAUTH_REDIRECT_PORT, OAUTH_FALLBACK_REDIRECT_PORT
        )
    })?;
    let port = listener
        .local_addr()
        .map_err(|error| format!("accountError.authResponse|{error}"))?
        .port();
    let redirect_uri = format!("http://localhost:{port}{OAUTH_REDIRECT_PATH}");
    let auth_url = build_oauth_url(&redirect_uri, &state, &challenge);
    open_browser(&app_handle, &auth_url)?;

    let (mut stream, _) = listener
        .accept()
        .await
        .map_err(|error| format!("accountError.authResponse|{error}"))?;
    let mut request = vec![0u8; 8192];
    let size = stream
        .read(&mut request)
        .await
        .map_err(|error| format!("accountError.authResponse|{error}"))?;
    let callback = parse_callback_request(&String::from_utf8_lossy(&request[..size]));
    let (callback_state, code) = match callback {
        Ok(value) if value.0 == state => value,
        Ok(_) => {
            let _ = stream
                .write_all(&callback_response(
                    "400 Bad Request",
                    &callback_page(&callback_messages.failed, ""),
                ))
                .await;
            return Err("accountError.state".to_string());
        }
        Err(error) => {
            let _ = stream
                .write_all(&callback_response(
                    "400 Bad Request",
                    &callback_page(&callback_messages.failed, ""),
                ))
                .await;
            return Err(error);
        }
    };
    let _ = callback_state;
    stream
        .write_all(&callback_response(
            "200 OK",
            &callback_page(&callback_messages.complete, &callback_messages.close_window),
        ))
        .await
        .map_err(|error| format!("accountError.authResponse|{error}"))?;
    let token_response = exchange_oauth_code(&code, &verifier, &redirect_uri).await?;
    // Serialize saving against cancellation so an abandoned attempt cannot save a late response.
    let pending = PENDING_LOGIN.lock().map_err(|_| "accountError.busy")?;
    if !pending
        .as_ref()
        .is_some_and(|(id, cancel)| id == login_id && !cancel.is_cancelled())
    {
        return Err("accountError.cancelled".into());
    }
    store_oauth_token_response(&token_response)
}

fn list_accounts_at(
    auth_path: &Path,
    store_dir: &Path,
) -> Result<Vec<CodexAccountSummary>, String> {
    let active_id = active_account_id(auth_path);
    if !store_dir.exists() {
        return Ok(Vec::new());
    }

    let mut accounts = Vec::new();
    for entry in fs::read_dir(store_dir).map_err(|error| format!("accountError.read|{error}"))? {
        let Ok(entry) = entry else { continue };
        if entry.path().extension().and_then(|value| value.to_str()) != Some("json") {
            continue;
        }
        let Some((raw, auth)) = read_oauth_snapshot(&entry.path()) else {
            continue;
        };
        let Ok(metadata) = metadata_from_auth(&auth, &raw) else {
            continue;
        };
        accounts.push(build_summary(metadata, active_id.as_deref(), store_dir));
    }
    accounts.sort_by(|left, right| left.email.to_lowercase().cmp(&right.email.to_lowercase()));
    Ok(accounts)
}

pub fn list_accounts() -> Result<Vec<CodexAccountSummary>, String> {
    let codex_dir = codex_home()?;
    list_accounts_at(&codex_dir.join("auth.json"), &account_store_dir()?)
}

fn switch_account_at(
    account_id: &str,
    auth_path: &Path,
    backup_path: &Path,
    store_dir: &Path,
) -> Result<CodexAccountSummary, String> {
    if !valid_account_id(account_id) {
        return Err("accountError.invalidAccount".to_string());
    }

    if let Ok((raw, auth)) = effective_snapshot(auth_path, backup_path) {
        let _ = save_snapshot(&raw, &auth, store_dir);
    }

    let saved_path = store_dir.join(format!("{account_id}.json"));
    let raw = fs::read(&saved_path).map_err(|_| "accountError.invalidAccount".to_string())?;
    let auth: Value = serde_json::from_slice(&raw)
        .map_err(|error| format!("accountError.invalidAccount|{error}"))?;
    let metadata = metadata_from_auth(&auth, &raw)?;

    let keychain_is_current = read_keychain_raw(auth_path.parent().unwrap_or(Path::new("")))
        .ok()
        .flatten()
        .is_some()
        && read_oauth_snapshot(auth_path).is_none();
    let target = if !keychain_is_current
        && (read_oauth_snapshot(auth_path).is_some() || !backup_path.exists())
    {
        auth_path
    } else {
        backup_path
    };
    if keychain_is_current {
        write_keychain_raw(auth_path.parent().unwrap_or(Path::new("")), &raw)?;
    } else {
        write_private_file(target, &raw)?;
    }

    let mut summary = build_summary(metadata, None, store_dir);
    summary.active = true;
    Ok(summary)
}

pub(crate) fn restore_legacy_oauth(auth_path: &Path, backup_path: &Path) -> Result<bool, String> {
    if !backup_path.exists() {
        return Ok(false);
    }
    let raw = fs::read(backup_path).map_err(|error| format!("accountError.read|{error}"))?;
    let keychain_was_used = read_keychain_raw(auth_path.parent().unwrap_or(Path::new("")))
        .ok()
        .flatten()
        .is_some();
    write_private_file(auth_path, &raw)?;
    if keychain_was_used {
        write_keychain_raw(auth_path.parent().unwrap_or(Path::new("")), &raw)?;
    }
    fs::remove_file(backup_path).map_err(|error| format!("accountError.write|{error}"))?;
    Ok(true)
}

pub fn switch_account(account_id: &str) -> Result<CodexAccountSummary, String> {
    let codex_dir = codex_home()?;
    let state_dir = echobird_dir()?;
    switch_account_at(
        account_id,
        &codex_dir.join("auth.json"),
        &state_dir.join(LEGACY_BACKUP_FILE),
        &account_store_dir()?,
    )
}

pub fn delete_account(account_id: &str) -> Result<(), String> {
    if !valid_account_id(account_id) {
        return Err("accountError.invalidAccount".to_string());
    }
    let path = account_store_dir()?.join(format!("{account_id}.json"));
    if path.exists() {
        fs::remove_file(path).map_err(|error| format!("accountError.write|{error}"))?;
    }
    let quota = quota_path(&account_store_dir()?, account_id);
    if quota.exists() {
        fs::remove_file(quota).map_err(|error| format!("accountError.write|{error}"))?;
    }
    Ok(())
}

pub async fn refresh_account_quota(account_id: &str) -> Result<CodexAccountSummary, String> {
    if !valid_account_id(account_id) {
        return Err("accountError.invalidAccount".to_string());
    }
    let codex_dir = codex_home()?;
    let store_dir = account_store_dir()?;
    let saved_path = store_dir.join(format!("{account_id}.json"));
    let raw = fs::read(&saved_path).map_err(|_| "accountError.invalidAccount".to_string())?;
    let mut auth: Value = serde_json::from_slice(&raw)
        .map_err(|error| format!("accountError.invalidAccount|{error}"))?;
    let mut metadata = metadata_from_auth(&auth, &raw)?;
    let chatgpt_account_id = account_id_from_auth(&auth);
    let mut access_token = auth
        .get("tokens")
        .and_then(|tokens| non_empty_string(tokens.get("access_token")))
        .ok_or_else(|| "accountError.loginRequired".to_string())?;

    if jwt_is_expired(&access_token) {
        refresh_auth_tokens(&mut auth).await?;
        access_token = auth
            .get("tokens")
            .and_then(|tokens| non_empty_string(tokens.get("access_token")))
            .ok_or_else(|| "accountError.format".to_string())?;
        let refreshed_raw = serde_json::to_vec_pretty(&auth)
            .map_err(|error| format!("accountError.write|{error}"))?;
        write_private_file(&saved_path, &refreshed_raw)?;
        persist_active_snapshot(&codex_dir, account_id, &refreshed_raw)?;
    }

    let mut response = request_usage(&access_token, chatgpt_account_id.as_deref()).await?;
    if response.status() == reqwest::StatusCode::UNAUTHORIZED {
        refresh_auth_tokens(&mut auth).await?;
        access_token = auth
            .get("tokens")
            .and_then(|tokens| non_empty_string(tokens.get("access_token")))
            .ok_or_else(|| "accountError.format".to_string())?;
        let refreshed_raw = serde_json::to_vec_pretty(&auth)
            .map_err(|error| format!("accountError.write|{error}"))?;
        write_private_file(&saved_path, &refreshed_raw)?;
        persist_active_snapshot(&codex_dir, account_id, &refreshed_raw)?;
        response = request_usage(&access_token, chatgpt_account_id.as_deref()).await?;
    }
    let status = response.status();
    let body: Value = response
        .json()
        .await
        .map_err(|error| format!("accountError.format|{error}"))?;
    if !status.is_success() {
        return Err(quota_http_error(status.as_u16(), &body));
    }
    metadata.subscription_end_at = metadata_from_auth(&auth, &raw)?.subscription_end_at;
    let plan = non_empty_string(body.get("plan_type")).or_else(|| metadata.plan.clone());
    let mut quota_percent = quota_percent_from_usage(&body)?;
    if quota_percent.is_none()
        && plan
            .as_deref()
            .is_some_and(|value| value.eq_ignore_ascii_case("free"))
    {
        quota_percent = Some(100);
    }
    let mut quota_reset_at = quota_reset_at_from_usage(&body);
    if quota_percent.is_none() {
        quota_percent =
            read_quota_cache(&store_dir, account_id).and_then(|cache| cache.quota_percent);
    }
    if quota_reset_at.is_none() {
        quota_reset_at =
            read_quota_cache(&store_dir, account_id).and_then(|cache| cache.quota_reset_at);
    }
    let quota_windows = if body.get("rate_limit").is_some() {
        ["primary_window", "secondary_window"]
            .iter()
            .filter_map(|key| quota_window(&body, key))
            .collect::<Vec<_>>()
    } else {
        read_quota_cache(&store_dir, account_id).map_or_else(Vec::new, |cache| cache.quota_windows)
    };
    write_private_file(
        &quota_path(&store_dir, account_id),
        serde_json::to_string(&serde_json::json!({
            "quotaPercent": quota_percent,
            "quotaResetAt": quota_reset_at,
            "quotaWindows": quota_windows,
            "plan": plan,
        }))
        .map_err(|error| format!("accountError.quota|{error}"))?
        .as_bytes(),
    )?;

    let active_id = active_account_id(&codex_dir.join("auth.json"));
    Ok(build_summary(metadata, active_id.as_deref(), &store_dir))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn cancelled_login_drops_pending_callback_and_releases_port() {
        let cancel = CancellationToken::new();
        let listener = TcpListener::bind(("127.0.0.1", 0)).await.unwrap();
        let address = listener.local_addr().unwrap();
        let entered = std::sync::Arc::new(tokio::sync::Notify::new());
        let ready = entered.clone();
        let token = cancel.clone();
        let task = tokio::spawn(async move {
            await_login(&token, async move {
                ready.notify_one();
                listener
                    .accept()
                    .await
                    .map(|_| ())
                    .map_err(|e| e.to_string())
            })
            .await
        });
        entered.notified().await;
        cancel.cancel();
        assert_eq!(task.await.unwrap().unwrap_err(), "accountError.cancelled");
        assert!(TcpListener::bind(address).await.is_ok());
        assert_eq!(
            await_login(&CancellationToken::new(), async { Ok::<_, String>(42) })
                .await
                .unwrap(),
            42
        );
        let called = std::sync::atomic::AtomicBool::new(false);
        let result = await_login(&cancel, async {
            called.store(true, std::sync::atomic::Ordering::SeqCst);
            Ok::<_, String>(())
        })
        .await;
        assert!(result.is_err());
        assert!(!called.load(std::sync::atomic::Ordering::SeqCst));
    }

    #[test]
    fn cancelling_an_older_login_does_not_cancel_the_new_attempt() {
        let first = start_login().unwrap();
        let old_token = PENDING_LOGIN.lock().unwrap().as_ref().unwrap().1.clone();
        let second = start_login().unwrap();
        assert!(old_token.is_cancelled());
        cancel_login(&first).unwrap();
        assert_eq!(PENDING_LOGIN.lock().unwrap().as_ref().unwrap().0, second);
        cancel_login(&second).unwrap();
        assert!(PENDING_LOGIN.lock().unwrap().is_none());
    }

    #[test]
    fn callback_page_preserves_localized_text_and_escapes_html() {
        let page = callback_page("認証 <script>", "A&B");
        assert!(page.contains("charset=\"utf-8\""));
        assert!(page.contains("認証 &lt;script&gt;"));
        assert!(page.contains("A&amp;B"));
        assert!(!page.contains("<script>"));
    }

    use serde_json::json;

    fn temp_dir(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "echobird-codex-accounts-{name}-{}",
            uuid::Uuid::new_v4()
        ));
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn jwt(payload: Value) -> String {
        let payload = serde_json::to_vec(&payload).unwrap();
        format!(
            "header.{}.signature",
            base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(payload)
        )
    }

    fn oauth(email: &str, account_id: &str, refresh_token: &str) -> Vec<u8> {
        serde_json::to_vec_pretty(&json!({
            "auth_mode": "chatgpt",
            "tokens": {
                "id_token": jwt(json!({
                    "email": email,
                    "https://api.openai.com/auth": { "chatgpt_plan_type": "pro" }
                })),
                "access_token": jwt(json!({
                    "https://api.openai.com/auth": { "chatgpt_account_id": account_id }
                })),
                "refresh_token": refresh_token,
                "account_id": account_id
            }
        }))
        .unwrap()
    }

    #[test]
    fn captures_and_deduplicates_current_oauth_account() {
        let dir = temp_dir("capture");
        let auth_path = dir.join("codex/auth.json");
        let backup_path = dir.join("state/codex-auth.bak.json");
        let store_dir = dir.join("state/codex-accounts");
        write_private_file(
            &auth_path,
            &oauth("first@example.com", "acc-1", "refresh-1"),
        )
        .unwrap();

        let first = save_effective_snapshot_at(&auth_path, &backup_path, &store_dir).unwrap();
        write_private_file(
            &auth_path,
            &oauth("first@example.com", "acc-1", "refresh-2"),
        )
        .unwrap();
        let second = save_effective_snapshot_at(&auth_path, &backup_path, &store_dir).unwrap();

        assert_eq!(first.id, second.id);
        assert_eq!(first.email, "first@example.com");
        assert_eq!(first.plan.as_deref(), Some("pro"));
        assert_eq!(first.quota_percent, None);
        assert_eq!(first.quota_reset_at, None);
        assert_eq!(fs::read_dir(&store_dir).unwrap().count(), 1);
        let stored = fs::read_to_string(store_dir.join(format!("{}.json", first.id))).unwrap();
        assert!(stored.contains("refresh-2"));
        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn switches_the_backup_while_api_auth_is_active() {
        let dir = temp_dir("api-switch");
        let auth_path = dir.join("codex/auth.json");
        let backup_path = dir.join("state/codex-auth.bak.json");
        let store_dir = dir.join("state/codex-accounts");
        let first = oauth("first@example.com", "acc-1", "refresh-1");
        let second = oauth("second@example.com", "acc-2", "refresh-2");
        write_private_file(&backup_path, &first).unwrap();
        write_private_file(&auth_path, br#"{"OPENAI_API_KEY":"sk-test"}"#).unwrap();
        let second_value: Value = serde_json::from_slice(&second).unwrap();
        let second_metadata = save_snapshot(&second, &second_value, &store_dir).unwrap();

        switch_account_at(&second_metadata.id, &auth_path, &backup_path, &store_dir).unwrap();

        assert_eq!(
            fs::read(&auth_path).unwrap(),
            br#"{"OPENAI_API_KEY":"sk-test"}"#
        );
        assert_eq!(fs::read(&backup_path).unwrap(), second);
        let accounts = list_accounts_at(&auth_path, &store_dir).unwrap();
        assert_eq!(accounts.len(), 2);
        assert!(accounts.iter().all(|account| !account.active));
        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn refreshed_tokens_update_the_active_snapshot() {
        let dir = temp_dir("refresh-active");
        let codex_dir = dir.join("codex");
        let auth_path = codex_dir.join("auth.json");
        let store_dir = dir.join("state/codex-accounts");
        let old = oauth("first@example.com", "acc-1", "refresh-1");
        let new = oauth("first@example.com", "acc-1", "refresh-2");
        write_private_file(&auth_path, &old).unwrap();
        let auth: Value = serde_json::from_slice(&old).unwrap();
        let metadata = save_snapshot(&old, &auth, &store_dir).unwrap();

        persist_active_snapshot(&codex_dir, &metadata.id, &new).unwrap();

        assert_eq!(fs::read(&auth_path).unwrap(), new);
        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn rejects_api_key_credentials_as_an_account() {
        let dir = temp_dir("api-only");
        let auth_path = dir.join("codex/auth.json");
        let backup_path = dir.join("state/codex-auth.bak.json");
        let store_dir = dir.join("state/codex-accounts");
        write_private_file(&auth_path, br#"{"OPENAI_API_KEY":"sk-test"}"#).unwrap();

        let error = save_effective_snapshot_at(&auth_path, &backup_path, &store_dir).unwrap_err();
        assert!(error.contains("accountError.noAccount"));
        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn quota_prefers_the_weekly_window() {
        let body = json!({
            "rate_limit": {
                "primary_window": { "used_percent": 10 },
                "secondary_window": { "used_percent": 80 }
            }
        });
        assert_eq!(quota_percent_from_usage(&body).unwrap(), Some(20));
    }

    #[test]
    fn primary_window_is_used_when_weekly_window_is_missing() {
        let body = json!({
            "rate_limit": {
                "primary_window": {
                    "used_percent": 10,
                    "reset_after_seconds": 3600
                },
                "secondary_window": null
            }
        });
        assert_eq!(quota_percent_from_usage(&body).unwrap(), Some(90));
        assert!(quota_reset_at_from_usage(&body).is_some());
    }

    #[test]
    fn free_account_can_report_full_weekly_quota_and_reset() {
        let body = json!({
            "rate_limit": {
                "secondary_window": {
                    "used_percent": 0,
                    "reset_at": 1_800_000_000
                }
            }
        });
        assert_eq!(quota_percent_from_usage(&body).unwrap(), Some(100));
        assert_eq!(quota_reset_at_from_usage(&body), Some(1_800_000_000));
    }

    #[test]
    fn reads_subscription_end_from_the_account_token() {
        let auth = json!({
            "auth_mode": "chatgpt",
            "tokens": {
                "id_token": jwt(json!({
                    "email": "paid@example.test",
                    "https://api.openai.com/auth": {
                        "chatgpt_plan_type": "prolite",
                        "chatgpt_subscription_active_until": "2026-10-15T15:21:48+00:00"
                    }
                }))
            }
        });
        let summary = metadata_from_auth(&auth, b"fixture").unwrap();
        assert_eq!(summary.subscription_end_at, Some(1_792_077_708));
        assert_eq!(
            subscription_end_at(Some(&json!(1_792_077_708_000_i64))),
            Some(1_792_077_708)
        );
        assert_eq!(subscription_end_at(Some(&json!("not-a-date"))), None);
    }

    #[test]
    fn prefers_the_current_access_token_subscription_end() {
        let auth = json!({
            "auth_mode": "chatgpt",
            "tokens": {
                "id_token": jwt(json!({
                    "email": "paid@example.test",
                    "https://api.openai.com/auth": {
                        "chatgpt_subscription_active_until": "2026-10-15T15:21:48+00:00"
                    }
                })),
                "access_token": jwt(json!({
                    "https://api.openai.com/auth": {
                        "chatgpt_subscription_active_until": "2026-11-15T15:21:48+00:00"
                    }
                }))
            }
        });
        let summary = metadata_from_auth(&auth, b"fixture").unwrap();
        assert_eq!(summary.subscription_end_at, Some(1_794_756_108));
    }

    #[test]
    fn keeps_short_and_weekly_quota_windows_separate() {
        let body = json!({
            "rate_limit": {
                "primary_window": {"used_percent": 25, "reset_at": 1_800_000_100, "limit_window_seconds": 18000},
                "secondary_window": {"used_percent": 60, "reset_at": 1_800_000_200, "limit_window_seconds": 604800}
            }
        });
        assert_eq!(
            quota_window(&body, "primary_window"),
            Some(QuotaWindow {
                label: Some("5h".into()),
                remaining_percent: 75,
                reset_at: Some(1_800_000_100)
            })
        );
        assert_eq!(
            quota_window(&body, "secondary_window"),
            Some(QuotaWindow {
                label: Some("7d".into()),
                remaining_percent: 40,
                reset_at: Some(1_800_000_200)
            })
        );
        assert_eq!(
            quota_window(&json!({"rate_limit": {}}), "primary_window"),
            None
        );
        assert_eq!(
            quota_window(
                &json!({"rate_limit": {"primary_window": {"used_percent": 30, "limit_window_seconds": 604800}}}),
                "primary_window"
            ).and_then(|window| window.label),
            Some("7d".into())
        );
    }

    #[test]
    fn oauth_url_uses_the_official_hosted_login_wrapper() {
        let url = url::Url::parse(&build_oauth_url(
            "http://localhost:1455/auth/callback",
            "state",
            "challenge",
        ))
        .unwrap();
        assert_eq!(url.host_str(), Some("chatgpt.com"));
        assert_eq!(url.path(), "/codex/desktop-auth");
        assert_eq!(
            url.query_pairs()
                .find(|(key, _)| key == "codex_streamlined_login")
                .map(|(_, value)| value.into_owned()),
            Some("true".to_string())
        );
        let inner = url
            .query_pairs()
            .find(|(key, _)| key == "authorize_url")
            .and_then(|(_, value)| url::Url::parse(&value).ok())
            .unwrap();
        assert_eq!(inner.host_str(), Some("auth.openai.com"));
        assert_eq!(
            inner
                .query_pairs()
                .find(|(key, _)| key == "redirect_uri")
                .map(|(_, value)| value.into_owned()),
            Some("http://localhost:1455/auth/callback".to_string())
        );
        assert_eq!(
            inner
                .query_pairs()
                .find(|(key, _)| key == "codex_streamlined_login")
                .map(|(_, value)| value.into_owned()),
            Some("true".to_string())
        );
    }
}