//! WorkBuddy account authentication. Protocol reference: changexbc/workbuddy-switch (MIT).
//! See tools/workbuddy/workbuddy-switch-LICENSE.txt for the upstream notice.
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::HashMap,
    fs,
    path::{Path, PathBuf},
    sync::{Mutex, OnceLock},
    time::Duration,
};

#[path = "workbuddy_credits.rs"]
mod credits;
#[path = "workbuddy_history.rs"]
mod history;
static ACCOUNT_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());
static LOGINS: OnceLock<Mutex<HashMap<String, Login>>> = OnceLock::new();
const LOGIN_TIMEOUT_SECONDS: i64 = 60;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Edition {
    #[serde(rename = "workbuddy")]
    Cn,
    #[serde(rename = "workbuddyai")]
    Ai,
}
impl Edition {
    fn api(self) -> &'static str {
        match self {
            Self::Cn => "https://www.codebuddy.cn",
            Self::Ai => "https://www.workbuddy.ai",
        }
    }
    fn platform(self) -> &'static str {
        match self {
            Self::Cn => "workbuddy",
            Self::Ai => "workbuddy-ai",
        }
    }
    fn tool(self) -> &'static str {
        match self {
            Self::Cn => "workbuddy",
            Self::Ai => "workbuddyai",
        }
    }
    fn auth_path(self) -> Result<PathBuf, String> {
        let home = dirs::home_dir().ok_or("accountError.home")?;
        #[cfg(windows)]
        let root = dirs::data_local_dir().ok_or("accountError.home")?;
        #[cfg(target_os = "macos")]
        let root = home.join("Library/Application Support");
        #[cfg(not(any(windows, target_os = "macos")))]
        let root = home.join(".local/share");
        let _ = home;
        Ok(root
            .join("CodeBuddyExtension/Data/Public/auth")
            .join(match self {
                Self::Cn => "workbuddy-desktop.info",
                Self::Ai => "workbuddy-desktop-ai.info",
            }))
    }
    fn accepts_domain(self, domain: &str) -> bool {
        let domain = domain.to_ascii_lowercase();
        domain.is_empty()
            || match self {
                Self::Cn => [
                    "codebuddy.cn",
                    "www.codebuddy.cn",
                    "workbuddy.cn",
                    "www.workbuddy.cn",
                ]
                .contains(&domain.as_str()),
                Self::Ai => ["workbuddy.ai", "www.workbuddy.ai"].contains(&domain.as_str()),
            }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Account {
    pub id: String,
    pub name: String,
    pub edition: Edition,
    #[serde(default)]
    pub plan: Option<String>,
    pub remaining: Option<f64>,
    pub total: Option<f64>,
    #[serde(default)]
    pub base_remaining: Option<f64>,
    #[serde(default)]
    pub base_total: Option<f64>,
    #[serde(default)]
    pub base_reset_at: Option<i64>,
    #[serde(default)]
    pub reward_remaining: Option<f64>,
    #[serde(default)]
    pub reward_total: Option<f64>,
    #[serde(default)]
    pub addon_remaining: Option<f64>,
    #[serde(default)]
    pub daily_claimed_at: Option<i64>,
    pub expires_at: Option<i64>,
    pub active: bool,
}
#[derive(Serialize, Deserialize)]
struct Saved {
    summary: Account,
    session: Value,
}
#[derive(Clone)]
struct Login {
    edition: Edition,
    state: String,
    expires: i64,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LoginStart {
    login_id: String,
    verification_uri: String,
    expires_at: i64,
}

fn text<'a>(value: &'a Value, key: &str) -> Option<&'a str> {
    value.get(key)?.as_str().filter(|s| !s.trim().is_empty())
}
fn store() -> Result<PathBuf, String> {
    Ok(dirs::home_dir()
        .ok_or("accountError.home")?
        .join(".echobird/workbuddy-accounts"))
}
fn account_path(dir: &Path, id: &str) -> Result<PathBuf, String> {
    if id.len() != 64 || !id.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err("accountError.invalidAccount".into());
    }
    Ok(dir.join(format!("{id}.json")))
}
fn read(path: &Path) -> Result<Value, String> {
    serde_json::from_slice(&fs::read(path).map_err(|_| "accountError.read")?)
        .map_err(|_| "accountError.format".into())
}
fn write(path: &Path, value: &impl Serialize) -> Result<(), String> {
    use std::io::Write;
    fs::create_dir_all(path.parent().ok_or("accountError.write")?)
        .map_err(|_| "accountError.write")?;
    let temporary = path.with_extension(format!("{}.tmp", uuid::Uuid::new_v4()));
    let result = (|| {
        let mut options = fs::OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut file = options.open(&temporary).map_err(|_| "accountError.write")?;
        file.write_all(&serde_json::to_vec_pretty(value).map_err(|_| "accountError.format")?)
            .map_err(|_| "accountError.write")?;
        file.sync_all().map_err(|_| "accountError.write")?;
        drop(file);
        fs::rename(&temporary, path).map_err(|_| "accountError.write".to_string())
    })();
    if result.is_err() {
        let _ = fs::remove_file(temporary);
    }
    result
}
fn snapshot(edition: Edition, session: Value) -> Result<Saved, String> {
    let profile = &session["account"];
    let uid = text(profile, "uid")
        .or_else(|| text(profile, "id"))
        .ok_or("accountError.invalidAccount")?;
    let auth = &session["auth"];
    let token = &auth["accessToken"];
    if !(token.as_str().is_some_and(|s| !s.is_empty()) || token.get("$wbEncrypted").is_some())
        || !edition.accepts_domain(text(auth, "domain").unwrap_or_default())
    {
        return Err("accountError.invalidAccount".into());
    }
    let id = format!(
        "{:x}",
        Sha256::digest(format!(
            "{}:{uid}:{}",
            edition.tool(),
            text(profile, "enterpriseId").unwrap_or_default()
        ))
    );
    let name = text(profile, "email")
        .or_else(|| text(profile, "nickname"))
        .unwrap_or(uid)
        .to_string();
    Ok(Saved {
        summary: Account {
            id,
            name,
            edition,
            plan: None,
            remaining: None,
            total: None,
            base_remaining: None,
            base_total: None,
            base_reset_at: None,
            reward_remaining: None,
            reward_total: None,
            addon_remaining: None,
            daily_claimed_at: None,
            expires_at: None,
            active: false,
        },
        session,
    })
}
fn load(id: &str, edition: Edition) -> Result<Saved, String> {
    let saved: Saved = serde_json::from_value(read(&account_path(&store()?, id)?)?)
        .map_err(|_| "accountError.invalidAccount")?;
    if saved.summary.edition != edition
        || saved.summary.id != id
        || snapshot(edition, saved.session.clone())?.summary.id != id
    {
        return Err("accountError.invalidAccount".into());
    }
    Ok(saved)
}
fn save(saved: &Saved) -> Result<(), String> {
    write(&account_path(&store()?, &saved.summary.id)?, saved)
}

