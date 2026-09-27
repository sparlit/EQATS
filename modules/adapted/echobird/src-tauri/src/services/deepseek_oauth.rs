//! Official browser authorization with PKCE and a bounded loopback callback.
use super::deepseek_accounts::{self as accounts, Account, Saved, ORIGIN};
use axum::{
    extract::{Query, State},
    http::StatusCode,
    response::{IntoResponse, Redirect, Response},
    routing::get,
    Router,
};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use serde::Serialize;
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    sync::{Arc, Mutex},
    time::Duration,
};
use tokio_util::sync::CancellationToken;

static PENDING: Mutex<Option<Arc<Attempt>>> = Mutex::new(None);
static START_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());
const LOGIN_TIMEOUT_SECONDS: i64 = 60;

struct Attempt {
    id: String,
    state: String,
    verifier: String,
    redirect: String,
    authorize_id: String,
    expires: i64,
    client: reqwest::Client,
    cancel: CancellationToken,
    outcome: Mutex<Outcome>,
}
enum Outcome {
    Waiting,
    Exchanging,
    Done(Result<Saved, String>),
    Consumed,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LoginStart {
    login_id: String,
    verification_uri: String,
    expires_at: i64,
}

fn random_token() -> String {
    let mut bytes = [0u8; 32];
    rand::RngCore::fill_bytes(&mut rand::thread_rng(), &mut bytes);
    URL_SAFE_NO_PAD.encode(bytes)
}

fn browser_url(value: &str, path: &str) -> Result<reqwest::Url, String> {
    let url = reqwest::Url::parse(value).map_err(|_| "accountError.authResponse")?;
    if url.origin().ascii_serialization() != ORIGIN
        || url.path() != path
        || !url.username().is_empty()
        || url.password().is_some()
        || url.fragment().is_some()
    {
        return Err("accountError.authResponse".into());
    }
    Ok(url)
}

pub async fn start(locale: &str) -> Result<LoginStart, String> {
    let _guard = START_LOCK.lock().await;
    let old = PENDING.lock().map_err(|_| "accountError.busy")?.take();
    if let Some(old) = old {
        stop(&old);
    }
    let listener = tokio::net::TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, 0))
        .await
        .map_err(|_| "accountError.auth")?;
    let redirect = format!(
        "http://127.0.0.1:{}/oauth/callback",
        listener
            .local_addr()
            .map_err(|_| "accountError.auth")?
            .port()
    );
    let state = random_token();
    let verifier = random_token();
    let client = accounts::client(locale)?;
    let started = chrono::Utc::now().timestamp();
    let init = accounts::response(
        client
            .post(format!("{ORIGIN}/auth-api/v0/dsh/auth_init"))
            .json(&json!({
                "code_challenge":URL_SAFE_NO_PAD.encode(Sha256::digest(verifier.as_bytes())),
                "code_challenge_method":"S256", "state":state, "redirect_uri":redirect,
                "locale": if locale.starts_with("zh") {"zh_CN"} else {"en_US"}, "login_source":"web"
            })),
    )
    .await?;
    let url = browser_url(
        init["authorize_url"]
            .as_str()
            .ok_or("accountError.authResponse")?,
        "/dsh/authorize",
    )?;
    let authorize_id = init["authorize_id"]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or("accountError.authResponse")?
        .to_string();
    let ttl = init["expires_in"]
        .as_u64()
        .filter(|v| *v > 0)
        .ok_or("accountError.authResponse")?
        .min(LOGIN_TIMEOUT_SECONDS as u64);
    let expires = started + ttl as i64;
    if expires <= chrono::Utc::now().timestamp() {
        return Err("accountError.expired".into());
    }
    let attempt = Arc::new(Attempt {
        id: random_token(),
        state,
        verifier,
        redirect,
        authorize_id,
        expires,
        client,
        cancel: CancellationToken::new(),
        outcome: Mutex::new(Outcome::Waiting),
    });
    let result = LoginStart {
        login_id: attempt.id.clone(),
        verification_uri: url.to_string(),
        expires_at: expires,
    };
    *PENDING.lock().map_err(|_| "accountError.busy")? = Some(attempt.clone());
    let router = Router::new()
        .route("/oauth/callback", get(callback))
        .with_state(attempt.clone());
    let cancellation = attempt.cancel.clone();
    tokio::spawn(async move {
        let _ = axum::serve(listener, router)
            .with_graceful_shutdown(cancellation.cancelled_owned())
            .await;
    });
    tokio::spawn(async move {
        let remaining = (expires - chrono::Utc::now().timestamp()).max(0) as u64;
        tokio::select! {
            _ = attempt.cancel.cancelled() => {},
            _ = tokio::time::sleep(Duration::from_secs(remaining)) => stop(&attempt),
        }
    });
    Ok(result)
}

