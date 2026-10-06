//! EchoBird-owned Grok Build OAuth account snapshots.
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    fs,
    path::{Path, PathBuf},
    sync::{Mutex, OnceLock},
};

static PENDING: OnceLock<Mutex<Option<Pending>>> = OnceLock::new();
static ACCOUNT_LOCK: Mutex<()> = Mutex::new(());
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
    dir: PathBuf,
    expires: i64,
    child: Option<std::process::Child>,
}
impl Drop for Pending {
    fn drop(&mut self) {
        if let Some(mut child) = self.child.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
        let _ = fs::remove_dir_all(&self.dir);
    }
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
fn apply_native(dir: &Path, saved: &Saved) -> Result<(), String> {
    // Grok's local session IDs and logs are shared across logins. Only replace auth.
    let mut auth = serde_json::Map::new();
    auth.insert(saved.key.clone(), saved.auth.clone());
    // The old account's subscription cache must not be shown for the new login.
    match fs::remove_file(dir.join("settings_cache.json")) {
        Ok(()) => {}
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
        Err(_) => return Err("accountError.write".into()),
    }
    super::cursor_auth::write(&dir.join("auth.json"), &Value::Object(auth))
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
    let user = row["user_id"]
        .as_str()
        .filter(|s| !s.is_empty())
        .or_else(|| row["email"].as_str().filter(|s| !s.is_empty()))
        .ok_or("accountError.invalidAccount")?;
    let id = format!("{:x}", Sha256::digest(format!("{key}\0{user}")));
    Ok(Account {
        id,
        email,
        plan: None,
        active,
    })
}
fn save(key: &str, auth: &Value) -> Result<Account, String> {
    let _guard = ACCOUNT_LOCK.lock().map_err(|_| "accountError.busy")?;
    save_at(&store()?, key, auth)
}
fn save_at(dir: &std::path::Path, key: &str, auth: &Value) -> Result<Account, String> {
    let mut a = summary(key, auth, false)?;
    // Keep existing account IDs stable while separating users on the same issuer.
    let legacy_id = format!("{:x}", Sha256::digest(key));
    let legacy_path = dir.join(format!("{legacy_id}.json"));
    if legacy_path.exists() {
        let legacy: Saved = super::cursor_auth::read(&legacy_path)?;
        let legacy_auth = serde_json::json!({legacy.key.clone(): legacy.auth});
        if summary(&legacy.key, &legacy_auth, false)?.id == a.id {
            a.id = legacy_id;
        }
    }
    let saved = Saved {
        summary: a.clone(),
        key: key.into(),
        auth: auth[key].clone(),
    };
    super::cursor_auth::write(&dir.join(format!("{}.json", a.id)), &saved)?;
    Ok(a)
}
fn sync_native(saved: &mut Saved, current: &Value) -> Result<bool, String> {
    if current.get(&saved.key).is_none() {
        return Ok(false);
    }
    let snapshot = serde_json::json!({saved.key.clone(): saved.auth});
    let active =
        summary(&saved.key, current, false)?.id == summary(&saved.key, &snapshot, false)?.id;
    if active {
        saved.auth = current[&saved.key].clone();
    }
    Ok(active)
}

pub async fn start_login() -> Result<(String, i64), String> {
    let mut guard = PENDING
        .get_or_init(|| Mutex::new(None))
        .lock()
        .map_err(|_| "accountError.busy")?;
    drop(guard.take());
    let exe =
        super::tool_manager::get_tool_exe_path("grok").ok_or("accountError.initializeClient")?;
    let id = uuid::Uuid::new_v4().to_string();
    let expires = chrono::Utc::now().timestamp() + LOGIN_TIMEOUT;
    let dir = home()?.join(".echobird/grok-logins").join(&id);
    fs::create_dir_all(&dir).map_err(|_| "accountError.write")?;
    let mut pending = Pending {
        id: id.clone(),
        dir,
        expires,
        child: None,
    };
    // Adding an account must not replace the CLI's current login.
    let mut command = crate::utils::process::command(exe);
    command
        .args(["login", "--oauth"])
        .env("GROK_HOME", &pending.dir);

    pending.child = Some(command.spawn().map_err(|_| "accountError.auth")?);
    *guard = Some(pending);
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
        *guard = None;
        return Err("accountError.expired".into());
    }
    let now = match fs::read(p.dir.join("auth.json")) {
        Ok(bytes) => match serde_json::from_slice::<Value>(&bytes) {
            Ok(value) => value,
            Err(_) => return Ok(None),
        },
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err("accountError.read".into()),
    };
    let obj = now.as_object().ok_or("accountError.format")?;
    if let Some(key) = obj.keys().next() {
        let a = save(key, &now)?;
        *guard = None;
        return Ok(Some(a));
    }
    Ok(None)
}
pub fn cancel_login(id: &str) -> Result<(), String> {
    let mut guard = PENDING
        .get_or_init(|| Mutex::new(None))
        .lock()
        .map_err(|_| "accountError.busy")?;
    if guard.as_ref().is_some_and(|p| p.id == id) {
        *guard = None;
    }
    Ok(())
}
pub fn list() -> Result<Vec<Account>, String> {
    let _guard = ACCOUNT_LOCK.lock().map_err(|_| "accountError.busy")?;
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
        let mut saved: Saved =
            serde_json::from_slice(&fs::read(&p).map_err(|_| "accountError.read")?)
                .map_err(|_| "accountError.format")?;
        let active = sync_native(&mut saved, &current)?;
        if active {
            super::cursor_auth::write(&p, &saved)?;
        }
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
    let _guard = ACCOUNT_LOCK.lock().map_err(|_| "accountError.busy")?;
    let p = saved_path(id)?;
    let mut saved: Saved = serde_json::from_slice(&fs::read(&p).map_err(|_| "accountError.read")?)
        .map_err(|_| "accountError.format")?;
    if let Ok(current) = read_auth() {
        if sync_native(&mut saved, &current)? {
            super::cursor_auth::write(&p, &saved)?;
        }
    }
    apply_native(&home()?.join(".grok"), &saved)?;
    let mut a = saved.summary;
    a.active = true;
    Ok(a)
}
pub async fn delete(id: &str) -> Result<(), String> {
    let _guard = ACCOUNT_LOCK.lock().map_err(|_| "accountError.busy")?;
    fs::remove_file(saved_path(id)?).map_err(|_| "accountError.write".into())
}