pub async fn list(edition: Edition) -> Result<Vec<Account>, String> {
    list_from_paths(edition, &store()?, &edition.auth_path()?).await
}

async fn list_from_paths(
    edition: Edition,
    dir: &Path,
    auth_path: &Path,
) -> Result<Vec<Account>, String> {
    // Saved accounts are replaced atomically, so reads need not wait for network refreshes.
    if !dir.exists() {
        return Ok(Vec::new());
    }
    let active = read(auth_path)
        .ok()
        .and_then(|v| snapshot(edition, v).ok())
        .map(|s| s.summary.id);
    let mut accounts = Vec::new();
    for entry in fs::read_dir(dir).map_err(|_| "accountError.read")? {
        let path = entry.map_err(|_| "accountError.read")?.path();
        if path.extension().and_then(|s| s.to_str()) != Some("json") {
            continue;
        }
        let saved: Saved =
            serde_json::from_value(read(&path)?).map_err(|_| "accountError.format")?;
        if saved.summary.edition == edition {
            let mut summary = saved.summary;
            summary.active = active.as_deref() == Some(&summary.id);
            accounts.push(summary);
        }
    }
    accounts.sort_by(|a, b| a.name.cmp(&b.name).then(a.id.cmp(&b.id)));
    Ok(accounts)
}
pub async fn delete(edition: Edition, id: &str) -> Result<(), String> {
    let _guard = ACCOUNT_LOCK.lock().await;
    load(id, edition)?;
    fs::remove_file(account_path(&store()?, id)?).map_err(|_| "accountError.write".into())
}
fn client() -> Result<reqwest::Client, String> {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(20))
        .build()
        .map_err(|_| "accountError.network".into())
}
async fn response(request: reqwest::RequestBuilder) -> Result<Value, String> {
    let response = request.send().await.map_err(|_| "accountError.network")?;
    let status = response.status();
    if !status.is_success() {
        return Err(format!(
            "{}|HTTP {}",
            match status.as_u16() {
                401 => "accountError.loginRequired",
                403 => "accountError.denied",
                429 => "accountError.rateLimited",
                _ => "accountError.network",
            },
            status.as_u16()
        ));
    }
    response
        .json()
        .await
        .map_err(|_| "accountError.format".into())
}
fn success(value: &Value) -> bool {
    matches!(value["code"].as_i64(), Some(0 | 200))
}
fn normalize_auth(mut auth: Value) -> Value {
    for (camel, snake) in [
        ("accessToken", "access_token"),
        ("refreshToken", "refresh_token"),
        ("tokenType", "token_type"),
    ] {
        if auth.get(camel).is_none() {
            if let Some(v) = auth.get(snake).cloned() {
                auth[camel] = v;
            }
        }
    }
    for (absolute, relative) in [
        ("expiresAt", "expiresIn"),
        ("refreshExpiresAt", "refreshExpiresIn"),
    ] {
        if let Some(ts) = credits::timestamp(auth.get(absolute)) {
            auth[absolute] = json!(ts * 1000);
        } else if let Some(seconds) = auth[relative].as_i64() {
            auth[absolute] = json!(chrono::Utc::now().timestamp_millis() + seconds * 1000);
        }
    }
    auth
}
pub async fn start_login(edition: Edition) -> Result<LoginStart, String> {
    let body = response(
        client()?
            .post(format!("{}/v2/plugin/auth/state", edition.api()))
            .query(&[("platform", edition.platform())])
            .json(&json!({})),
    )
    .await?;
    if !success(&body) {
        return Err("accountError.auth".into());
    }
    let data = &body["data"];
    let state = text(data, "state")
        .ok_or("accountError.authResponse")?
        .to_string();
    let uri = text(data, "authUrl")
        .or_else(|| text(data, "auth_url"))
        .or_else(|| text(data, "url"))
        .map(str::to_owned)
        .unwrap_or_else(|| format!("{}/login?state={state}", edition.api()));
    let url = url::Url::parse(&uri).map_err(|_| "accountError.authResponse")?;
    if url.scheme() != "https"
        || !edition.accepts_domain(url.host_str().unwrap_or_default())
        || url.host_str().is_none()
    {
        return Err("accountError.authResponse".into());
    }
    let expires = chrono::Utc::now().timestamp() + LOGIN_TIMEOUT_SECONDS;
    let login_id = uuid::Uuid::new_v4().to_string();
    let mut pending = LOGINS
        .get_or_init(Mutex::default)
        .lock()
        .map_err(|_| "accountError.busy")?;
    pending.retain(|_, login| login.expires > chrono::Utc::now().timestamp());
    pending.insert(
        login_id.clone(),
        Login {
            edition,
            state,
            expires,
        },
    );
    Ok(LoginStart {
        login_id,
        verification_uri: uri,
        expires_at: expires,
    })
}
pub fn cancel_login(id: &str) -> Result<(), String> {
    LOGINS
        .get_or_init(Mutex::default)
        .lock()
        .map_err(|_| "accountError.busy")?
        .remove(id);
    Ok(())
}
pub async fn poll_login(id: &str) -> Result<Option<Account>, String> {
    let login = LOGINS
        .get_or_init(Mutex::default)
        .lock()
        .map_err(|_| "accountError.busy")?
        .get(id)
        .cloned()
        .ok_or("accountError.cancelled")?;
    if login.expires <= chrono::Utc::now().timestamp() {
        cancel_login(id)?;
        return Err("accountError.expired".into());
    }
    let client = client()?;
    let token = response(
        client
            .get(format!("{}/v2/plugin/auth/token", login.edition.api()))
            .query(&[("state", &login.state)]),
    )
    .await?;
    if !success(&token)
        || text(&token["data"], "accessToken")
            .or_else(|| text(&token["data"], "access_token"))
            .is_none()
    {
        return Ok(None);
    }
    let auth = normalize_auth(token["data"].clone());
    if !login
        .edition
        .accepts_domain(text(&auth, "domain").unwrap_or_default())
    {
        return Err("accountError.authResponse".into());
    }
    let mut request = client
        .get(format!("{}/v2/plugin/login/account", login.edition.api()))
        .query(&[("state", &login.state)])
        .bearer_auth(text(&auth, "accessToken").ok_or("accountError.authResponse")?);
    if let Some(domain) = text(&auth, "domain") {
        request = request.header("X-Domain", domain);
    }
    let profile = response(request).await?;
    if !success(&profile) {
        return Err("accountError.authResponse".into());
    }
    if !login
        .edition
        .accepts_domain(text(&profile["data"], "domain").unwrap_or_default())
    {
        return Err("accountError.authResponse".into());
    }
    let saved = snapshot(
        login.edition,
        json!({"account": profile["data"], "auth": auth}),
    )?;
    let _guard = ACCOUNT_LOCK.lock().await;
    let mut pending = LOGINS
        .get_or_init(Mutex::default)
        .lock()
        .map_err(|_| "accountError.busy")?;
    if !pending
        .get(id)
        .is_some_and(|s| s.expires > chrono::Utc::now().timestamp())
    {
        return Err("accountError.cancelled".into());
    }
    save(&saved)?;
    pending.remove(id);
    Ok(Some(saved.summary))
}
fn authorized(
    client: &reqwest::Client,
    saved: &Saved,
    url: &str,
) -> Result<reqwest::RequestBuilder, String> {
    let auth = &saved.session["auth"];
    let mut request = client
        .post(url)
        .bearer_auth(text(auth, "accessToken").ok_or("accountError.loginRequired")?)
        .header("Accept", "application/json");
    for (header, value) in [
        ("X-Domain", text(auth, "domain")),
        ("X-User-Id", text(&saved.session["account"], "uid")),
        (
            "X-Enterprise-Id",
            text(&saved.session["account"], "enterpriseId"),
        ),
        (
            "X-Tenant-Id",
            text(&saved.session["account"], "enterpriseId"),
        ),
    ] {
        if let Some(value) = value {
            request = request.header(header, value);
        }
    }
    Ok(request)
}
async fn refresh_token(saved: &mut Saved) -> Result<(), String> {
    let auth = &saved.session["auth"];
    let refresh = text(auth, "refreshToken").ok_or("accountError.loginRequired")?;
    let body = response(
        authorized(
            &client()?,
            saved,
            &format!(
                "{}/v2/plugin/auth/token/refresh",
                saved.summary.edition.api()
            ),
        )?
        .header("X-Refresh-Token", refresh)
        .header("X-Auth-Refresh-Source", "plugin")
        .json(&json!({})),
    )
    .await?;
    if !success(&body) {
        return Err("accountError.loginRequired".into());
    }
    let update = normalize_auth(body["data"].clone());
    if text(&update, "accessToken").is_none() {
        return Err("accountError.authResponse".into());
    }
    if !saved
        .summary
        .edition
        .accepts_domain(text(&update, "domain").unwrap_or_default())
    {
        return Err("accountError.authResponse".into());
    }
    let target = saved.session["auth"]
        .as_object_mut()
        .ok_or("accountError.invalidAccount")?;
    target.extend(
        update
            .as_object()
            .ok_or("accountError.authResponse")?
            .clone(),
    );
    save(saved)
}
fn sync_current(saved: &mut Saved) -> Result<(), String> {
    let edition = saved.summary.edition;
    let Ok(session) = read(&edition.auth_path()?) else {
        return Ok(());
    };
    let Ok(current) = snapshot(edition, session) else {
        return Ok(());
    };
    if current.summary.id == saved.summary.id
        && text(&current.session["auth"], "accessToken").is_some()
        && credits::timestamp(current.session["auth"].get("expiresAt"))
            > credits::timestamp(saved.session["auth"].get("expiresAt"))
    {
        saved.session = current.session;
        save(saved)?;
    }
    Ok(())
}

