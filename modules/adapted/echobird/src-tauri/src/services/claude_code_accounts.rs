use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    fs,
    path::{Path, PathBuf},
    time::Duration,
};

const LOGIN_REQUIRED: &str = "accountError.loginRequired";
pub(super) static ACCOUNT_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

#[derive(Clone, Serialize, Deserialize, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ClaudeCodeQuota {
    pub remaining_percent: i32,
    pub reset_at: Option<i64>,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ClaudeCodeAccount {
    pub id: String,
    pub email: String,
    pub plan: Option<String>,
    pub five_hour: Option<ClaudeCodeQuota>,
    pub seven_day: Option<ClaudeCodeQuota>,
    pub active: bool,
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SavedAccount {
    summary: ClaudeCodeAccount,
    oauth: Value,
    identity: Value,
}

pub(crate) fn config_dir() -> Result<PathBuf, String> {
    if let Ok(value) = std::env::var("CLAUDE_CONFIG_DIR") {
        if !value.trim().is_empty() {
            return Ok(PathBuf::from(value.trim().trim_matches('"')));
        }
    }
    Ok(home()?.join(".claude"))
}

fn home() -> Result<PathBuf, String> {
    dirs::home_dir().ok_or_else(|| "accountError.home".to_string())
}

fn config_path() -> Result<PathBuf, String> {
    let dir = config_dir()?;
    if dir.join(".config.json").exists() {
        return Ok(dir.join(".config.json"));
    }
    Ok(if dir == home()?.join(".claude") {
        home()?.join(".claude.json")
    } else {
        dir.join(".claude.json")
    })
}

fn store() -> Result<PathBuf, String> {
    Ok(home()?.join(".echobird/claude-code-accounts"))
}

fn account_path(dir: &Path, id: &str) -> Result<PathBuf, String> {
    if id.len() != 64 || !id.bytes().all(|c| c.is_ascii_hexdigit()) {
        return Err("accountError.invalidAccount".to_string());
    }
    Ok(dir.join(format!("{id}.json")))
}

fn read_json(path: &Path) -> Result<Value, String> {
    let raw = fs::read(path).map_err(|_| format!("accountError.read|{}", path.display()))?;
    serde_json::from_slice(&raw).map_err(|_| format!("accountError.format|{}", path.display()))
}

fn write_json(path: &Path, value: &impl Serialize) -> Result<(), String> {
    use std::io::Write;
    fs::create_dir_all(path.parent().ok_or("accountError.write")?)
        .map_err(|e| format!("accountError.write|{e}"))?;
    let bytes = serde_json::to_vec_pretty(value).map_err(|e| format!("accountError.format|{e}"))?;
    let mut options = fs::OpenOptions::new();
    options.write(true).create(true).truncate(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let temporary = path.with_extension(format!("{}.tmp", uuid::Uuid::new_v4()));
    let result = (|| {
        let mut file = options
            .open(&temporary)
            .map_err(|e| format!("accountError.write|{e}"))?;
        file.write_all(&bytes)
            .map_err(|e| format!("accountError.write|{e}"))?;
        file.sync_all()
            .map_err(|e| format!("accountError.write|{e}"))?;
        drop(file);
        fs::rename(&temporary, path).map_err(|e| format!("accountError.write|{e}"))
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}

#[cfg(target_os = "macos")]
fn keychain_service() -> Result<String, String> {
    let suffix = if std::env::var("CLAUDE_CONFIG_DIR").is_ok_and(|s| !s.trim().is_empty()) {
        let hash = format!(
            "{:x}",
            Sha256::digest(config_dir()?.to_string_lossy().as_bytes())
        );
        format!("-{}", &hash[..8])
    } else {
        String::new()
    };
    Ok(format!("Claude Code-credentials{suffix}"))
}

fn read_credentials() -> Result<Value, String> {
    #[cfg(target_os = "macos")]
    {
        let output = crate::utils::process::command("security")
            .args(["find-generic-password", "-s", &keychain_service()?, "-w"])
            .output()
            .map_err(|e| format!("accountError.keychain|{e}"))?;
        if output.status.success() {
            return serde_json::from_slice(&output.stdout).map_err(|_| LOGIN_REQUIRED.to_string());
        }
    }
    let path = config_dir()?.join(".credentials.json");
    if !path.exists() {
        return Err(LOGIN_REQUIRED.to_string());
    }
    read_json(&path)
}

fn write_credentials(value: &Value) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        let output = crate::utils::process::command("security")
            .args([
                "add-generic-password",
                "-U",
                "-s",
                &keychain_service()?,
                "-a",
                &std::env::var("USER").map_err(|e| format!("accountError.keychain|{e}"))?,
                "-w",
                &value.to_string(),
            ])
            .output()
            .map_err(|e| format!("accountError.keychain|{e}"))?;
        if !output.status.success() {
            return Err("accountError.keychain".to_string());
        }
        Ok(())
    }
    #[cfg(not(target_os = "macos"))]
    write_json(&config_dir()?.join(".credentials.json"), value)
}

fn text<'a>(value: &'a Value, key: &str) -> Option<&'a str> {
    value.get(key)?.as_str().filter(|s| !s.trim().is_empty())
}

