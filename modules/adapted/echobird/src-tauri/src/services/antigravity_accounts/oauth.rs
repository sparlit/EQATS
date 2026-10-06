use super::{quota, LoginStart};
use axum::{
    extract::{Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::get,
    Router,
};
use serde_json::{json, Value};
use std::{
    sync::{Arc, Mutex},
    time::Duration,
};
use tokio_util::sync::CancellationToken;

static PENDING: Mutex<Option<Arc<Attempt>>> = Mutex::new(None);
static START_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());
const CALLBACK_PATH: &str = "/oauth-callback";

struct Attempt {
    id: String,
    state: String,
    redirect: String,
    expires: i64,
    cancel: CancellationToken,
    outcome: Mutex<Outcome>,
}

enum Outcome {
    Waiting,
    Exchanging,
    Done(Result<String, String>),
}

fn authorize_url(redirect: &str, state: &str) -> Result<String, String> {
    let scope = [
        "openid",
        "https://www.googleapis.com/auth/cloud-platform",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
        "https://www.googleapis.com/auth/cclog",
        "https://www.googleapis.com/auth/experimentsandconfigs",
        "https://www.googleapis.com/auth/aicode",
    ]
    .join(" ");
    reqwest::Url::parse_with_params(
        "https://accounts.google.com/o/oauth2/v2/auth",
        &[
            ("client_id", quota::CLIENT_ID),
            ("redirect_uri", redirect),
            ("response_type", "code"),
            ("scope", scope.as_str()),
            ("access_type", "offline"),
            ("prompt", "select_account consent"),
            ("state", state),
        ],
    )
    .map(|url| url.to_string())
    .map_err(|_| "accountError.auth".into())
}

pub(super) async fn start() -> Result<LoginStart, String> {
    let _guard = START_LOCK.lock().await;
    if quota::CLIENT_ID.is_empty() || quota::CLIENT_SECRET.is_empty() {
        return Err("accountError.auth".into());
    }
    if let Some(previous) = PENDING.lock().map_err(|_| "accountError.busy")?.take() {
        previous.cancel.cancel();
    }
    let listener = tokio::net::TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, 0))
        .await
        .map_err(|_| "accountError.auth")?;
    let port = listener
        .local_addr()
        .map_err(|_| "accountError.auth")?
        .port();
    let redirect = format!("http://127.0.0.1:{port}{CALLBACK_PATH}");
    let state = uuid::Uuid::new_v4().to_string();
    let verification_uri = authorize_url(&redirect, &state)?;
    let attempt = Arc::new(Attempt {
        id: uuid::Uuid::new_v4().to_string(),
        state,
        redirect,
        expires: chrono::Utc::now().timestamp() + 60,
        cancel: CancellationToken::new(),
        outcome: Mutex::new(Outcome::Waiting),
    });
    let result = LoginStart {
        login_id: attempt.id.clone(),
        verification_uri,
        expires_at: attempt.expires,
    };
    *PENDING.lock().map_err(|_| "accountError.busy")? = Some(attempt.clone());
    let router = Router::new()
        .route(CALLBACK_PATH, get(callback))
        .with_state(attempt.clone());
    let cancel = attempt.cancel.clone();
    tokio::spawn(async move {
        let _ = axum::serve(listener, router)
            .with_graceful_shutdown(cancel.cancelled_owned())
            .await;
    });
    tokio::spawn(async move {
        tokio::select! {
            _ = attempt.cancel.cancelled() => {},
            _ = tokio::time::sleep(Duration::from_secs(60)) => attempt.cancel.cancel(),
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
        let Ok(mut outcome) = attempt.outcome.lock() else {
            return StatusCode::INTERNAL_SERVER_ERROR.into_response();
        };
        if attempt.cancel.is_cancelled()
            || chrono::Utc::now().timestamp() >= attempt.expires
            || !matches!(*outcome, Outcome::Waiting)
        {
            return StatusCode::GONE.into_response();
        }
        *outcome = Outcome::Exchanging;
    }
    let result = tokio::select! {
        _ = attempt.cancel.cancelled() => Err("accountError.cancelled".into()),
        result = exchange(code, &attempt.redirect) => result,
    };
    if attempt.cancel.is_cancelled() || chrono::Utc::now().timestamp() >= attempt.expires {
        return StatusCode::GONE.into_response();
    }
    let success = result.is_ok();
    if let Ok(mut outcome) = attempt.outcome.lock() {
        *outcome = Outcome::Done(result);
    }
    if success {
        (
            StatusCode::OK,
            "Authorization complete. Return to EchoBird.",
        )
            .into_response()
    } else {
        StatusCode::BAD_REQUEST.into_response()
    }
}

async fn exchange(code: &str, redirect: &str) -> Result<String, String> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(15))
        .build()
        .map_err(|_| "accountError.network")?;
    let response = client
        .post("https://oauth2.googleapis.com/token")
        .form(&[
            ("client_id", quota::CLIENT_ID),
            ("client_secret", quota::CLIENT_SECRET),
            ("code", code),
            ("redirect_uri", redirect),
            ("grant_type", "authorization_code"),
        ])
        .send()
        .await
        .map_err(|_| "accountError.network")?;
    if !response.status().is_success() {
        return Err(format!(
            "accountError.auth|HTTP {}",
            response.status().as_u16()
        ));
    }
    let token: Value = response
        .json()
        .await
        .map_err(|_| "accountError.authResponse")?;
    let access = token["access_token"]
        .as_str()
        .filter(|v| !v.is_empty())
        .ok_or("accountError.authResponse")?;
    let refresh = token["refresh_token"]
        .as_str()
        .filter(|v| !v.is_empty())
        .ok_or("accountError.authResponse")?;
    let id_token = token["id_token"]
        .as_str()
        .filter(|v| !v.is_empty())
        .ok_or("accountError.authResponse")?;
    let expires = token["expires_in"]
        .as_i64()
        .filter(|v| *v > 0)
        .ok_or("accountError.authResponse")?;
    let raw = json!({
        "auth_method":"consumer",
        "id_token":id_token,
        "token":{
            "access_token":access,
            "refresh_token":refresh,
            "token_type":token["token_type"].as_str().unwrap_or("Bearer"),
            "expiry":(chrono::Utc::now() + chrono::Duration::seconds(expires)).to_rfc3339(),
        }
    });
    super::identity(&raw.to_string())?;
    Ok(raw.to_string())
}