async fn ensure_fresh(saved: &mut Saved) -> Result<(), String> {
    sync_current(saved)?;
    if credits::timestamp(saved.session["auth"].get("expiresAt"))
        .is_some_and(|t| t <= chrono::Utc::now().timestamp() + 60)
    {
        refresh_token(saved).await?;
    }
    Ok(())
}
pub async fn refresh(edition: Edition, id: &str) -> Result<Account, String> {
    let _guard = ACCOUNT_LOCK.lock().await;
    let mut saved = load(id, edition)?;
    refresh_saved(&mut saved, true).await
}

async fn refresh_saved(saved: &mut Saved, sync_checkin_status: bool) -> Result<Account, String> {
    ensure_fresh(saved).await?;
    let result = credits::fetch(saved).await;
    let quota = match result {
        Err(e) if e.starts_with("accountError.loginRequired") => {
            refresh_token(saved).await?;
            credits::fetch(saved).await?
        }
        other => other?,
    };
    saved.summary.remaining = Some(quota.remaining);
    saved.summary.total = Some(quota.total);
    saved.summary.base_remaining = quota.base_remaining;
    saved.summary.base_total = quota.base_total;
    saved.summary.base_reset_at = quota.base_reset_at;
    saved.summary.reward_remaining = quota.reward_remaining;
    saved.summary.reward_total = quota.reward_total;
    saved.summary.addon_remaining = quota.addon_remaining;
    saved.summary.expires_at = quota.expires_at;
    saved.summary.plan = quota.plan;
    if sync_checkin_status && saved.summary.edition == Edition::Cn {
        if let Ok(checked_in) = credits::checkin_status(saved).await {
            saved.summary.daily_claimed_at = checked_in.then(|| chrono::Utc::now().timestamp());
        }
    }
    saved.summary.active = read(&saved.summary.edition.auth_path()?)
        .ok()
        .and_then(|v| snapshot(saved.summary.edition, v).ok())
        .is_some_and(|v| v.summary.id == saved.summary.id);
    save(saved)?;
    Ok(saved.summary.clone())
}