fn callback_code<'a>(pairs: &'a [(String, String)], expected: &str) -> Result<&'a str, String> {
    let states: Vec<_> = pairs.iter().filter(|(key, _)| key == "state").collect();
    let codes: Vec<_> = pairs.iter().filter(|(key, _)| key == "code").collect();
    if states.len() != 1 || codes.len() != 1 || codes[0].1.is_empty() || codes[0].1.len() > 4096 {
        return Err("accountError.state".into());
    }
    let received = states[0].1.as_bytes();
    let expected = expected.as_bytes();
    if received.len() != expected.len()
        || received
            .iter()
            .zip(expected)
            .fold(0u8, |v, (a, b)| v | (a ^ b))
            != 0
    {
        return Err("accountError.state".into());
    }
    Ok(&codes[0].1)
}

async fn callback(
    State(attempt): State<Arc<Attempt>>,
    Query(pairs): Query<Vec<(String, String)>>,
) -> Response {
    let code = match callback_code(&pairs, &attempt.state) {
        Ok(code) => code,
        Err(_) => return StatusCode::BAD_REQUEST.into_response(),
    };
    {
        let Ok(mut state) = attempt.outcome.lock() else {
            return StatusCode::INTERNAL_SERVER_ERROR.into_response();
        };
        if attempt.cancel.is_cancelled()
            || chrono::Utc::now().timestamp() >= attempt.expires
            || !matches!(*state, Outcome::Waiting)
        {
            return StatusCode::GONE.into_response();
        }
        *state = Outcome::Exchanging;
    }
    let result = tokio::select! {
        _ = attempt.cancel.cancelled() => Err("accountError.cancelled".into()),
        result = exchange(&attempt,code) => result,
    };
    let redirect = result.as_ref().ok().map(|(_, url)| url.clone());
    if let Ok(mut state) = attempt.outcome.lock() {
        if !attempt.cancel.is_cancelled() && chrono::Utc::now().timestamp() < attempt.expires {
            *state = Outcome::Done(result.map(|(saved, _)| saved));
        }
    }
    if attempt.cancel.is_cancelled() {
        return StatusCode::GONE.into_response();
    }
    match redirect {
        Some(url) => Redirect::to(&url).into_response(),
        None => StatusCode::NO_CONTENT.into_response(),
    }
}

async fn exchange(attempt: &Attempt, code: &str) -> Result<(Saved, String), String> {
    let device = uuid::Uuid::new_v4().to_string();
    let result = accounts::response(attempt.client.post(format!("{ORIGIN}/auth-api/v0/dsh/auth_exchange")).json(&json!({
        "code":code, "code_verifier":attempt.verifier, "redirect_uri":attempt.redirect,
        "device_id":device, "device_model":format!("{}-{}",std::env::consts::OS,std::env::consts::ARCH),
        "os_version":std::env::consts::OS
    }))).await?;
    let token = result["token"]
        .as_str()
        .filter(|s| accounts::valid_token(s))
        .ok_or("accountError.authResponse")?
        .to_string();
    let mut url = browser_url(
        result["authorized_url"]
            .as_str()
            .ok_or("accountError.authResponse")?,
        "/dsh/authorized",
    )?;
    let pairs: Vec<_> = url
        .query_pairs()
        .filter(|(k, _)| k != "login_source")
        .map(|(k, v)| (k.into_owned(), v.into_owned()))
        .collect();
    url.query_pairs_mut()
        .clear()
        .extend_pairs(pairs)
        .append_pair("login_source", "desktop");
    // Query identity independently: masked contact text is not an account ID.
    let profile = accounts::profile(&attempt.client, &token).await?;
    Ok((
        accounts::snapshot(&profile, token, device)?,
        url.to_string(),
    ))
}

fn stop(attempt: &Arc<Attempt>) {
    if attempt.cancel.is_cancelled() {
        return;
    }
    attempt.cancel.cancel();
    let attempt = attempt.clone();
    tokio::spawn(async move {
        let _ = accounts::response(
            attempt
                .client
                .post(format!("{ORIGIN}/auth-api/v0/dsh/auth_cancel"))
                .json(&json!({
                    "authorize_id":attempt.authorize_id,"code_verifier":attempt.verifier
                })),
        )
        .await;
    });
}

pub fn cancel(id: &str) -> Result<(), String> {
    let mut pending = PENDING.lock().map_err(|_| "accountError.busy")?;
    if pending.as_ref().is_some_and(|p| p.id == id) {
        if let Some(attempt) = pending.take() {
            stop(&attempt);
        }
    }
    Ok(())
}