fn snapshot(credentials: &Value, config: &Value) -> Result<SavedAccount, String> {
    let oauth = credentials
        .get("claudeAiOauth")
        .filter(|v| text(v, "accessToken").is_some())
        .ok_or(LOGIN_REQUIRED)?;
    let identity = config.get("oauthAccount").ok_or(LOGIN_REQUIRED)?;
    let email = text(identity, "emailAddress").ok_or(LOGIN_REQUIRED)?;
    let account = text(identity, "accountUuid").unwrap_or(email);
    let org = text(identity, "organizationUuid").unwrap_or_default();
    let id = format!(
        "{:x}",
        Sha256::digest(format!("{account}\n{org}").as_bytes())
    );
    let plan = text(oauth, "subscriptionType").or_else(|| text(identity, "subscriptionType"));
    let tier = text(oauth, "rateLimitTier")
        .or_else(|| text(identity, "rateLimitTier"))
        .unwrap_or_default()
        .to_ascii_lowercase();
    let normalized_plan = plan.map(str::to_ascii_lowercase);
    let plan = match normalized_plan.as_deref() {
        Some("max") if tier.contains("20x") => Some("Max 20x".to_string()),
        Some("max") if tier.contains("5x") => Some("Max 5x".to_string()),
        Some(value) => Some(
            value
                .split_whitespace()
                .map(|word| {
                    let mut chars = word.chars();
                    chars
                        .next()
                        .map(|c| c.to_uppercase().to_string() + chars.as_str())
                        .unwrap_or_default()
                })
                .collect::<Vec<_>>()
                .join(" "),
        ),
        None => None,
    };
    Ok(SavedAccount {
        summary: ClaudeCodeAccount {
            id,
            email: email.to_string(),
            plan,
            five_hour: None,
            seven_day: None,
            active: true,
        },
        oauth: oauth.clone(),
        identity: identity.clone(),
    })
}

fn current() -> Result<SavedAccount, String> {
    let config = config_path()?;
    if !config.exists() {
        return Err(LOGIN_REQUIRED.to_string());
    }
    snapshot(&read_credentials()?, &read_json(&config)?)
}

fn load(dir: &Path, id: &str) -> Result<SavedAccount, String> {
    serde_json::from_value(read_json(&account_path(dir, id)?)?)
        .map_err(|_| "accountError.invalidAccount".to_string())
}

fn save(dir: &Path, account: &SavedAccount) -> Result<(), String> {
    write_json(&account_path(dir, &account.summary.id)?, account)
}

// Keep native token rotations before switching away or refreshing a saved account.
fn sync_current(dir: &Path) -> Result<Option<SavedAccount>, String> {
    let mut account = match current() {
        Ok(value) => value,
        Err(_) => return Ok(None),
    };
    let path = account_path(dir, &account.summary.id)?;
    if path.exists() {
        let saved = load(dir, &account.summary.id)?;
        // Adding the same account through OAuth must not be overwritten by an older CLI login.
        if text(&account.oauth, "accessToken") != text(&saved.oauth, "accessToken")
            && account.oauth["expiresAt"].as_i64().unwrap_or(0)
                <= saved.oauth["expiresAt"].as_i64().unwrap_or(0)
        {
            return Ok(Some(saved));
        }
        account.summary.five_hour = saved.summary.five_hour;
        account.summary.seven_day = saved.summary.seven_day;
    }
    if path.exists() {
        save(dir, &account)?;
    }
    Ok(Some(account))
}