pub async fn claim_daily(edition: Edition, id: &str) -> Result<Account, String> {
    if edition != Edition::Cn {
        return Err("accountError.claimUnavailable".into());
    }
    let _guard = ACCOUNT_LOCK.lock().await;
    let mut saved = load(id, edition)?;
    ensure_fresh(&mut saved).await?;
    if credits::checkin_status(&saved).await != Ok(true) {
        match credits::claim_daily(&saved).await {
            Err(error) if error.starts_with("accountError.loginRequired") => {
                refresh_token(&mut saved).await?;
                credits::claim_daily(&saved).await?;
            }
            result => result?,
        }
    }
    saved.summary.daily_claimed_at = Some(chrono::Utc::now().timestamp());
    save(&saved)?;
    Ok(refresh_saved(&mut saved, false)
        .await
        .unwrap_or_else(|_| saved.summary.clone()))
}
fn merge_session(mut current: Value, saved: &Saved) -> Result<Value, String> {
    if !current.is_object() {
        return Err("accountError.format".into());
    }
    let profile = saved.session["account"].clone();
    let uid = text(&profile, "uid").or_else(|| text(&profile, "id"));
    let mut all = current
        .get("allAccounts")
        .or_else(|| current.get("accounts"))
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    all.retain(|p| text(p, "uid").or_else(|| text(p, "id")) != uid);
    all.push(profile.clone());
    current["account"] = profile;
    current["auth"] = saved.session["auth"].clone();
    let now = chrono::Utc::now().timestamp();
    for (absolute, relative) in [
        ("expiresAt", "expiresIn"),
        ("refreshExpiresAt", "refreshExpiresIn"),
    ] {
        if let Some(expires) = credits::timestamp(current["auth"].get(absolute)) {
            current["auth"][relative] = json!((expires - now).max(0));
        }
    }
    current["accounts"] = json!(all);
    current["allAccounts"] = current["accounts"].clone();
    Ok(current)
}
pub async fn switch(edition: Edition, id: &str) -> Result<Account, String> {
    let _guard = ACCOUNT_LOCK.lock().await;
    let mut saved = load(id, edition)?;
    ensure_fresh(&mut saved).await?;
    log::info!("[WorkBuddy] Switching {}: closing client", edition.tool());
    close_app(edition).await?;
    log::info!("[WorkBuddy] Switching {}: client stopped", edition.tool());
    let path = edition.auth_path()?;
    let original = if path.exists() {
        read(&path)?
    } else {
        json!({})
    };
    // Preserve the last credentials written by the official client before replacing them.
    if let Ok(mut current) = snapshot(edition, original.clone()) {
        if let Ok(old) = load(&current.summary.id, edition) {
            current.summary = old.summary;
            // A newer plaintext credential from EchoBird must not be replaced by an older snapshot.
            let live_time = credits::timestamp(current.session["auth"].get("expiresAt"));
            let stored_time = credits::timestamp(old.session["auth"].get("expiresAt"));
            if live_time > stored_time {
                save(&current)?;
                if current.summary.id == id {
                    saved = current;
                }
            }
        }
    }
    let next = merge_session(original.clone(), &saved)?;
    if path.exists() {
        write(
            &store()?.join(format!("{}-auth.backup", edition.tool())),
            &original,
        )?;
    }
    let data_root = dirs::home_dir()
        .ok_or("accountError.home")?
        .join(format!(".{}", edition.platform()));
    history::apply(&path, &data_root, &original, &next)?;
    saved.summary.active = true;
    Ok(saved.summary)
}
#[cfg(windows)]
fn windows_close_script(name: &str) -> String {
    // Electron children can exit between any property read and close/kill call.
    // The final process check is authoritative; a stale process object isn't a failure.
    format!(
        r#"
$ErrorActionPreference='Stop'
$items=@(Get-Process -Name '{name}' -ErrorAction SilentlyContinue)
foreach($item in $items) {{ try {{ if($item.MainWindowHandle -ne 0) {{ [void]$item.CloseMainWindow() }} }} catch {{ }} }}
$deadline=(Get-Date).AddSeconds(8)
while((Get-Process -Name '{name}' -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) {{ Start-Sleep -Milliseconds 200 }}
foreach($item in $items) {{ try {{ if(-not $item.HasExited) {{ $item.Kill() }} }} catch {{ }} }}
$deadline=(Get-Date).AddSeconds(10)
while(Get-Process -Name '{name}' -ErrorAction SilentlyContinue) {{
    if((Get-Date) -ge $deadline) {{ exit 1 }}
    Start-Sleep -Milliseconds 200
}}
exit 0
"#
    )
}

async fn close_app(edition: Edition) -> Result<(), String> {
    #[cfg(windows)]
    {
        let name = match edition {
            Edition::Cn => "WorkBuddy",
            Edition::Ai => "WorkBuddyAI",
        };
        let script = windows_close_script(name);
        let status = crate::utils::process::async_command("powershell")
            .args(["-NoProfile", "-NonInteractive", "-Command", &script])
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .status()
            .await
            .map_err(|_| "accountError.failed")?;
        if !status.success() {
            log::warn!("[WorkBuddy] Client shutdown failed: {name}, status={status}");
            return Err(format!("accountError.failed|Close {name} and try again."));
        }
        Ok(())
    }
    #[cfg(target_os = "macos")]
    {
        let bundle = match edition {
            Edition::Cn => "com.tencent.workbuddy.mac",
            Edition::Ai => "com.workbuddy.workbuddy-ai",
        };
        let script = format!("tell application \"System Events\"\nif exists (processes whose bundle identifier is \"{bundle}\") then\ntell application id \"{bundle}\" to quit\nrepeat 100 times\nif not (exists (processes whose bundle identifier is \"{bundle}\")) then return\ndelay 0.2\nend repeat\nerror \"WorkBuddy is still running\"\nend if\nend tell");
        let status = crate::utils::process::async_command("osascript")
            .args(["-e", &script])
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .status()
            .await
            .map_err(|_| "accountError.failed")?;
        if !status.success() {
            return Err("accountError.failed".into());
        }
        Ok(())
    }
    #[cfg(not(any(windows, target_os = "macos")))]
    {
        let _ = edition;
        Err("accountError.unavailable".into())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn session() -> Value {
        json!({"account":{"uid":"u1","nickname":"Name"},"auth":{"accessToken":"token","domain":"www.codebuddy.cn"}})
    }
    #[test]
    fn saved_accounts_without_plan_remain_readable() {
        let mut value = serde_json::to_value(snapshot(Edition::Cn, session()).unwrap()).unwrap();
        value["summary"].as_object_mut().unwrap().remove("plan");
        value["summary"]
            .as_object_mut()
            .unwrap()
            .remove("baseRemaining");
        for key in [
            "baseTotal",
            "baseResetAt",
            "rewardRemaining",
            "rewardTotal",
            "addonRemaining",
        ] {
            value["summary"].as_object_mut().unwrap().remove(key);
        }
        value["summary"]
            .as_object_mut()
            .unwrap()
            .remove("dailyClaimedAt");
        let saved: Saved = serde_json::from_value(value).unwrap();
        assert_eq!(saved.summary.plan, None);
        assert_eq!(saved.summary.base_remaining, None);
        assert_eq!(saved.summary.reward_remaining, None);
        assert_eq!(saved.summary.addon_remaining, None);
        assert_eq!(saved.summary.daily_claimed_at, None);
    }
    #[tokio::test]
    async fn international_daily_claim_is_rejected_before_loading_credentials() {
        assert_eq!(
            claim_daily(Edition::Ai, "invalid-id").await.unwrap_err(),
            "accountError.claimUnavailable"
        );
    }
    #[tokio::test]
    async fn account_list_does_not_wait_for_quota_refresh_lock() {
        let dir = std::env::temp_dir().join(uuid::Uuid::new_v4().to_string());
        let saved = snapshot(Edition::Cn, session()).unwrap();
        write(&account_path(&dir, &saved.summary.id).unwrap(), &saved).unwrap();
        let auth_path = dir.join("auth.info");
        write(&auth_path, &session()).unwrap();
        let _refresh_guard = ACCOUNT_LOCK.lock().await;
        let result = tokio::time::timeout(
            Duration::from_millis(200),
            list_from_paths(Edition::Cn, &dir, &auth_path),
        )
        .await;
        fs::remove_dir_all(dir).unwrap();
        let accounts = result
            .expect("local account listing must not wait for network operations")
            .unwrap();
        assert_eq!(accounts.len(), 1);
        assert_eq!(accounts[0].id, saved.summary.id);
        assert!(accounts[0].active);
    }
    #[test]
    fn editions_and_enterprises_have_distinct_identity() {
        let cn = snapshot(Edition::Cn, session()).unwrap();
        let mut ai = session();
        ai["auth"]["domain"] = json!("www.workbuddy.ai");
        assert_ne!(cn.summary.id, snapshot(Edition::Ai, ai).unwrap().summary.id);
        assert!(snapshot(Edition::Ai, session()).is_err());
        let mut enterprise = session();
        enterprise["account"]["enterpriseId"] = json!("org");
        assert_ne!(
            cn.summary.id,
            snapshot(Edition::Cn, enterprise).unwrap().summary.id
        );
        assert!(!Edition::Ai.accepts_domain("www.workbuddy.ai.evil.test"));
    }
    #[test]
    fn merge_preserves_encrypted_credentials_and_unrelated_fields() {
        let mut source = session();
        source["auth"]["accessToken"] = json!({"$wbEncrypted":true,"envelope":"cipher"});
        let saved = snapshot(Edition::Cn, source.clone()).unwrap();
        let merged = merge_session(
            json!({"extra":42,"allAccounts":[{"uid":"other"},{"uid":"u1","nickname":"old"}]}),
            &saved,
        )
        .unwrap();
        assert_eq!(merged["extra"], 42);
        assert_eq!(merged["auth"], source["auth"]);
        assert_eq!(merged["allAccounts"].as_array().unwrap().len(), 2);
        assert!(!serde_json::to_string(&saved.summary)
            .unwrap()
            .contains("cipher"));
    }
    #[test]
    fn rejects_empty_credentials_and_path_traversal() {
        let mut value = session();
        value["auth"]["accessToken"] = json!("");
        assert!(snapshot(Edition::Cn, value).is_err());
        assert!(account_path(Path::new("store"), "../auth").is_err());
    }
    #[tokio::test]
    async fn expired_and_cancelled_logins_cannot_be_polled() {
        let id = uuid::Uuid::new_v4().to_string();
        LOGINS.get_or_init(Mutex::default).lock().unwrap().insert(
            id.clone(),
            Login {
                edition: Edition::Ai,
                state: "expired-state".into(),
                expires: 1,
            },
        );
        assert_eq!(poll_login(&id).await.unwrap_err(), "accountError.expired");
        assert_eq!(poll_login(&id).await.unwrap_err(), "accountError.cancelled");
        cancel_login(&id).unwrap();
    }
    #[test]
    fn writing_an_account_recalculates_remaining_token_lifetime() {
        let mut value = session();
        value["auth"]["expiresAt"] = json!(1000);
        value["auth"]["expiresIn"] = json!(3600);
        let saved = snapshot(Edition::Cn, value).unwrap();
        let merged = merge_session(json!({}), &saved).unwrap();
        assert_eq!(merged["auth"]["expiresIn"], 0);
        assert_eq!(merged["auth"]["accessToken"], "token");
    }
    #[cfg(windows)]
    fn run_close_fixture(phase: &str, exits: bool) -> bool {
        // Fake process objects reproduce OS exit races without touching real applications.
        let fixture = format!(
            r#"
$global:fixture = [pscustomobject]@{{ MainWindowHandle = {window}; HasExited = $false }}
$global:fixture | Add-Member ScriptMethod CloseMainWindow {{ $this.HasExited = $true; throw 'Process already exited' }}
$global:fixture | Add-Member ScriptMethod Kill {{ $this.HasExited = ${exits}; throw 'Process already exited or access denied' }}
function Get-Process {{ if (-not $global:fixture.HasExited) {{ $global:fixture }} }}
"#,
            window = if phase == "close" { 1 } else { 0 },
            exits = if exits { "true" } else { "false" }
        );
        let script = windows_close_script("EchoBirdTestOnly")
            .replace("AddSeconds(8)", "AddSeconds(0)")
            .replace("AddSeconds(10)", "AddSeconds(0)");
        crate::utils::process::command("powershell")
            .args([
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                &format!("{fixture}\n{script}"),
            ])
            .output()
            .unwrap()
            .status
            .success()
    }
    #[cfg(windows)]
    #[test]
    fn closing_a_process_that_exits_during_close_is_successful() {
        assert!(run_close_fixture("close", true));
    }
    #[cfg(windows)]
    #[test]
    fn killing_a_process_that_exits_concurrently_is_successful() {
        assert!(run_close_fixture("kill", true));
    }
    #[cfg(windows)]
    #[test]
    fn a_process_that_remains_running_still_blocks_switching() {
        assert!(!run_close_fixture("kill", false));
    }
    #[test]
    fn atomic_write_replaces_existing_file() {
        let dir = std::env::temp_dir().join(uuid::Uuid::new_v4().to_string());
        let path = dir.join("auth.info");
        write(&path, &session()).unwrap();
        write(&path, &json!({"updated":true})).unwrap();
        assert_eq!(read(&path).unwrap(), json!({"updated":true}));
        fs::remove_dir_all(dir).unwrap();
    }
}