pub(super) fn poll(id: &str) -> Result<Option<String>, String> {
    let pending = PENDING.lock().map_err(|_| "accountError.busy")?;
    let attempt = pending
        .as_ref()
        .filter(|p| p.id == id)
        .ok_or("accountError.cancelled")?;
    if attempt.cancel.is_cancelled() || chrono::Utc::now().timestamp() >= attempt.expires {
        return Err("accountError.expired".into());
    }
    let outcome = attempt.outcome.lock().map_err(|_| "accountError.busy")?;
    match &*outcome {
        Outcome::Waiting | Outcome::Exchanging => Ok(None),
        Outcome::Done(result) => result.clone().map(Some),
    }
}

pub(super) fn cancel(id: &str) -> Result<(), String> {
    let mut pending = PENDING.lock().map_err(|_| "accountError.busy")?;
    if pending.as_ref().is_some_and(|p| p.id == id) {
        if let Some(attempt) = pending.take() {
            attempt.cancel.cancel();
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{authorize_url, callback_code};

    #[test]
    fn browser_url_requests_account_choice_and_loopback_callback() {
        let url = authorize_url("http://127.0.0.1:1234/oauth-callback", "state-value").unwrap();
        let parsed = reqwest::Url::parse(&url).unwrap();
        let pairs: std::collections::HashMap<_, _> = parsed.query_pairs().into_owned().collect();
        assert_eq!(parsed.host_str(), Some("accounts.google.com"));
        assert_eq!(
            pairs["redirect_uri"],
            "http://127.0.0.1:1234/oauth-callback"
        );
        assert_eq!(pairs["prompt"], "select_account consent");
        assert_eq!(pairs["state"], "state-value");
    }

    #[test]
    fn callback_rejects_wrong_or_duplicate_state() {
        let valid = vec![
            ("state".into(), "expected".into()),
            ("code".into(), "code".into()),
        ];
        assert_eq!(callback_code(&valid, "expected").unwrap(), "code");
        let wrong = vec![
            ("state".into(), "wrong".into()),
            ("code".into(), "code".into()),
        ];
        assert!(callback_code(&wrong, "expected").is_err());
        let mut duplicate = valid.clone();
        duplicate.push(("state".into(), "expected".into()));
        assert!(callback_code(&duplicate, "expected").is_err());
    }
}