pub async fn list() -> Result<Vec<ClaudeCodeAccount>, String> {
    let _guard = ACCOUNT_LOCK.lock().await;
    let dir = store()?;
    let active = sync_current(&dir)?.map(|a| a.summary.id);
    if !dir.exists() {
        return Ok(vec![]);
    }
    let mut accounts = vec![];
    for entry in fs::read_dir(&dir).map_err(|e| format!("accountError.read|{e}"))? {
        let path = entry.map_err(|e| format!("accountError.read|{e}"))?.path();
        let Some(id) = path.file_stem().and_then(|s| s.to_str()) else {
            continue;
        };
        if path.extension().map_or(true, |s| s != "json") {
            continue;
        }
        let mut account = load(&dir, id)?.summary;
        account.active = active.as_deref() == Some(&account.id);
        accounts.push(account);
    }
    accounts.sort_by(|a, b| a.email.cmp(&b.email).then(a.id.cmp(&b.id)));
    Ok(accounts)
}

pub(super) fn save_login(credentials: &Value, config: &Value) -> Result<ClaudeCodeAccount, String> {
    let mut account = snapshot(credentials, config)?;
    account.summary.active = current().is_ok_and(|live| live.summary.id == account.summary.id);
    save(&store()?, &account)?;
    Ok(account.summary)
}

fn merge_oauth(target: &mut Value, key: &str, value: &Value) -> Result<(), String> {
    target
        .as_object_mut()
        .ok_or("accountError.format")?
        .insert(key.to_string(), value.clone());
    Ok(())
}

pub async fn switch(id: &str) -> Result<ClaudeCodeAccount, String> {
    let _guard = ACCOUNT_LOCK.lock().await;
    let dir = store()?;
    sync_current(&dir)?;
    let mut account = load(&dir, id)?;
    let config_file = config_path()?;
    let mut config = if config_file.exists() {
        read_json(&config_file)?
    } else {
        json!({})
    };
    let original_config = config.clone();
    let mut credentials = match read_credentials() {
        Ok(value) => value,
        Err(_) if !config_dir()?.join(".credentials.json").exists() => json!({}),
        Err(error) => return Err(error),
    };
    merge_oauth(&mut config, "oauthAccount", &account.identity)?;
    config["hasCompletedOnboarding"] = json!(true);
    merge_oauth(&mut credentials, "claudeAiOauth", &account.oauth)?;
    write_json(&config_file, &config)?;
    if let Err(error) = write_credentials(&credentials) {
        write_json(&config_file, &original_config)
            .map_err(|rollback| format!("accountError.rollback|{error} {rollback}"))?;
        return Err(error);
    }
    account.summary.active = true;
    Ok(account.summary)
}

fn quota(window: &Value) -> Option<ClaudeCodeQuota> {
    let used = window.get("utilization")?.as_f64()?;
    let reset_at = text(window, "resets_at")
        .and_then(|s| chrono::DateTime::parse_from_rfc3339(s).ok())
        .map(|d| d.timestamp());
    Some(ClaudeCodeQuota {
        remaining_percent: (100.0 - used).clamp(0.0, 100.0).round() as i32,
        reset_at,
    })
}

async fn request_quota(token: &str) -> Result<reqwest::Response, String> {
    reqwest::Client::new()
        .get("https://api.anthropic.com/api/oauth/usage")
        .bearer_auth(token)
        .header("anthropic-beta", "oauth-2025-04-20")
        .header("Accept", "application/json")
        .timeout(Duration::from_secs(15))
        .send()
        .await
        .map_err(|_| "accountError.network".to_string())
}

