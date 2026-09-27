//! EchoBird-owned Grok Build OAuth account snapshots.
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    fs,
    path::PathBuf,
    sync::{Mutex, OnceLock},
};

static PENDING: OnceLock<Mutex<Option<Pending>>> = OnceLock::new();
const LOGIN_TIMEOUT: i64 = 60;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Account {
    pub id: String,
    pub email: String,
    pub plan: Option<String>,
    pub active: bool,
}
#[derive(Clone, Serialize, Deserialize)]
struct Saved {
    summary: Account,
    key: String,
    auth: Value,
}
struct Pending {
    id: String,
    before: Value,
    expires: i64,
    child: Option<std::process::Child>,
}

fn home() -> Result<PathBuf, String> {
    dirs::home_dir().ok_or("accountError.home".into())
}
fn auth_path() -> Result<PathBuf, String> {
    Ok(home()?.join(".grok/auth.json"))
}
fn store() -> Result<PathBuf, String> {
    Ok(home()?.join(".echobird/grok-accounts"))
}
fn read_auth() -> Result<Value, String> {
    serde_json::from_slice(&fs::read(auth_path()?).map_err(|_| "accountError.read")?)
        .map_err(|_| "accountError.format".into())
}
fn write_auth(value: &Value) -> Result<(), String> {
    fs::write(
        auth_path()?,
        serde_json::to_vec_pretty(value).map_err(|_| "accountError.format")?,
    )
    .map_err(|_| "accountError.write".into())
}
fn saved_path(id: &str) -> Result<PathBuf, String> {
    if id.len() != 64 || !id.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err("accountError.invalidAccount".into());
    }
    Ok(store()?.join(format!("{id}.json")))
}
fn summary(key: &str, auth: &Value, active: bool) -> Result<Account, String> {
    let row = auth.get(key).ok_or("accountError.invalidAccount")?;
    let email = row
        .get("email")
        .and_then(Value::as_str)
        .unwrap_or("Grok account")
        .to_string();
    let id = format!("{:x}", Sha256::digest(key));
    Ok(Account {
        id,
        email,
        plan: None,
        active,
    })
}
fn save(key: &str, auth: &Value) -> Result<Account, String> {
    let a = summary(key, auth, false)?;
    fs::create_dir_all(store()?).map_err(|_| "accountError.write")?;
    let saved = Saved {
        summary: a.clone(),
        key: key.into(),
        auth: auth[key].clone(),
    };
    fs::write(
        saved_path(&a.id)?,
        serde_json::to_vec_pretty(&saved).map_err(|_| "accountError.format")?,
    )
    .map_err(|_| "accountError.write")?;
    Ok(a)
}

pub async fn start_login() -> Result<(String, i64), String> {
    if let Some(previous) = PENDING
        .get_or_init(|| Mutex::new(None))
        .lock()
        .map_err(|_| "accountError.busy")?
        .take()
    {
        if let Some(mut child) = previous.child {
            let _ = child.kill();
        }
    }
    let before = read_auth().unwrap_or_else(|_| serde_json::json!({}));
    let exe = home()?.join(".grok/bin/grok.exe");
    let child = std::process::Command::new(exe)
        .args(["login", "--oauth"])
        .spawn()
        .map_err(|_| "accountError.auth")?;
    let id = uuid::Uuid::new_v4().to_string();
    let expires = chrono::Utc::now().timestamp() + LOGIN_TIMEOUT;
    *PENDING
        .get_or_init(|| Mutex::new(None))
        .lock()
        .map_err(|_| "accountError.busy")? = Some(Pending {
        id: id.clone(),
        before,
        expires,
        child: Some(child),
    });
    Ok((id, expires))
}
pub async fn poll_login(id: &str) -> Result<Option<Account>, String> {
    let mut guard = PENDING
        .get_or_init(|| Mutex::new(None))
        .lock()
        .map_err(|_| "accountError.busy")?;
    let p = guard
        .as_mut()
        .filter(|p| p.id == id)
        .ok_or("accountError.cancelled")?;
    if chrono::Utc::now().timestamp() >= p.expires {
        if let Some(mut child) = p.child.take() {
            let _ = child.kill();
        }
        *guard = None;
        return Err("accountError.expired".into());
    }
    let now = read_auth().unwrap_or_else(|_| serde_json::json!({}));
    let obj = now.as_object().ok_or("accountError.format")?;
    let before = p.before.as_object().cloned().unwrap_or_default();
    for (key, value) in obj {
        if before.get(key) != Some(value) {
            let a = save(key, &now)?;
            *guard = None;
            return Ok(Some(a));
        }
    }
    Ok(None)
}
pub fn cancel_login(id: &str) -> Result<(), String> {
    let mut guard = PENDING
        .get_or_init(|| Mutex::new(None))
        .lock()
        .map_err(|_| "accountError.busy")?;
    if guard.as_ref().is_some_and(|p| p.id == id) {
        if let Some(p) = guard.take() {
            if let Some(mut c) = p.child {
                let _ = c.kill();
            }
        }
    }
    Ok(())
}
pub fn list() -> Result<Vec<Account>, String> {
    let dir = store()?;
    if !dir.exists() {
        return Ok(Vec::new());
    }
    let mut out = Vec::new();
    let current = read_auth().unwrap_or_else(|_| serde_json::json!({}));
    let active_plan = home()
        .ok()
        .and_then(|h| fs::read_to_string(h.join(".grok/settings_cache.json")).ok())
        .and_then(|s| serde_json::from_str::<Value>(&s).ok())
        .and_then(|v| serde_json::from_str::<Value>(v.get("payload")?.as_str()?).ok())
        .and_then(|v| {
            v["settings"]["subscription_tier_display"]
                .as_str()
                .map(String::from)
        });
    for e in fs::read_dir(dir).map_err(|_| "accountError.read")? {
        let p = e.map_err(|_| "accountError.read")?.path();
        if p.extension().and_then(|x| x.to_str()) != Some("json") {
            continue;
        }
        let saved: Saved = serde_json::from_slice(&fs::read(&p).map_err(|_| "accountError.read")?)
            .map_err(|_| "accountError.format")?;
        let active = current.get(&saved.key).is_some_and(|v| v == &saved.auth);
        let mut a = saved.summary;
        a.active = active;
        if a.active {
            a.plan = active_plan.clone();
        }
        out.push(a)
    }
    out.sort_by(|a, b| a.email.cmp(&b.email));
    Ok(out)
}
pub async fn switch(id: &str) -> Result<Account, String> {
    let p = saved_path(id)?;
    let saved: Saved = serde_json::from_slice(&fs::read(p).map_err(|_| "accountError.read")?)
        .map_err(|_| "accountError.format")?;
    let mut auth = serde_json::Map::new();
    auth.insert(saved.key.clone(), saved.auth.clone());
    write_auth(&Value::Object(auth))?;
    let mut a = saved.summary;
    a.active = true;
    Ok(a)
}
pub async fn delete(id: &str) -> Result<(), String> {
    fs::remove_file(saved_path(id)?).map_err(|_| "accountError.write".into())
}

pub async fn refresh(id: &str) -> Result<Account, String> {
    list()?
        .into_iter()
        .find(|account| account.id == id)
        .ok_or("accountError.invalidAccount".into())
}