pub async fn refresh(id: &str) -> Result<Account, String> {
    list()?
        .into_iter()
        .find(|account| account.id == id)
        .ok_or("accountError.invalidAccount".into())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn switching_accounts_keeps_original_local_sessions_and_missing_history() {
        let dir = std::env::temp_dir().join(format!("grok-history-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&dir).unwrap();
        let login = |user: &str| {
            let key = "https://auth.x.ai";
            let auth = json!({"user_id":user,"email":format!("{user}@example.test"),"access_token":format!("token-{user}")});
            Saved {
                summary: summary(key, &json!({key:auth}), true).unwrap(),
                key: key.into(),
                auth,
            }
        };
        let a = login("a");
        let b = login("b");
        apply_native(&dir, &a).unwrap();
        assert!(!dir.join("sessions").exists());
        let mut originals = Vec::new();
        for id in ["a-session", "b-session"] {
            let session = dir.join("sessions/workspace").join(id);
            fs::create_dir_all(&session).unwrap();
            for (name, value) in [
                (
                    "summary.json",
                    json!({"info":{"id":id,"cwd":"/workspace"},"session_summary":id}),
                ),
                (
                    "chat_history.jsonl",
                    json!({"role":"assistant","content":"original tool result"}),
                ),
            ] {
                let path = session.join(name);
                fs::write(&path, value.to_string()).unwrap();
                originals.push((path.clone(), fs::read(path).unwrap()));
            }
        }
        for saved in [&b, &b, &a] {
            fs::write(dir.join("settings_cache.json"), "old-plan").unwrap();
            apply_native(&dir, saved).unwrap();
            let auth: Value =
                serde_json::from_slice(&fs::read(dir.join("auth.json")).unwrap()).unwrap();
            assert_eq!(
                summary(&saved.key, &auth, true).unwrap().id,
                saved.summary.id
            );
            assert!(!dir.join("settings_cache.json").exists());
            for (path, bytes) in &originals {
                assert_eq!(&fs::read(path).unwrap(), bytes);
            }
        }
        // A reported write failure must leave both accounts' original history intact.
        fs::create_dir(dir.join("settings_cache.json")).unwrap();
        assert!(apply_native(&dir, &b).is_err());
        for (path, bytes) in &originals {
            assert_eq!(&fs::read(path).unwrap(), bytes);
        }
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn users_on_the_same_issuer_have_independent_snapshots_and_legacy_ids_survive() {
        let dir = std::env::temp_dir().join(format!("echobird-grok-{}", uuid::Uuid::new_v4()));
        let issuer = "https://auth.example.test";
        let a = json!({issuer:{"user_id":"a", "email":"a@example.test", "key":"token-a"}});
        let b = json!({issuer:{"user_id":"b", "email":"b@example.test", "key":"token-b"}});
        let first = save_at(&dir, issuer, &a).unwrap();
        let second = save_at(&dir, issuer, &b).unwrap();
        assert_ne!(first.id, second.id);
        assert!(dir.join(format!("{}.json", first.id)).exists());
        assert!(dir.join(format!("{}.json", second.id)).exists());
        let legacy_id = format!("{:x}", Sha256::digest(issuer));
        fs::rename(
            dir.join(format!("{}.json", first.id)),
            dir.join(format!("{legacy_id}.json")),
        )
        .unwrap();
        let mut rotated = a.clone();
        rotated[issuer]["key"] = json!("rotated-token");
        assert_eq!(save_at(&dir, issuer, &rotated).unwrap().id, legacy_id);
        assert_eq!(save_at(&dir, issuer, &b).unwrap().id, second.id);
        let legacy: Saved =
            super::super::cursor_auth::read(&dir.join(format!("{legacy_id}.json"))).unwrap();
        assert_eq!(legacy.auth["key"], "rotated-token");
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn pending_login_cleanup_only_removes_its_isolated_directory() {
        let root = std::env::temp_dir().join(format!("echobird-grok-{}", uuid::Uuid::new_v4()));
        let dir = root.join("login");
        fs::create_dir_all(&dir).unwrap();
        fs::write(root.join("auth.json"), "existing native login").unwrap();
        fs::write(dir.join("auth.json"), "temporary login").unwrap();
        drop(Pending {
            id: "test".into(),
            dir: dir.clone(),
            expires: 0,
            child: None,
        });
        assert!(!dir.exists());
        assert_eq!(
            fs::read_to_string(root.join("auth.json")).unwrap(),
            "existing native login"
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn token_rotation_keeps_current_identity_without_overwriting_other_accounts() {
        let issuer = "https://auth.example.test";
        let original = json!({issuer:{"user_id":"a", "email":"a@example.test", "key":"old"}});
        let mut saved = Saved {
            summary: summary(issuer, &original, false).unwrap(),
            key: issuer.into(),
            auth: original[issuer].clone(),
        };
        let mut rotated = original.clone();
        rotated[issuer]["key"] = json!("new");
        assert!(sync_native(&mut saved, &rotated).unwrap());
        assert_eq!(saved.auth["key"], "new");
        rotated[issuer]["user_id"] = json!("b");
        rotated[issuer]["key"] = json!("other-user");
        assert!(!sync_native(&mut saved, &rotated).unwrap());
        assert_eq!(saved.auth["key"], "new");
    }
}