async fn renew(dir: &Path, account: &mut SavedAccount) -> Result<(), String> {
    let refresh_token = text(&account.oauth, "refreshToken").ok_or(LOGIN_REQUIRED)?;
    let old_token = text(&account.oauth, "accessToken")
        .unwrap_or_default()
        .to_string();
    let response = reqwest::Client::new()
        .post("https://platform.claude.com/v1/oauth/token")
        .timeout(Duration::from_secs(15))
        .json(&json!({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": "9d1c250a-e61b-44d9-88ed-5944d1962f5e",
        }))
        .send()
        .await
        .map_err(|_| "accountError.network".to_string())?;
    if !response.status().is_success() {
        return Err("accountError.loginRequired".to_string());
    }
    let body: Value = response
        .json()
        .await
        .map_err(|_| "accountError.format".to_string())?;
    let token = text(&body, "access_token").ok_or("accountError.format")?;
    account.oauth["accessToken"] = json!(token);
    if let Some(token) = text(&body, "refresh_token") {
        account.oauth["refreshToken"] = json!(token);
    }
    if let Some(seconds) = body.get("expires_in").and_then(Value::as_i64) {
        account.oauth["expiresAt"] = json!(chrono::Utc::now().timestamp_millis() + seconds * 1000);
    }
    save(dir, account)?;
    // Do not overwrite a different login or a token rotated by the CLI while awaiting HTTP.
    if current().is_ok_and(|live| {
        live.summary.id == account.summary.id
            && text(&live.oauth, "accessToken") == Some(old_token.as_str())
    }) {
        let mut credentials = read_credentials()?;
        merge_oauth(&mut credentials, "claudeAiOauth", &account.oauth)?;
        write_credentials(&credentials)?;
    }
    Ok(())
}

pub async fn refresh(id: &str) -> Result<ClaudeCodeAccount, String> {
    let _guard = ACCOUNT_LOCK.lock().await;
    let dir = store()?;
    let active = sync_current(&dir)?.is_some_and(|a| a.summary.id == id);
    let mut account = load(&dir, id)?;
    let mut response =
        request_quota(text(&account.oauth, "accessToken").ok_or(LOGIN_REQUIRED)?).await?;
    if response.status() == reqwest::StatusCode::UNAUTHORIZED {
        renew(&dir, &mut account).await?;
        response =
            request_quota(text(&account.oauth, "accessToken").ok_or(LOGIN_REQUIRED)?).await?;
    }
    let status = response.status();
    if status == reqwest::StatusCode::UNAUTHORIZED || status == reqwest::StatusCode::FORBIDDEN {
        return Err("accountError.loginRequired".to_string());
    }
    if !status.is_success() {
        return Err(format!("accountError.quota|HTTP {}", status.as_u16()));
    }
    let body: Value = response
        .json()
        .await
        .map_err(|_| "accountError.format".to_string())?;
    let five_hour = quota(&body["five_hour"]);
    let seven_day = quota(&body["seven_day"]);
    if five_hour.is_none() && seven_day.is_none() {
        return Err("accountError.quota".to_string());
    }
    account.summary.five_hour = five_hour;
    account.summary.seven_day = seven_day;
    account.summary.active = active;
    save(&dir, &account)?;
    Ok(account.summary)
}

