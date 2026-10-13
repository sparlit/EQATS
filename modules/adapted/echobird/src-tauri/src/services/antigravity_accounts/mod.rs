mod native;
mod oauth;
mod quota;

use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use quota::ModelQuota;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, path::PathBuf};

static ACCOUNT_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Account {
    pub id: String,
    pub email: String,
    pub active: bool,
    pub plan: Option<String>,
    pub quotas: Vec<ModelQuota>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LoginStart {
    pub login_id: String,
    pub verification_uri: String,
    pub expires_at: i64,
}

#[derive(Clone, Serialize, Deserialize)]
struct Saved {
    email: String,
    credential: String,
    #[serde(default)]
    plan: Option<String>,
    #[serde(default)]
    quotas: Vec<ModelQuota>,
}

fn store_path() -> Result<PathBuf, String> {
    Ok(dirs::home_dir()
        .ok_or("accountError.home")?
        .join(".echobird/antigravity-accounts.json"))
}

fn load() -> Result<BTreeMap<String, Saved>, String> {
    let path = store_path()?;
    if !path.exists() {
        return Ok(BTreeMap::new());
    }
    super::cursor_auth::read(&path)
}

fn save(accounts: &BTreeMap<String, Saved>) -> Result<(), String> {
    super::cursor_auth::write(&store_path()?, accounts)
}

fn identity(raw: &str) -> Result<(String, String), String> {
    let credential: Value = serde_json::from_str(raw).map_err(|_| "accountError.format")?;
    if credential["token"]["refresh_token"]
        .as_str()
        .filter(|s| !s.is_empty())
        .is_none()
    {
        return Err("accountError.invalidAccount".into());
    }
    let token = credential["id_token"]
        .as_str()
        .ok_or("accountError.invalidAccount")?;
    let segment = token
        .split('.')
        .nth(1)
        .ok_or("accountError.invalidAccount")?;
    let decoded = URL_SAFE_NO_PAD
        .decode(segment.trim_end_matches('='))
        .map_err(|_| "accountError.invalidAccount")?;
    let claims: Value =
        serde_json::from_slice(&decoded).map_err(|_| "accountError.invalidAccount")?;
    let subject = claims["sub"]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or("accountError.invalidAccount")?;
    let email = claims["email"]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or("accountError.invalidAccount")?;
    Ok((format!("{:x}", Sha256::digest(subject)), email.to_owned()))
}

fn protect(value: &str) -> Result<String, String> {
    let encrypted = super::model_manager::encrypt_key_for_storage(value);
    if !encrypted.starts_with("enc:v1:") {
        return Err("accountError.keychain".into());
    }
    Ok(encrypted)
}

fn unprotect(value: &str) -> Result<String, String> {
    if !value.starts_with("enc:v1:") {
        return Err("accountError.invalidAccount".into());
    }
    let plain = super::model_manager::decrypt_key_for_use(value);
    if plain.is_empty() {
        return Err("accountError.keychain".into());
    }
    Ok(plain)
}

fn summary(id: &str, saved: &Saved, active: Option<&str>) -> Account {
    Account {
        id: id.to_owned(),
        email: saved.email.clone(),
        active: active == Some(id),
        plan: saved.plan.clone(),
        quotas: saved.quotas.clone(),
    }
}

fn capture(
    raw: &str,
    accounts: &mut BTreeMap<String, Saved>,
    active: bool,
) -> Result<Account, String> {
    let (id, email) = identity(raw)?;
    let previous = accounts.get(&id);
    let saved = Saved {
        email,
        credential: protect(raw)?,
        plan: previous.and_then(|s| s.plan.clone()),
        quotas: previous.map(|s| s.quotas.clone()).unwrap_or_default(),
    };
    let account = summary(&id, &saved, active.then_some(id.as_str()));
    accounts.insert(id, saved);
    save(accounts)?;
    Ok(account)
}

pub async fn list() -> Result<Vec<Account>, String> {
    let _guard = ACCOUNT_LOCK.lock().await;
    let accounts = load()?;
    let current = native::read()?;
    let active = current.as_deref().map(identity).transpose()?.map(|v| v.0);
    let rows = accounts
        .iter()
        .map(|(id, saved)| summary(id, saved, active.as_deref()))
        .collect::<Vec<_>>();
    Ok(rows)
}

pub async fn start_login() -> Result<LoginStart, String> {
    oauth::start().await
}

pub async fn poll_login(login_id: &str) -> Result<Option<Account>, String> {
    let _guard = ACCOUNT_LOCK.lock().await;
    let Some(raw) = oauth::poll(login_id)? else {
        return Ok(None);
    };
    let mut accounts = load()?;
    let result = capture(&raw, &mut accounts, false)?;
    cancel_login(login_id)?;
    Ok(Some(result))
}

pub fn cancel_login(login_id: &str) -> Result<(), String> {
    oauth::cancel(login_id)
}

pub async fn delete(id: &str) -> Result<(), String> {
    let _guard = ACCOUNT_LOCK.lock().await;
    let mut accounts = load()?;
    accounts.remove(id);
    save(&accounts)
}

async fn ensure_cli_closed() -> Result<(), String> {
    #[cfg(windows)]
    {
        let result = crate::utils::process::async_command("tasklist")
            .args(["/FI", "IMAGENAME eq agy.exe", "/FO", "CSV", "/NH"])
            .output()
            .await
            .map_err(|_| "accountError.closeClient")?;
        if !result.status.success() {
            return Err("accountError.closeClient".into());
        }
        if String::from_utf8_lossy(&result.stdout)
            .to_ascii_lowercase()
            .contains("\"agy.exe\"")
        {
            return Err("accountError.closeClient".into());
        }
    }
    #[cfg(unix)]
    {
        if crate::utils::process::async_command("pgrep")
            .args(["-x", "agy"])
            .status()
            .await
            .is_ok_and(|status| status.success())
        {
            return Err("accountError.closeClient".into());
        }
    }
    Ok(())
}

async fn close_desktop() -> Result<(), String> {
    #[cfg(windows)]
    {
        super::cursor_auth::close_windows_client("Antigravity", false).await
    }
    #[cfg(unix)]
    {
        super::cursor_auth::close_client("antigravitydesktop", "Antigravity").await
    }
}

pub async fn switch(id: &str) -> Result<Account, String> {
    let _guard = ACCOUNT_LOCK.lock().await;
    let mut accounts = load()?;
    let saved = accounts.get(id).ok_or("accountError.invalidAccount")?;
    let mut raw = unprotect(&saved.credential)?;
    if identity(&raw)?.0 != id {
        return Err("accountError.invalidAccount".into());
    }
    let mut document: Value = serde_json::from_str(&raw).map_err(|_| "accountError.format")?;
    quota::refresh_access(&mut document).await?;
    raw = serde_json::to_string(&document).map_err(|_| "accountError.format")?;
    if identity(&raw)?.0 != id {
        return Err("accountError.invalidAccount".into());
    }
    let protected = protect(&raw)?;
    let previous = native::read()?;
    if let Some(current) = previous.as_deref() {
        let current_id = identity(current)?.0;
        if !accounts.contains_key(&current_id) {
            capture(current, &mut accounts, true)?;
        }
    }
    ensure_cli_closed().await?;
    close_desktop().await?;
    native::write(&raw)?;
    let verified = native::read()
        .and_then(|value| value.as_deref().map(identity).transpose())
        .map(|value| value.map(|v| v.0));
    if !matches!(verified, Ok(Some(ref value)) if value == id) {
        restore_native(previous.as_deref())?;
        return Err("accountError.write".into());
    }
    let account = accounts.get_mut(id).ok_or("accountError.invalidAccount")?;
    account.credential = protected;
    let result = summary(id, account, Some(id));
    if let Err(error) = save(&accounts) {
        restore_native(previous.as_deref())?;
        return Err(error);
    }
    Ok(result)
}

fn restore_native(previous: Option<&str>) -> Result<(), String> {
    match previous {
        Some(value) => native::write(value),
        None => native::delete(),
    }
}

pub async fn refresh(id: &str) -> Result<Account, String> {
    let _guard = ACCOUNT_LOCK.lock().await;
    let mut accounts = load()?;
    let saved = accounts.get_mut(id).ok_or("accountError.invalidAccount")?;
    let mut document: Value =
        serde_json::from_str(&unprotect(&saved.credential)?).map_err(|_| "accountError.format")?;
    if identity(&document.to_string())?.0 != id {
        return Err("accountError.invalidAccount".into());
    }
    quota::refresh_access(&mut document).await?;
    if identity(&document.to_string())?.0 != id {
        return Err("accountError.invalidAccount".into());
    }
    let (plan, quotas) = quota::fetch(&document).await?;
    saved.credential = protect(&document.to_string())?;
    saved.plan = plan;
    saved.quotas = quotas;
    let active = native::read()?
        .as_deref()
        .map(identity)
        .transpose()?
        .map(|v| v.0);
    let result = summary(id, saved, active.as_deref());
    save(&accounts)?;
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::identity;

    #[test]
    fn parses_native_identity_without_using_email_as_key() {
        let claims = base64::Engine::encode(
            &base64::engine::general_purpose::URL_SAFE_NO_PAD,
            br#"{"sub":"stable-id","email":"a@example.com"}"#,
        );
        let raw = serde_json::json!({"id_token":format!("x.{claims}.y"),"token":{"refresh_token":"refresh"}}).to_string();
        let (id, email) = identity(&raw).unwrap();
        assert_eq!(email, "a@example.com");
        assert_ne!(id, email);
    }
}