pub async fn poll(id: &str) -> Result<Option<Account>, String> {
    let _guard = accounts::ACCOUNT_LOCK.lock().await;
    let mut pending = PENDING.lock().map_err(|_| "accountError.busy")?;
    let attempt = pending
        .as_ref()
        .filter(|p| p.id == id)
        .ok_or("accountError.cancelled")?
        .clone();
    let result = finish_attempt(&attempt, &accounts::store()?)?;
    if result.is_some() {
        *pending = None;
    }
    Ok(result)
}

fn finish_attempt(attempt: &Attempt, dir: &std::path::Path) -> Result<Option<Account>, String> {
    if attempt.cancel.is_cancelled() || chrono::Utc::now().timestamp() >= attempt.expires {
        return Err("accountError.expired".into());
    }
    let mut outcome = attempt.outcome.lock().map_err(|_| "accountError.busy")?;
    match &*outcome {
        Outcome::Waiting | Outcome::Exchanging => Ok(None),
        Outcome::Done(Err(error)) => Err(error.clone()),
        Outcome::Consumed => Err("accountError.cancelled".into()),
        Outcome::Done(Ok(saved)) => {
            accounts::save_at(dir, saved)?;
            let summary = saved.summary.clone();
            *outcome = Outcome::Consumed;
            attempt.cancel.cancel();
            Ok(Some(summary))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn cancelled_and_expired_callbacks_cannot_save_an_account() {
        let dir = std::env::temp_dir().join(format!("echobird-dsh-auth-{}", uuid::Uuid::new_v4()));
        let saved = accounts::snapshot(
            &json!({"id":"test-user","email":"test@example.test"}),
            "test-token".into(),
            uuid::Uuid::new_v4().to_string(),
        )
        .unwrap();
        let mut attempt = Attempt {
            id: "test".into(),
            state: "state".into(),
            verifier: "verifier".into(),
            redirect: "http://127.0.0.1:1234/oauth/callback".into(),
            authorize_id: "test".into(),
            expires: chrono::Utc::now().timestamp() + 600,
            client: accounts::client("en").unwrap(),
            cancel: CancellationToken::new(),
            outcome: Mutex::new(Outcome::Done(Ok(saved))),
        };
        attempt.cancel.cancel();
        assert!(finish_attempt(&attempt, &dir).is_err());
        assert!(!dir.exists());
        attempt.cancel = CancellationToken::new();
        attempt.expires = chrono::Utc::now().timestamp() - 1;
        assert!(finish_attempt(&attempt, &dir).is_err());
        assert!(!dir.exists());
        attempt.expires = chrono::Utc::now().timestamp() + 600;
        let account = finish_attempt(&attempt, &dir).unwrap().unwrap();
        assert!(dir.join(format!("{}.yaml", account.id)).is_file());
        assert!(!serde_json::to_string(&account)
            .unwrap()
            .contains("test-token"));
        assert!(finish_attempt(&attempt, &dir).is_err());
        std::fs::remove_dir_all(dir).unwrap();
    }
    #[tokio::test]
    #[ignore = "network: initializes and cancels an official authorization attempt without signing in"]
    async fn official_authorization_initializes_and_cancels() {
        let login = start("zh-CN")
            .await
            .expect("Official authorization initialization failed");
        assert!(browser_url(&login.verification_uri, "/dsh/authorize").is_ok());
        assert!(login.expires_at > chrono::Utc::now().timestamp());
        cancel(&login.login_id).unwrap();
        assert_eq!(
            poll(&login.login_id).await.unwrap_err(),
            "accountError.cancelled"
        );
    }
    #[test]
    fn callback_requires_one_matching_state_and_code() {
        let pairs = vec![
            ("state".into(), "expected".into()),
            ("code".into(), "code".into()),
        ];
        assert_eq!(callback_code(&pairs, "expected").unwrap(), "code");
        assert!(callback_code(&pairs, "wrong").is_err());
        let mut duplicate = pairs.clone();
        duplicate.push(("state".into(), "expected".into()));
        assert!(callback_code(&duplicate, "expected").is_err());
        assert!(callback_code(&[], "expected").is_err());
    }
    #[test]
    fn authorization_stays_on_the_official_origin_and_path() {
        assert!(browser_url(
            "https://platform.deepseek.com/dsh/authorize?state=x",
            "/dsh/authorize"
        )
        .is_ok());
        for url in [
            "https://evil.test/dsh/authorize",
            "http://platform.deepseek.com/dsh/authorize",
            "https://platform.deepseek.com/other",
            "https://user@platform.deepseek.com/dsh/authorize",
            "https://platform.deepseek.com/dsh/authorize#token",
        ] {
            assert!(browser_url(url, "/dsh/authorize").is_err());
        }
    }
}