pub async fn delete(id: &str) -> Result<(), String> {
    let _guard = ACCOUNT_LOCK.lock().await;
    let path = account_path(&store()?, id)?;
    if path.exists() {
        fs::remove_file(path).map_err(|e| format!("accountError.write|{e}"))?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn recognizes_max_tiers_without_guessing_an_unknown_tier() {
        for (plan, tier, expected) in [
            ("max", "default_claude_max_5x", "Max 5x"),
            ("Max", "default_claude_max_20x", "Max 20x"),
            ("MAX", "", "Max"),
            ("pro", "", "Pro"),
            ("free", "", "Free"),
        ] {
            let account = snapshot(
                &json!({"claudeAiOauth":{"accessToken":"test","subscriptionType":plan,"rateLimitTier":tier}}),
                &json!({"oauthAccount":{"emailAddress":"test@example.com"}}),
            ).unwrap();
            assert_eq!(account.summary.plan.as_deref(), Some(expected));
        }
    }

    #[test]
    fn saves_separate_accounts_and_replaces_snapshot_without_exposing_tokens() {
        let dir =
            std::env::temp_dir().join(format!("echobird-claude-test-{}", uuid::Uuid::new_v4()));
        let mut first = snapshot(
            &json!({"claudeAiOauth":{"accessToken":"first-token", "refreshToken":"first-refresh"}}),
            &json!({"oauthAccount":{"emailAddress":"first@example.com"}}),
        )
        .unwrap();
        let second = snapshot(
            &json!({"claudeAiOauth":{"accessToken":"second-token"}}),
            &json!({"oauthAccount":{"emailAddress":"second@example.com"}}),
        )
        .unwrap();
        save(&dir, &first).unwrap();
        save(&dir, &second).unwrap();
        first.oauth["accessToken"] = json!("rotated-token");
        save(&dir, &first).unwrap();
        assert_eq!(
            load(&dir, &first.summary.id).unwrap().oauth["accessToken"],
            "rotated-token"
        );
        assert_eq!(
            load(&dir, &second.summary.id).unwrap().oauth["accessToken"],
            "second-token"
        );
        let summary = serde_json::to_string(&first.summary).unwrap();
        assert!(!summary.contains("token"));
        assert!(!summary.contains("refresh"));
        fs::remove_file(account_path(&dir, &first.summary.id).unwrap()).unwrap();
        assert!(load(&dir, &second.summary.id).is_ok());
        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn rejects_api_key_only_and_incomplete_login() {
        assert!(snapshot(&json!({"apiKey":"test"}), &json!({})).is_err());
        assert!(snapshot(&json!({"claudeAiOauth":{"accessToken":"test"}}), &json!({})).is_err());
    }

    #[test]
    fn account_id_survives_token_rotation_and_separates_organizations() {
        let mut config = json!({"oauthAccount":{"emailAddress":"test@example.com", "accountUuid":"a", "organizationUuid":"one"}});
        let first = snapshot(&json!({"claudeAiOauth":{"accessToken":"first"}}), &config).unwrap();
        let next = snapshot(&json!({"claudeAiOauth":{"accessToken":"next"}}), &config).unwrap();
        assert_eq!(first.summary.id, next.summary.id);
        config["oauthAccount"]["organizationUuid"] = json!("two");
        assert_ne!(
            first.summary.id,
            snapshot(&json!({"claudeAiOauth":{"accessToken":"next"}}), &config)
                .unwrap()
                .summary
                .id
        );
    }

    #[test]
    fn switch_merges_identity_without_replacing_user_settings() {
        let mut config =
            json!({"projects":{"demo":{}},"theme":"dark","oauthAccount":{"emailAddress":"old"}});
        merge_oauth(&mut config, "oauthAccount", &json!({"emailAddress":"new"})).unwrap();
        assert_eq!(config["theme"], "dark");
        assert!(config["projects"].get("demo").is_some());
        assert_eq!(config["oauthAccount"]["emailAddress"], "new");
        assert!(merge_oauth(&mut json!([]), "oauthAccount", &json!({})).is_err());
        assert!(account_path(Path::new("test"), "../credentials").is_err());
    }

    #[test]
    fn quota_keeps_both_windows_and_their_own_resets() {
        let body = json!({"five_hour":{"utilization":20,"resets_at":"2026-09-19T12:00:00Z"},"seven_day":{"utilization":85,"resets_at":"2026-09-22T12:00:00Z"}});
        let five = quota(&body["five_hour"]).unwrap();
        let seven = quota(&body["seven_day"]).unwrap();
        assert_eq!(five.remaining_percent, 80);
        assert_eq!(seven.remaining_percent, 15);
        assert_eq!(seven.reset_at.unwrap() - five.reset_at.unwrap(), 3 * 86400);
        assert!(quota(&Value::Null).is_none());
        assert_eq!(
            quota(&json!({"utilization":0})).unwrap().remaining_percent,
            100
        );
        assert_eq!(
            quota(&json!({"utilization":100}))
                .unwrap()
                .remaining_percent,
            0
        );
    }
}