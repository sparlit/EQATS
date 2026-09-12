use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs;
use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use axum::body::{Body, Bytes};
use axum::extract::{DefaultBodyLimit, State};
use axum::http::{header, HeaderMap, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Json, Response};
use axum::routing::{get, post};
use axum::Router;
use futures_util::{stream, StreamExt};
use http_body_util::BodyExt;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tokio_stream::wrappers::ReceiverStream;

use super::{
    api_key_for_use, candidate_ids, mark_running, PublicActivity, SMART_ROUTER_INTERNAL_ID,
    SMART_ROUTER_MODEL_ID,
};
use crate::services::model_manager;
use crate::utils::platform::echobird_dir;

const MAX_REQUEST_BODY_BYTES: usize = 64 * 1024 * 1024;
pub const MAX_ROUTE_CANDIDATES: usize = 20;
const FALLBACK_TIME_BUDGET: Duration = Duration::from_secs(45);
const UPSTREAM_HEADER_TIMEOUT: Duration = Duration::from_secs(30);
const UPSTREAM_FIRST_BYTE_TIMEOUT: Duration = Duration::from_secs(120);
const TRANSIENT_COOLDOWN: Duration = Duration::from_secs(30);
const MAX_TRANSIENT_COOLDOWN: Duration = Duration::from_secs(5 * 60);
const RATE_LIMIT_COOLDOWN: Duration = Duration::from_secs(60);
const AUTH_OR_BILLING_COOLDOWN: Duration = Duration::from_secs(60 * 60);
const MODEL_UNAVAILABLE_COOLDOWN: Duration = Duration::from_secs(6 * 60 * 60);
const MAX_RETRY_AFTER: Duration = Duration::from_secs(24 * 60 * 60);

static ROUTE_MEMORY: OnceLock<Arc<Mutex<RouteMemory>>> = OnceLock::new();
static ROUTE_ACTIVITY: OnceLock<Mutex<RouteActivity>> = OnceLock::new();

#[derive(Default)]
struct RouteActivity {
    next_attempt_id: u64,
    active_attempts: BTreeMap<u64, String>,
    last_candidate_id: Option<String>,
    sequence: u64,
    updated_at_ms: u64,
}

impl RouteActivity {
    fn begin(&mut self, candidate_id: &str, updated_at_ms: u64) -> u64 {
        self.next_attempt_id = self.next_attempt_id.saturating_add(1);
        let attempt_id = self.next_attempt_id;
        self.active_attempts
            .insert(attempt_id, candidate_id.to_string());
        self.last_candidate_id = Some(candidate_id.to_string());
        self.sequence = self.sequence.saturating_add(1);
        self.updated_at_ms = updated_at_ms;
        attempt_id
    }

    fn end(&mut self, attempt_id: u64, updated_at_ms: u64) {
        if self.active_attempts.remove(&attempt_id).is_none() {
            return;
        }
        if let Some((_, candidate_id)) = self.active_attempts.last_key_value() {
            self.last_candidate_id = Some(candidate_id.clone());
        }
        self.sequence = self.sequence.saturating_add(1);
        self.updated_at_ms = updated_at_ms;
    }

    fn snapshot(&self) -> PublicActivity {
        PublicActivity {
            candidate_id: self.last_candidate_id.clone(),
            active: !self.active_attempts.is_empty(),
            sequence: self.sequence,
            updated_at_ms: self.updated_at_ms,
        }
    }
}

struct RouteActivityGuard {
    attempt_id: Option<u64>,
}

impl RouteActivityGuard {
    fn begin(candidate_id: &str) -> Self {
        let attempt_id = ROUTE_ACTIVITY
            .get_or_init(|| Mutex::new(RouteActivity::default()))
            .lock()
            .ok()
            .map(|mut activity| activity.begin(candidate_id, now_ms()));
        Self { attempt_id }
    }
}

impl Drop for RouteActivityGuard {
    fn drop(&mut self) {
        let Some(attempt_id) = self.attempt_id else {
            return;
        };
        let Some(activity) = ROUTE_ACTIVITY.get() else {
            return;
        };
        if let Ok(mut activity) = activity.lock() {
            activity.end(attempt_id, now_ms());
        }
    }
}

pub(crate) fn public_activity() -> PublicActivity {
    ROUTE_ACTIVITY
        .get_or_init(|| Mutex::new(RouteActivity::default()))
        .lock()
        .map(|activity| activity.snapshot())
        .unwrap_or(PublicActivity {
            candidate_id: None,
            active: false,
            sequence: 0,
            updated_at_ms: 0,
        })
}

#[derive(Clone)]
struct AppState {
    http_client: reqwest::Client,
    route_memory: Arc<Mutex<RouteMemory>>,
    route_memory_path: Option<PathBuf>,
}

impl AppState {
    fn new() -> Result<Self, String> {
        let http_client = reqwest::Client::builder()
            .connect_timeout(Duration::from_secs(15))
            .tcp_keepalive(Duration::from_secs(60))
            .build()
            .map_err(|e| format!("reqwest client build failed: {e}"))?;
        Ok(Self {
            http_client,
            route_memory: shared_route_memory(),
            route_memory_path: Some(route_memory_path()),
        })
    }

    #[cfg(test)]
    fn for_tests() -> Result<Self, String> {
        let http_client = reqwest::Client::builder()
            .connect_timeout(Duration::from_secs(15))
            .tcp_keepalive(Duration::from_secs(60))
            .build()
            .map_err(|e| format!("reqwest client build failed: {e}"))?;
        Ok(Self {
            http_client,
            route_memory: Arc::new(Mutex::new(RouteMemory::default())),
            route_memory_path: None,
        })
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct RouteMemory {
    #[serde(default = "route_memory_version")]
    version: u32,
    #[serde(default)]
    last_success_id: Option<String>,
    #[serde(default)]
    candidates: HashMap<String, CandidateHealth>,
}

impl Default for RouteMemory {
    fn default() -> Self {
        Self {
            version: route_memory_version(),
            last_success_id: None,
            candidates: HashMap::new(),
        }
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct CandidateHealth {
    #[serde(default)]
    consecutive_failures: u32,
    #[serde(default)]
    cooldown_until_ms: Option<u64>,
    #[serde(default)]
    fingerprint: String,
    #[serde(default)]
    failure: Option<FailureClass>,
}

#[derive(Debug, Clone)]
struct Candidate {
    internal_id: String,
    model_id: String,
    base_url: String,
    api_key: String,
    fingerprint: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum FailureClass {
    Authentication,
    Billing,
    ModelUnavailable,
    RateLimit,
    Transient,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct AttemptRecord {
    candidate_id: String,
    model_id: String,
    failure: FailureClass,
    status: Option<u16>,
}

#[derive(Clone, Copy)]
struct RoutePolicy {
    max_attempts: usize,
    time_budget: Duration,
    header_timeout: Duration,
    first_byte_timeout: Duration,
}

impl Default for RoutePolicy {
    fn default() -> Self {
        Self {
            max_attempts: MAX_ROUTE_CANDIDATES,
            time_budget: FALLBACK_TIME_BUDGET,
            header_timeout: UPSTREAM_HEADER_TIMEOUT,
            first_byte_timeout: UPSTREAM_FIRST_BYTE_TIMEOUT,
        }
    }
}

fn route_memory_version() -> u32 {
    1
}

fn route_memory_path() -> PathBuf {
    echobird_dir()
        .join("config")
        .join("smart-router-state.json")
}

fn shared_route_memory() -> Arc<Mutex<RouteMemory>> {
    ROUTE_MEMORY
        .get_or_init(|| Arc::new(Mutex::new(load_route_memory(&route_memory_path()))))
        .clone()
}

fn load_route_memory(path: &Path) -> RouteMemory {
    if !path.exists() {
        return RouteMemory::default();
    }
    fs::read_to_string(path)
        .map_err(|e| e.to_string())
        .and_then(|content| serde_json::from_str(&content).map_err(|e| e.to_string()))
        .unwrap_or_else(|error| {
            log::warn!(
                "[SmartRouter] Ignoring invalid route memory {}: {error}",
                path.display()
            );
            RouteMemory::default()
        })
}

fn save_route_memory(path: &Path, memory: &RouteMemory) {
    let Some(parent) = path.parent() else {
        return;
    };
    let result = fs::create_dir_all(parent)
        .map_err(|e| e.to_string())
        .and_then(|_| serde_json::to_string_pretty(memory).map_err(|e| e.to_string()))
        .and_then(|content| fs::write(path, content).map_err(|e| e.to_string()));
    if let Err(error) = result {
        log::warn!(
            "[SmartRouter] Failed to save route memory {}: {error}",
            path.display()
        );
    }
}

fn persist_route_memory(state: &AppState, memory: &RouteMemory) {
    if let Some(path) = &state.route_memory_path {
        save_route_memory(path, memory);
    }
}

pub(crate) fn retain_candidate_memory(candidate_ids: &[String]) {
    let memory = shared_route_memory();
    let Ok(mut memory) = memory.lock() else {
        return;
    };
    let valid: HashSet<&str> = candidate_ids.iter().map(String::as_str).collect();
    let previous_len = memory.candidates.len();
    memory
        .candidates
        .retain(|candidate_id, _| valid.contains(candidate_id.as_str()));
    let removed_preferred = memory
        .last_success_id
        .as_deref()
        .is_some_and(|candidate_id| !valid.contains(candidate_id));
    if removed_preferred {
        memory.last_success_id = None;
    }
    if memory.candidates.len() != previous_len || removed_preferred {
        save_route_memory(&route_memory_path(), &memory);
    }
}

pub(crate) fn forget_candidate_memory(candidate_id: &str) {
    let memory = shared_route_memory();
    let Ok(mut memory) = memory.lock() else {
        return;
    };
    let removed = memory.candidates.remove(candidate_id).is_some();
    let removed_preferred = memory.last_success_id.as_deref() == Some(candidate_id);
    if removed_preferred {
        memory.last_success_id = None;
    }
    if removed || removed_preferred {
        save_route_memory(&route_memory_path(), &memory);
    }
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .min(u128::from(u64::MAX)) as u64
}

fn candidate_fingerprint(model_id: &str, base_url: &str, api_key: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(model_id.as_bytes());
    hasher.update([0]);
    hasher.update(base_url.as_bytes());
    hasher.update([0]);
    hasher.update(api_key.as_bytes());
    hex::encode(hasher.finalize())
}

pub async fn run(port: u16) -> Result<(), String> {
    let state = AppState::new()?;
    let app = Router::new()
        .route("/health", get(handle_health))
        .route("/v1/models", get(handle_models))
        .route("/models", get(handle_models))
        .route("/v1/chat/completions", post(handle_chat))
        .route("/chat/completions", post(handle_chat))
        .route("/v1/messages", post(handle_messages))
        .route("/messages", post(handle_messages))
        .layer(DefaultBodyLimit::max(MAX_REQUEST_BODY_BYTES))
        .with_state(state);
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .map_err(|e| format!("bind 127.0.0.1:{port} failed: {e}"))?;

    mark_running();
    log::info!("[SmartRouter] listening on 127.0.0.1:{port}");
    axum::serve(listener, app)
        .await
        .map_err(|e| format!("serve failed: {e}"))
}

async fn handle_health() -> Json<Value> {
    let ids = candidate_ids();
    Json(json!({
        "status": "ok",
        "model": SMART_ROUTER_MODEL_ID,
        "candidates": ids.len(),
        "usableCandidates": super::usable_candidate_count(&ids),
    }))
}

async fn handle_models(headers: HeaderMap) -> Response {
    let expected_key = match api_key_for_use() {
        Ok(key) => key,
        Err(e) => return openai_error(StatusCode::INTERNAL_SERVER_ERROR, &e),
    };
    if !is_authorized(&headers, &expected_key) {
        return openai_error(StatusCode::UNAUTHORIZED, "Invalid EchoBird router API key");
    }

    Json(json!({
        "object": "list",
        "data": [{
            "id": SMART_ROUTER_MODEL_ID,
            "object": "model",
            "created": 0,
            "owned_by": "echobird"
        }]
    }))
    .into_response()
}

async fn handle_chat(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Response {
    let expected_key = match api_key_for_use() {
        Ok(key) => key,
        Err(e) => return openai_error(StatusCode::INTERNAL_SERVER_ERROR, &e),
    };
    if !is_authorized(&headers, &expected_key) {
        return openai_error(StatusCode::UNAUTHORIZED, "Invalid EchoBird router API key");
    }

    let requested_model = body
        .get("model")
        .and_then(Value::as_str)
        .unwrap_or_default();
    if !is_supported_router_model(requested_model) {
        return openai_error(
            StatusCode::NOT_FOUND,
            &format!("Unknown router model: {requested_model}"),
        );
    }

    let candidates = resolve_candidates();
    route_chat_with_candidates(&state, &headers, body, candidates).await
}

fn is_supported_router_model(model_id: &str) -> bool {
    matches!(
        model_id,
        SMART_ROUTER_MODEL_ID | "echobird/auto" | "echobird-auto" | SMART_ROUTER_INTERNAL_ID
    )
}

async fn handle_messages(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Response {
    let expected_key = match api_key_for_use() {
        Ok(key) => key,
        Err(e) => return anthropic_error(StatusCode::INTERNAL_SERVER_ERROR, &e),
    };
    if !is_authorized(&headers, &expected_key) {
        return anthropic_error(StatusCode::UNAUTHORIZED, "Invalid EchoBird router API key");
    }

    route_messages_with_candidates(&state, &headers, body, resolve_candidates()).await
}

async fn route_messages_with_candidates(
    state: &AppState,
    headers: &HeaderMap,
    body: Value,
    candidates: Vec<Candidate>,
) -> Response {
    let stream_requested = body.get("stream").and_then(Value::as_bool).unwrap_or(false);
    let mut openai_body = crate::services::local_llm::proxy::anthropic_to_openai(&body);
    openai_body["model"] = Value::String(SMART_ROUTER_MODEL_ID.to_string());
    let response = route_chat_with_candidates(state, headers, openai_body, candidates).await;

    if !response.status().is_success() {
        return openai_error_to_anthropic(response).await;
    }
    if stream_requested {
        openai_stream_to_anthropic(response)
    } else {
        openai_response_to_anthropic(response).await
    }
}

fn resolve_candidates() -> Vec<Candidate> {
    let ids = candidate_ids();
    let user_models = model_manager::get_user_models();
    let local_server = crate::services::local_llm::get_server_info_sync();

    ids.into_iter()
        .filter_map(|id| {
            if id == "local-server" && local_server.running {
                let model_id = local_server.model_name.clone();
                let base_url = format!("http://127.0.0.1:{}/v1", local_server.port);
                let api_key = local_server.api_key.clone();
                return Some(Candidate {
                    internal_id: id,
                    fingerprint: candidate_fingerprint(&model_id, &base_url, &api_key),
                    model_id,
                    base_url,
                    api_key,
                });
            }

            let model = user_models.iter().find(|model| model.internal_id == id)?;
            let model_id = model.model_id.as_deref()?.trim();
            if model_id.is_empty() || model.base_url.trim().is_empty() {
                return None;
            }
            let api_key = model_manager::decrypt_key_for_use(&model.api_key);
            if api_key.is_empty() {
                return None;
            }

            Some(Candidate {
                internal_id: model.internal_id.clone(),
                fingerprint: candidate_fingerprint(model_id, &model.base_url, &model.api_key),
                model_id: model_id.to_string(),
                base_url: model.base_url.clone(),
                api_key,
            })
        })
        .filter(|candidate| !candidate.base_url.contains(":53683"))
        .collect()
}

async fn route_chat_with_candidates(
    state: &AppState,
    inbound_headers: &HeaderMap,
    body: Value,
    candidates: Vec<Candidate>,
) -> Response {
    route_chat_with_policy(
        state,
        inbound_headers,
        body,
        candidates,
        RoutePolicy::default(),
    )
    .await
}

async fn route_chat_with_policy(
    state: &AppState,
    inbound_headers: &HeaderMap,
    body: Value,
    candidates: Vec<Candidate>,
    policy: RoutePolicy,
) -> Response {
    if candidates.is_empty() {
        return openai_error(
            StatusCode::SERVICE_UNAVAILABLE,
            "No usable models are configured for Auto Router",
        );
    }

    let available = prioritized_candidates(state, candidates);
    if available.is_empty() {
        return openai_error(
            StatusCode::SERVICE_UNAVAILABLE,
            "All Auto Router models are cooling down",
        );
    }

    let stream_requested = body.get("stream").and_then(Value::as_bool).unwrap_or(false);
    let mut attempts = Vec::new();
    let routing_started = Instant::now();

    for candidate in available.into_iter().take(policy.max_attempts) {
        let Some(header_timeout) =
            remaining_timeout(routing_started, policy.time_budget, policy.header_timeout)
        else {
            break;
        };
        let mut upstream_body = body.clone();
        upstream_body["model"] = Value::String(candidate.model_id.clone());
        let url = chat_completions_url(&candidate.base_url);
        let mut request = state
            .http_client
            .post(url)
            .header(header::CONTENT_TYPE, "application/json")
            .header(
                header::AUTHORIZATION,
                format!("Bearer {}", candidate.api_key),
            )
            .header("HTTP-Referer", "https://echobird.ai")
            .header("X-OpenRouter-Title", "EchoBird")
            .header("X-OpenRouter-Categories", "programming-app,personal-agent")
            .json(&upstream_body);
        if let Some(user_agent) = inbound_headers.get(header::USER_AGENT) {
            request = request.header(header::USER_AGENT, user_agent.clone());
        }

        let activity_guard = RouteActivityGuard::begin(&candidate.internal_id);
        let sent = tokio::time::timeout(header_timeout, request.send()).await;
        let response = match sent {
            Ok(Ok(response)) => response,
            Ok(Err(error)) => {
                mark_failure(state, &candidate, FailureClass::Transient, None);
                attempts.push(AttemptRecord {
                    candidate_id: candidate.internal_id.clone(),
                    model_id: candidate.model_id.clone(),
                    failure: FailureClass::Transient,
                    status: None,
                });
                log::warn!(
                    "[SmartRouter] {} transport failure: {}",
                    candidate.internal_id,
                    error
                );
                continue;
            }
            Err(_) => {
                mark_failure(state, &candidate, FailureClass::Transient, None);
                attempts.push(AttemptRecord {
                    candidate_id: candidate.internal_id.clone(),
                    model_id: candidate.model_id.clone(),
                    failure: FailureClass::Transient,
                    status: None,
                });
                log::warn!(
                    "[SmartRouter] {} timed out before response headers",
                    candidate.internal_id
                );
                continue;
            }
        };

        let status = response.status();
        let content_type = response.headers().get(header::CONTENT_TYPE).cloned();
        let cache_control = response.headers().get(header::CACHE_CONTROL).cloned();
        if !status.is_success() {
            let retry_after = retry_after(response.headers());
            let Some(error_body_timeout) =
                remaining_timeout(routing_started, policy.time_budget, policy.header_timeout)
            else {
                mark_failure(state, &candidate, FailureClass::Transient, None);
                attempts.push(AttemptRecord {
                    candidate_id: candidate.internal_id.clone(),
                    model_id: candidate.model_id.clone(),
                    failure: FailureClass::Transient,
                    status: Some(status.as_u16()),
                });
                break;
            };
            let response_body =
                match tokio::time::timeout(error_body_timeout, response.bytes()).await {
                    Ok(Ok(body)) => body,
                    Ok(Err(_)) | Err(_) => {
                        mark_failure(state, &candidate, FailureClass::Transient, None);
                        attempts.push(AttemptRecord {
                            candidate_id: candidate.internal_id.clone(),
                            model_id: candidate.model_id.clone(),
                            failure: FailureClass::Transient,
                            status: Some(status.as_u16()),
                        });
                        break;
                    }
                };
            if let Some(failure) = classify_failure(status, &response_body) {
                mark_failure(state, &candidate, failure, retry_after);
                attempts.push(AttemptRecord {
                    candidate_id: candidate.internal_id.clone(),
                    model_id: candidate.model_id.clone(),
                    failure,
                    status: Some(status.as_u16()),
                });
                log::warn!(
                    "[SmartRouter] {} returned {}, trying next candidate",
                    candidate.internal_id,
                    status.as_u16()
                );
                continue;
            }

            return upstream_response(
                status,
                content_type,
                cache_control,
                response_body,
                &candidate,
            );
        }

        if stream_requested {
            let mut upstream_stream = response.bytes_stream();
            let Some(first_byte_timeout) = remaining_timeout(
                routing_started,
                policy.time_budget,
                policy.first_byte_timeout,
            ) else {
                mark_failure(state, &candidate, FailureClass::Transient, None);
                attempts.push(AttemptRecord {
                    candidate_id: candidate.internal_id.clone(),
                    model_id: candidate.model_id.clone(),
                    failure: FailureClass::Transient,
                    status: Some(status.as_u16()),
                });
                break;
            };
            let first = tokio::time::timeout(first_byte_timeout, upstream_stream.next()).await;
            match first {
                Ok(Some(Ok(first_chunk))) if !first_chunk.is_empty() => {
                    mark_success(state, &candidate);
                    let stream_state = state.clone();
                    let stream_candidate = candidate.clone();
                    let activity_guard = Arc::new(activity_guard);
                    let rest = upstream_stream.then(move |item| {
                        let stream_state = stream_state.clone();
                        let stream_candidate = stream_candidate.clone();
                        let activity_guard = activity_guard.clone();
                        async move {
                            let _activity_guard = activity_guard;
                            match item {
                                Ok(bytes) => Ok(bytes),
                                Err(error) => {
                                    mark_failure(
                                        &stream_state,
                                        &stream_candidate,
                                        FailureClass::Transient,
                                        None,
                                    );
                                    Err(std::io::Error::other(error))
                                }
                            }
                        }
                    });
                    let body_stream =
                        stream::once(async move { Ok::<Bytes, std::io::Error>(first_chunk) })
                            .chain(rest);
                    return streaming_response(
                        content_type,
                        cache_control,
                        Body::from_stream(body_stream),
                        &candidate,
                    );
                }
                Ok(Some(Ok(_))) | Ok(None) | Ok(Some(Err(_))) | Err(_) => {
                    mark_failure(state, &candidate, FailureClass::Transient, None);
                    attempts.push(AttemptRecord {
                        candidate_id: candidate.internal_id.clone(),
                        model_id: candidate.model_id.clone(),
                        failure: FailureClass::Transient,
                        status: Some(status.as_u16()),
                    });
                    continue;
                }
            }
        }

        let Some(body_timeout) =
            remaining_timeout(routing_started, policy.time_budget, policy.time_budget)
        else {
            mark_failure(state, &candidate, FailureClass::Transient, None);
            attempts.push(AttemptRecord {
                candidate_id: candidate.internal_id.clone(),
                model_id: candidate.model_id.clone(),
                failure: FailureClass::Transient,
                status: Some(status.as_u16()),
            });
            break;
        };
        match tokio::time::timeout(body_timeout, response.bytes()).await {
            Ok(Ok(response_body)) => {
                mark_success(state, &candidate);
                return upstream_response(
                    status,
                    content_type,
                    cache_control,
                    response_body,
                    &candidate,
                );
            }
            Ok(Err(error)) => {
                mark_failure(state, &candidate, FailureClass::Transient, None);
                attempts.push(AttemptRecord {
                    candidate_id: candidate.internal_id.clone(),
                    model_id: candidate.model_id.clone(),
                    failure: FailureClass::Transient,
                    status: Some(status.as_u16()),
                });
                log::warn!(
                    "[SmartRouter] {} response body failure: {}",
                    candidate.internal_id,
                    error
                );
            }
            Err(_) => {
                mark_failure(state, &candidate, FailureClass::Transient, None);
                attempts.push(AttemptRecord {
                    candidate_id: candidate.internal_id.clone(),
                    model_id: candidate.model_id.clone(),
                    failure: FailureClass::Transient,
                    status: Some(status.as_u16()),
                });
                log::warn!(
                    "[SmartRouter] {} response body exceeded the routing budget",
                    candidate.internal_id
                );
                break;
            }
        }
    }

    let detail = serde_json::to_value(&attempts).unwrap_or_else(|_| json!([]));
    log::error!("[SmartRouter] all candidates failed: {detail}");
    json_error(
        StatusCode::SERVICE_UNAVAILABLE,
        "All Auto Router models failed",
        Some(detail),
    )
}

#[derive(Debug, Default)]
struct ToolCallBuffer {
    id: String,
    name: String,
    arguments: String,
}

struct AnthropicSseAdapter {
    buffer: String,
    message_id: String,
    text_index: Option<usize>,
    next_block_index: usize,
    tool_calls: BTreeMap<u64, ToolCallBuffer>,
    finish_reason: Option<String>,
    output_tokens: u64,
    finished: bool,
}

impl AnthropicSseAdapter {
    fn new() -> Self {
        Self {
            buffer: String::new(),
            message_id: format!("msg_{}", chrono::Utc::now().timestamp_millis()),
            text_index: None,
            next_block_index: 0,
            tool_calls: BTreeMap::new(),
            finish_reason: None,
            output_tokens: 0,
            finished: false,
        }
    }

    fn start_event(&self) -> Bytes {
        anthropic_sse_event(
            "message_start",
            json!({
                "type": "message_start",
                "message": {
                    "id": self.message_id,
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": SMART_ROUTER_MODEL_ID,
                    "stop_reason": null,
                    "stop_sequence": null,
                    "usage": {"input_tokens": 0, "output_tokens": 0}
                }
            }),
        )
    }

    fn push(&mut self, chunk: &[u8]) -> Vec<Bytes> {
        self.buffer.push_str(&String::from_utf8_lossy(chunk));
        let mut events = Vec::new();
        while let Some(newline) = self.buffer.find('\n') {
            let line = self.buffer[..newline].trim_end_matches('\r').to_string();
            self.buffer.drain(..=newline);
            events.extend(self.process_line(&line));
        }
        events
    }

    fn finish(mut self) -> Vec<Bytes> {
        let mut events = Vec::new();
        if !self.buffer.trim().is_empty() {
            let line = std::mem::take(&mut self.buffer);
            events.extend(self.process_line(line.trim_end_matches('\r')));
        }
        events.extend(self.finish_events());
        events
    }

    fn process_line(&mut self, line: &str) -> Vec<Bytes> {
        let Some(data) = line.strip_prefix("data:").map(str::trim) else {
            return Vec::new();
        };
        if data == "[DONE]" {
            return self.finish_events();
        }
        let Ok(chunk) = serde_json::from_str::<Value>(data) else {
            return Vec::new();
        };

        if let Some(tokens) = chunk
            .get("usage")
            .and_then(|usage| usage.get("completion_tokens"))
            .and_then(Value::as_u64)
        {
            self.output_tokens = tokens;
        }

        let Some(choice) = chunk
            .get("choices")
            .and_then(Value::as_array)
            .and_then(|choices| choices.first())
        else {
            return Vec::new();
        };
        if let Some(reason) = choice.get("finish_reason").and_then(Value::as_str) {
            self.finish_reason = Some(reason.to_string());
        }

        let Some(delta) = choice.get("delta") else {
            return Vec::new();
        };
        let mut events = Vec::new();
        if let Some(text) = delta.get("content").and_then(Value::as_str) {
            if !text.is_empty() {
                let index = match self.text_index {
                    Some(index) => index,
                    None => {
                        let index = self.next_block_index;
                        self.next_block_index += 1;
                        self.text_index = Some(index);
                        events.push(anthropic_sse_event(
                            "content_block_start",
                            json!({
                                "type": "content_block_start",
                                "index": index,
                                "content_block": {"type": "text", "text": ""}
                            }),
                        ));
                        index
                    }
                };
                events.push(anthropic_sse_event(
                    "content_block_delta",
                    json!({
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {"type": "text_delta", "text": text}
                    }),
                ));
            }
        }

        if let Some(tool_calls) = delta.get("tool_calls").and_then(Value::as_array) {
            for tool_call in tool_calls {
                let index = tool_call.get("index").and_then(Value::as_u64).unwrap_or(0);
                let buffered = self.tool_calls.entry(index).or_default();
                if let Some(id) = tool_call.get("id").and_then(Value::as_str) {
                    buffered.id.push_str(id);
                }
                if let Some(function) = tool_call.get("function") {
                    if let Some(name) = function.get("name").and_then(Value::as_str) {
                        buffered.name.push_str(name);
                    }
                    if let Some(arguments) = function.get("arguments").and_then(Value::as_str) {
                        buffered.arguments.push_str(arguments);
                    }
                }
            }
        }
        events
    }

    fn finish_events(&mut self) -> Vec<Bytes> {
        if self.finished {
            return Vec::new();
        }
        self.finished = true;
        let mut events = Vec::new();

        if let Some(index) = self.text_index {
            events.push(anthropic_sse_event(
                "content_block_stop",
                json!({"type": "content_block_stop", "index": index}),
            ));
        }

        for tool_call in self.tool_calls.values() {
            let index = self.next_block_index;
            self.next_block_index += 1;
            let id = if tool_call.id.is_empty() {
                format!("call_{index}")
            } else {
                tool_call.id.clone()
            };
            events.push(anthropic_sse_event(
                "content_block_start",
                json!({
                    "type": "content_block_start",
                    "index": index,
                    "content_block": {
                        "type": "tool_use",
                        "id": id,
                        "name": tool_call.name,
                        "input": {}
                    }
                }),
            ));
            events.push(anthropic_sse_event(
                "content_block_delta",
                json!({
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": if tool_call.arguments.is_empty() {
                            "{}"
                        } else {
                            tool_call.arguments.as_str()
                        }
                    }
                }),
            ));
            events.push(anthropic_sse_event(
                "content_block_stop",
                json!({"type": "content_block_stop", "index": index}),
            ));
        }

        if self.text_index.is_none() && self.tool_calls.is_empty() {
            events.push(anthropic_sse_event(
                "content_block_start",
                json!({
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""}
                }),
            ));
            events.push(anthropic_sse_event(
                "content_block_stop",
                json!({"type": "content_block_stop", "index": 0}),
            ));
        }

        let stop_reason = if !self.tool_calls.is_empty() {
            "tool_use"
        } else {
            match self.finish_reason.as_deref() {
                Some("length") => "max_tokens",
                Some("tool_calls") => "tool_use",
                _ => "end_turn",
            }
        };
        events.push(anthropic_sse_event(
            "message_delta",
            json!({
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": null},
                "usage": {"output_tokens": self.output_tokens}
            }),
        ));
        events.push(anthropic_sse_event(
            "message_stop",
            json!({"type": "message_stop"}),
        ));
        events
    }
}

fn anthropic_sse_event(event: &str, data: Value) -> Bytes {
    Bytes::from(format!("event: {event}\ndata: {data}\n\n"))
}

fn openai_stream_to_anthropic(response: Response) -> Response {
    let routed_via = response.headers().get("X-EchoBird-Routed-Via").cloned();
    let mut source = response.into_body().into_data_stream();
    let (tx, rx) = tokio::sync::mpsc::channel::<Result<Bytes, std::io::Error>>(32);

    tokio::spawn(async move {
        let mut adapter = AnthropicSseAdapter::new();
        if tx.send(Ok(adapter.start_event())).await.is_err() {
            return;
        }
        while let Some(item) = source.next().await {
            match item {
                Ok(chunk) => {
                    for event in adapter.push(&chunk) {
                        if tx.send(Ok(event)).await.is_err() {
                            return;
                        }
                    }
                }
                Err(error) => {
                    let _ = tx.send(Err(std::io::Error::other(error))).await;
                    return;
                }
            }
        }
        for event in adapter.finish() {
            if tx.send(Ok(event)).await.is_err() {
                return;
            }
        }
    });

    anthropic_response(
        StatusCode::OK,
        "text/event-stream",
        Body::from_stream(ReceiverStream::new(rx)),
        routed_via,
    )
}

async fn openai_response_to_anthropic(response: Response) -> Response {
    let routed_via = response.headers().get("X-EchoBird-Routed-Via").cloned();
    let body = match response.into_body().collect().await {
        Ok(collected) => collected.to_bytes(),
        Err(error) => {
            return anthropic_error(
                StatusCode::BAD_GATEWAY,
                &format!("Failed to read Smart Router response: {error}"),
            )
        }
    };
    let data: Value = match serde_json::from_slice(&body) {
        Ok(data) => data,
        Err(error) => {
            return anthropic_error(
                StatusCode::BAD_GATEWAY,
                &format!("Invalid Smart Router response: {error}"),
            )
        }
    };
    let converted = crate::services::local_llm::proxy::openai_to_anthropic(&data);
    anthropic_response(
        StatusCode::OK,
        "application/json",
        Body::from(converted.to_string()),
        routed_via,
    )
}

async fn openai_error_to_anthropic(response: Response) -> Response {
    let status = response.status();
    let body = response
        .into_body()
        .collect()
        .await
        .map(|collected| collected.to_bytes())
        .unwrap_or_default();
    let parsed: Value = serde_json::from_slice(&body).unwrap_or(Value::Null);
    let message = parsed
        .pointer("/error/message")
        .and_then(Value::as_str)
        .unwrap_or("Auto Router request failed");
    anthropic_error(status, message)
}

fn anthropic_error(status: StatusCode, message: &str) -> Response {
    let error_type = match status {
        StatusCode::BAD_REQUEST => "invalid_request_error",
        StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN => "authentication_error",
        StatusCode::TOO_MANY_REQUESTS => "rate_limit_error",
        _ => "api_error",
    };
    anthropic_response(
        status,
        "application/json",
        Body::from(
            json!({
                "type": "error",
                "error": {"type": error_type, "message": message}
            })
            .to_string(),
        ),
        None,
    )
}

fn anthropic_response(
    status: StatusCode,
    content_type: &'static str,
    body: Body,
    routed_via: Option<HeaderValue>,
) -> Response {
    let mut response = Response::builder()
        .status(status)
        .header(header::CONTENT_TYPE, content_type)
        .header(header::CACHE_CONTROL, "no-cache");
    if let Some(routed_via) = routed_via {
        response = response.header("X-EchoBird-Routed-Via", routed_via);
    }
    response.body(body).unwrap_or_else(|_| {
        openai_error(
            StatusCode::INTERNAL_SERVER_ERROR,
            "Failed to build Anthropic router response",
        )
    })
}

fn prioritized_candidates(state: &AppState, candidates: Vec<Candidate>) -> Vec<Candidate> {
    let Ok(mut memory) = state.route_memory.lock() else {
        return candidates;
    };
    let now = now_ms();
    let fingerprints: HashMap<&str, &str> = candidates
        .iter()
        .map(|candidate| {
            (
                candidate.internal_id.as_str(),
                candidate.fingerprint.as_str(),
            )
        })
        .collect();
    let previous_len = memory.candidates.len();
    memory.candidates.retain(|candidate_id, health| {
        fingerprints
            .get(candidate_id.as_str())
            .is_some_and(|fingerprint| health.fingerprint == *fingerprint)
    });
    if memory.candidates.len() != previous_len {
        persist_route_memory(state, &memory);
    }

    let mut available: Vec<Candidate> = candidates
        .into_iter()
        .filter(|candidate| {
            !memory
                .candidates
                .get(&candidate.internal_id)
                .and_then(|health| health.cooldown_until_ms)
                .is_some_and(|until| until > now)
        })
        .collect();
    if let Some(preferred) = memory.last_success_id.as_deref() {
        if let Some(index) = available
            .iter()
            .position(|candidate| candidate.internal_id == preferred)
        {
            let candidate = available.remove(index);
            available.insert(0, candidate);
        }
    }
    available
}

fn mark_success(state: &AppState, candidate: &Candidate) {
    let Ok(mut memory) = state.route_memory.lock() else {
        return;
    };
    let removed_failure = memory.candidates.remove(&candidate.internal_id).is_some();
    let changed_preferred = memory.last_success_id.as_deref() != Some(&candidate.internal_id);
    if changed_preferred {
        memory.last_success_id = Some(candidate.internal_id.clone());
    }
    if removed_failure || changed_preferred {
        persist_route_memory(state, &memory);
    }
}

fn mark_failure(
    state: &AppState,
    candidate: &Candidate,
    failure: FailureClass,
    retry_after: Option<Duration>,
) {
    let Ok(mut memory) = state.route_memory.lock() else {
        return;
    };
    let entry = memory
        .candidates
        .entry(candidate.internal_id.clone())
        .or_default();
    if entry.fingerprint != candidate.fingerprint {
        *entry = CandidateHealth {
            fingerprint: candidate.fingerprint.clone(),
            ..CandidateHealth::default()
        };
    }
    entry.consecutive_failures = entry.consecutive_failures.saturating_add(1);
    entry.failure = Some(failure);
    let cooldown = cooldown_for_failure(failure, retry_after, entry.consecutive_failures);
    entry.cooldown_until_ms =
        Some(now_ms().saturating_add(cooldown.as_millis().min(u128::from(u64::MAX)) as u64));
    persist_route_memory(state, &memory);
}

fn cooldown_for_failure(
    failure: FailureClass,
    retry_after: Option<Duration>,
    consecutive_failures: u32,
) -> Duration {
    match failure {
        FailureClass::Authentication | FailureClass::Billing => AUTH_OR_BILLING_COOLDOWN,
        FailureClass::ModelUnavailable => MODEL_UNAVAILABLE_COOLDOWN,
        FailureClass::RateLimit => retry_after
            .unwrap_or(RATE_LIMIT_COOLDOWN)
            .min(MAX_RETRY_AFTER),
        FailureClass::Transient => {
            let multiplier = 1_u32 << consecutive_failures.saturating_sub(1).min(3);
            TRANSIENT_COOLDOWN
                .saturating_mul(multiplier)
                .min(MAX_TRANSIENT_COOLDOWN)
        }
    }
}

fn remaining_timeout(started: Instant, budget: Duration, cap: Duration) -> Option<Duration> {
    budget
        .checked_sub(started.elapsed())
        .map(|remaining| remaining.min(cap))
        .filter(|remaining| !remaining.is_zero())
}

fn classify_failure(status: StatusCode, body: &[u8]) -> Option<FailureClass> {
    let message = String::from_utf8_lossy(body).to_ascii_lowercase();
    if [
        "content policy",
        "safety policy",
        "content moderation",
        "blocked by safety",
    ]
    .iter()
    .any(|pattern| message.contains(pattern))
    {
        return None;
    }
    if [
        "model_not_found",
        "model not found",
        "model does not exist",
        "model is not available",
        "model unavailable",
        "unknown model",
        "invalid model",
        "model_not_supported",
        "model has been deprecated",
        "model has been decommissioned",
        "does not support tool",
        "tools are not supported",
        "tool use is not supported",
        "function calling is not supported",
    ]
    .iter()
    .any(|pattern| message.contains(pattern))
    {
        return Some(FailureClass::ModelUnavailable);
    }
    if [
        "insufficient quota",
        "insufficient_quota",
        "quota exceeded",
        "credit balance",
        "credits exhausted",
    ]
    .iter()
    .any(|pattern| message.contains(pattern))
    {
        return Some(FailureClass::Billing);
    }
    let status_failure = match status.as_u16() {
        401 | 403 => Some(FailureClass::Authentication),
        402 => Some(FailureClass::Billing),
        404 => Some(FailureClass::ModelUnavailable),
        408 | 409 => Some(FailureClass::Transient),
        429 => Some(FailureClass::RateLimit),
        500..=599 => Some(FailureClass::Transient),
        _ => None,
    };
    if status_failure.is_some() {
        return status_failure;
    }
    if ["rate limit", "rate_limit", "too many requests"]
        .iter()
        .any(|pattern| message.contains(pattern))
    {
        return Some(FailureClass::RateLimit);
    }
    None
}

fn retry_after(headers: &HeaderMap) -> Option<Duration> {
    let value = headers.get(header::RETRY_AFTER)?.to_str().ok()?.trim();
    if let Ok(seconds) = value.parse::<u64>() {
        return Some(Duration::from_secs(seconds).min(MAX_RETRY_AFTER));
    }

    let retry_at = chrono::DateTime::parse_from_rfc2822(value).ok()?;
    let wait = retry_at.signed_duration_since(chrono::Utc::now());
    Some(wait.to_std().unwrap_or_default().min(MAX_RETRY_AFTER))
}

fn chat_completions_url(base_url: &str) -> String {
    let base_url = base_url.trim_end_matches('/');
    if base_url.ends_with("/chat/completions") {
        base_url.to_string()
    } else {
        format!("{base_url}/chat/completions")
    }
}

fn is_authorized(headers: &HeaderMap, expected_key: &str) -> bool {
    let bearer_matches = headers
        .get(header::AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.strip_prefix("Bearer "))
        .is_some_and(|key| key == expected_key);
    bearer_matches
        || headers
            .get("x-api-key")
            .and_then(|value| value.to_str().ok())
            .is_some_and(|key| key == expected_key)
}

fn routed_via(candidate: &Candidate) -> HeaderValue {
    let value = format!("{}/{}", candidate.internal_id, candidate.model_id);
    HeaderValue::from_str(&value).unwrap_or_else(|_| HeaderValue::from_static("echobird/unknown"))
}

fn upstream_response(
    status: StatusCode,
    content_type: Option<HeaderValue>,
    cache_control: Option<HeaderValue>,
    body: Bytes,
    candidate: &Candidate,
) -> Response {
    response_with_headers(
        status,
        content_type,
        cache_control,
        Body::from(body),
        candidate,
    )
}

fn streaming_response(
    content_type: Option<HeaderValue>,
    cache_control: Option<HeaderValue>,
    body: Body,
    candidate: &Candidate,
) -> Response {
    response_with_headers(StatusCode::OK, content_type, cache_control, body, candidate)
}

fn response_with_headers(
    status: StatusCode,
    content_type: Option<HeaderValue>,
    cache_control: Option<HeaderValue>,
    body: Body,
    candidate: &Candidate,
) -> Response {
    let mut response = Response::builder()
        .status(status)
        .header("X-EchoBird-Routed-Via", routed_via(candidate));
    if let Some(content_type) = content_type {
        response = response.header(header::CONTENT_TYPE, content_type);
    }
    if let Some(cache_control) = cache_control {
        response = response.header(header::CACHE_CONTROL, cache_control);
    }
    response.body(body).unwrap_or_else(|_| {
        openai_error(
            StatusCode::INTERNAL_SERVER_ERROR,
            "Failed to build router response",
        )
    })
}

fn openai_error(status: StatusCode, message: &str) -> Response {
    json_error(status, message, None)
}

fn json_error(status: StatusCode, message: &str, attempts: Option<Value>) -> Response {
    let mut error = json!({
        "message": message,
        "type": "echobird_router_error",
        "code": status.as_u16(),
    });
    if let Some(attempts) = attempts {
        error["attempts"] = attempts;
    }
    (status, Json(json!({ "error": error }))).into_response()
}

#[cfg(test)]
mod tests {
    use std::convert::Infallible;
    use std::sync::atomic::{AtomicUsize, Ordering};

    use axum::routing::post;
    use http_body_util::BodyExt;
    use tokio_stream::wrappers::ReceiverStream;

    use super::*;

    fn candidate(addr: SocketAddr, id: &str) -> Candidate {
        let model_id = format!("{id}-model");
        let base_url = format!("http://{addr}/v1");
        let api_key = "upstream-key".to_string();
        Candidate {
            internal_id: id.to_string(),
            fingerprint: candidate_fingerprint(&model_id, &base_url, &api_key),
            model_id,
            base_url,
            api_key,
        }
    }

    fn inbound_headers() -> HeaderMap {
        let mut headers = HeaderMap::new();
        headers.insert(
            header::AUTHORIZATION,
            HeaderValue::from_static("Bearer local-key"),
        );
        headers
    }

    async fn spawn_mock(app: Router) -> SocketAddr {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });
        addr
    }

    #[test]
    fn route_activity_tracks_the_latest_in_flight_candidate() {
        let mut activity = RouteActivity::default();
        let first = activity.begin("first", 10);
        let second = activity.begin("second", 20);

        let snapshot = activity.snapshot();
        assert_eq!(snapshot.candidate_id.as_deref(), Some("second"));
        assert!(snapshot.active);

        activity.end(second, 30);
        let snapshot = activity.snapshot();
        assert_eq!(snapshot.candidate_id.as_deref(), Some("first"));
        assert!(snapshot.active);

        activity.end(first, 40);
        let snapshot = activity.snapshot();
        assert_eq!(snapshot.candidate_id.as_deref(), Some("first"));
        assert!(!snapshot.active);
        assert_eq!(snapshot.sequence, 4);
        assert_eq!(snapshot.updated_at_ms, 40);
    }

    #[test]
    fn classifies_only_failover_worthy_statuses() {
        assert_eq!(
            classify_failure(StatusCode::UNAUTHORIZED, b""),
            Some(FailureClass::Authentication)
        );
        assert_eq!(
            classify_failure(StatusCode::TOO_MANY_REQUESTS, b""),
            Some(FailureClass::RateLimit)
        );
        assert_eq!(
            classify_failure(
                StatusCode::TOO_MANY_REQUESTS,
                br#"{"error":{"code":"insufficient_quota"}}"#
            ),
            Some(FailureClass::Billing)
        );
        assert_eq!(
            classify_failure(StatusCode::REQUEST_TIMEOUT, b""),
            Some(FailureClass::Transient)
        );
        assert_eq!(
            classify_failure(StatusCode::BAD_GATEWAY, b""),
            Some(FailureClass::Transient)
        );
        assert_eq!(
            classify_failure(StatusCode::BAD_REQUEST, b"bad input"),
            None
        );
        assert_eq!(
            classify_failure(StatusCode::FORBIDDEN, b"blocked by safety policy"),
            None
        );
        assert_eq!(
            classify_failure(StatusCode::PAYLOAD_TOO_LARGE, b"too large"),
            None
        );
        assert_eq!(
            classify_failure(StatusCode::BAD_REQUEST, b"model_not_found"),
            Some(FailureClass::ModelUnavailable)
        );
        assert_eq!(
            classify_failure(StatusCode::BAD_REQUEST, b"unknown model"),
            Some(FailureClass::ModelUnavailable)
        );
        assert_eq!(
            classify_failure(StatusCode::BAD_REQUEST, b"insufficient quota"),
            Some(FailureClass::Billing)
        );
    }

    #[test]
    fn accepts_current_and_legacy_router_model_ids() {
        assert!(is_supported_router_model("auto"));
        assert!(is_supported_router_model("echobird/auto"));
        assert!(is_supported_router_model("echobird-auto"));
        assert!(is_supported_router_model("smart-router"));
        assert!(!is_supported_router_model("other-model"));
    }

    #[test]
    fn appends_chat_completions_once() {
        assert_eq!(
            chat_completions_url("https://example.com/v1"),
            "https://example.com/v1/chat/completions"
        );
        assert_eq!(
            chat_completions_url("https://example.com/v1/chat/completions"),
            "https://example.com/v1/chat/completions"
        );
    }

    #[tokio::test]
    async fn sends_openrouter_app_attribution_headers() {
        let upstream = Router::new().route(
            "/v1/chat/completions",
            post(|headers: HeaderMap, Json(body): Json<Value>| async move {
                assert_eq!(headers["HTTP-Referer"], "https://echobird.ai");
                assert_eq!(headers["X-OpenRouter-Title"], "EchoBird");
                assert_eq!(
                    headers["X-OpenRouter-Categories"],
                    "programming-app,personal-agent"
                );
                Json(json!({
                    "id": "chatcmpl-attribution",
                    "model": body["model"],
                    "choices": [{"message": {"role": "assistant", "content": "ok"}}]
                }))
            }),
        );
        let addr = spawn_mock(upstream).await;
        let state = AppState::for_tests().unwrap();
        let response = route_chat_with_candidates(
            &state,
            &inbound_headers(),
            json!({"model": SMART_ROUTER_MODEL_ID, "messages": []}),
            vec![candidate(addr, "openrouter")],
        )
        .await;

        assert_eq!(response.status(), StatusCode::OK);
    }

    #[test]
    fn route_memory_survives_round_trip_and_skips_cooldown() {
        let state = AppState::for_tests().unwrap();
        let addr = SocketAddr::from(([127, 0, 0, 1], 1));
        let first = candidate(addr, "first");
        let second = candidate(addr, "second");

        mark_success(&state, &second);
        let ordered = prioritized_candidates(&state, vec![first.clone(), second.clone()]);
        assert_eq!(ordered[0].internal_id, "second");

        mark_failure(&state, &second, FailureClass::RateLimit, None);
        let serialized = {
            let memory = state.route_memory.lock().unwrap();
            serde_json::to_string(&*memory).unwrap()
        };
        let restored: RouteMemory = serde_json::from_str(&serialized).unwrap();
        let restored_state = AppState {
            http_client: state.http_client.clone(),
            route_memory: Arc::new(Mutex::new(restored)),
            route_memory_path: None,
        };
        let available = prioritized_candidates(&restored_state, vec![first, second]);
        assert_eq!(available.len(), 1);
        assert_eq!(available[0].internal_id, "first");
    }

    #[test]
    fn cooldowns_match_failure_type_and_cap_retry_after() {
        assert_eq!(
            cooldown_for_failure(FailureClass::RateLimit, None, 1),
            Duration::from_secs(60)
        );
        assert_eq!(
            cooldown_for_failure(FailureClass::Transient, None, 4),
            Duration::from_secs(4 * 60)
        );
        assert_eq!(
            cooldown_for_failure(FailureClass::ModelUnavailable, None, 1),
            Duration::from_secs(6 * 60 * 60)
        );
        assert_eq!(
            cooldown_for_failure(FailureClass::RateLimit, Some(Duration::MAX), 1),
            MAX_RETRY_AFTER
        );
    }

    #[test]
    fn parses_retry_after_seconds_and_http_dates() {
        let mut headers = HeaderMap::new();
        headers.insert(header::RETRY_AFTER, HeaderValue::from_static("3600"));
        assert_eq!(retry_after(&headers), Some(Duration::from_secs(3600)));

        let retry_at = chrono::Utc::now() + chrono::Duration::seconds(90);
        let http_date = retry_at.format("%a, %d %b %Y %H:%M:%S GMT").to_string();
        headers.insert(
            header::RETRY_AFTER,
            HeaderValue::from_str(&http_date).unwrap(),
        );
        let parsed = retry_after(&headers).unwrap();
        assert!(parsed >= Duration::from_secs(88));
        assert!(parsed <= Duration::from_secs(90));
    }

    #[test]
    fn expired_transient_cooldown_keeps_failure_streak() {
        let state = AppState::for_tests().unwrap();
        let model = candidate(SocketAddr::from(([127, 0, 0, 1], 1)), "transient");

        mark_failure(&state, &model, FailureClass::Transient, None);
        {
            let mut memory = state.route_memory.lock().unwrap();
            memory
                .candidates
                .get_mut(&model.internal_id)
                .unwrap()
                .cooldown_until_ms = Some(now_ms().saturating_sub(1));
        }
        assert_eq!(prioritized_candidates(&state, vec![model.clone()]).len(), 1);

        mark_failure(&state, &model, FailureClass::Transient, None);
        let memory = state.route_memory.lock().unwrap();
        let health = memory.candidates.get(&model.internal_id).unwrap();
        assert_eq!(health.consecutive_failures, 2);
        let remaining = health.cooldown_until_ms.unwrap().saturating_sub(now_ms());
        assert!(remaining >= Duration::from_secs(59).as_millis() as u64);
    }

    #[tokio::test]
    async fn reaches_twentieth_candidate_after_nineteen_fast_failures() {
        let hits = Arc::new(AtomicUsize::new(0));
        let counter = hits.clone();
        let upstream = Router::new().route(
            "/v1/chat/completions",
            post(move |Json(body): Json<Value>| {
                let attempt = counter.fetch_add(1, Ordering::SeqCst) + 1;
                async move {
                    if attempt < MAX_ROUTE_CANDIDATES {
                        StatusCode::TOO_MANY_REQUESTS.into_response()
                    } else {
                        Json(json!({
                            "id": "chatcmpl-test",
                            "model": body["model"],
                            "choices": [{"message": {"role": "assistant", "content": "ok"}}]
                        }))
                        .into_response()
                    }
                }
            }),
        );
        let addr = spawn_mock(upstream).await;
        let candidates = (0..MAX_ROUTE_CANDIDATES)
            .map(|index| candidate(addr, &format!("candidate-{index}")))
            .collect();
        let state = AppState::for_tests().unwrap();
        let response = route_chat_with_candidates(
            &state,
            &inbound_headers(),
            json!({"model": SMART_ROUTER_MODEL_ID, "messages": []}),
            candidates,
        )
        .await;

        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(hits.load(Ordering::SeqCst), MAX_ROUTE_CANDIDATES);
        assert_eq!(
            response.headers()["X-EchoBird-Routed-Via"],
            "candidate-19/candidate-19-model"
        );
    }

    #[tokio::test]
    async fn fallback_budget_stops_starting_more_candidates() {
        let slow = Router::new().route(
            "/v1/chat/completions",
            post(|| async {
                tokio::time::sleep(Duration::from_millis(100)).await;
                StatusCode::TOO_MANY_REQUESTS
            }),
        );
        let slow_addr = spawn_mock(slow).await;

        let second_hits = Arc::new(AtomicUsize::new(0));
        let second_counter = second_hits.clone();
        let second = Router::new().route(
            "/v1/chat/completions",
            post(move || {
                second_counter.fetch_add(1, Ordering::SeqCst);
                async { StatusCode::OK }
            }),
        );
        let second_addr = spawn_mock(second).await;
        let state = AppState::for_tests().unwrap();
        let response = route_chat_with_policy(
            &state,
            &inbound_headers(),
            json!({"model": SMART_ROUTER_MODEL_ID, "messages": []}),
            vec![
                candidate(slow_addr, "slow"),
                candidate(second_addr, "second"),
            ],
            RoutePolicy {
                max_attempts: MAX_ROUTE_CANDIDATES,
                time_budget: Duration::from_millis(30),
                header_timeout: Duration::from_secs(1),
                first_byte_timeout: Duration::from_secs(1),
            },
        )
        .await;

        assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
        assert_eq!(second_hits.load(Ordering::SeqCst), 0);
    }

    #[tokio::test]
    async fn success_body_cannot_outlive_routing_budget() {
        let hanging = Router::new().route(
            "/v1/chat/completions",
            post(|| async {
                Response::builder()
                    .status(StatusCode::OK)
                    .body(Body::from_stream(stream::pending::<
                        Result<Bytes, Infallible>,
                    >()))
                    .unwrap()
            }),
        );
        let addr = spawn_mock(hanging).await;
        let state = AppState::for_tests().unwrap();
        let routed = tokio::time::timeout(
            Duration::from_millis(500),
            route_chat_with_policy(
                &state,
                &inbound_headers(),
                json!({"model": SMART_ROUTER_MODEL_ID, "messages": []}),
                vec![candidate(addr, "hanging")],
                RoutePolicy {
                    max_attempts: 1,
                    time_budget: Duration::from_millis(30),
                    header_timeout: Duration::from_secs(1),
                    first_byte_timeout: Duration::from_secs(1),
                },
            ),
        )
        .await
        .expect("router exceeded its own budget");

        assert_eq!(routed.status(), StatusCode::SERVICE_UNAVAILABLE);
    }

    #[tokio::test]
    async fn falls_back_after_rate_limit() {
        let first_hits = Arc::new(AtomicUsize::new(0));
        let first_counter = first_hits.clone();
        let first = Router::new().route(
            "/v1/chat/completions",
            post(move || {
                first_counter.fetch_add(1, Ordering::SeqCst);
                async { StatusCode::TOO_MANY_REQUESTS }
            }),
        );
        let first_addr = spawn_mock(first).await;

        let second_hits = Arc::new(AtomicUsize::new(0));
        let second_counter = second_hits.clone();
        let second = Router::new().route(
            "/v1/chat/completions",
            post(move |Json(body): Json<Value>| {
                second_counter.fetch_add(1, Ordering::SeqCst);
                async move {
                    Json(json!({
                        "id": "chatcmpl-test",
                        "model": body["model"],
                        "choices": [{"message": {"role": "assistant", "content": "ok"}}]
                    }))
                }
            }),
        );
        let second_addr = spawn_mock(second).await;

        let state = AppState::for_tests().unwrap();
        let response = route_chat_with_candidates(
            &state,
            &inbound_headers(),
            json!({"model": SMART_ROUTER_MODEL_ID, "messages": [], "stream": false}),
            vec![
                candidate(first_addr, "first"),
                candidate(second_addr, "second"),
            ],
        )
        .await;

        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            response.headers()["X-EchoBird-Routed-Via"],
            "second/second-model"
        );
        let body = response.into_body().collect().await.unwrap().to_bytes();
        let json: Value = serde_json::from_slice(&body).unwrap();
        assert_eq!(json["model"], "second-model");
        assert_eq!(first_hits.load(Ordering::SeqCst), 1);
        assert_eq!(second_hits.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn never_falls_back_after_first_stream_chunk() {
        let first = Router::new().route(
            "/v1/chat/completions",
            post(|| async {
                let (tx, rx) = tokio::sync::mpsc::channel(2);
                tokio::spawn(async move {
                    tx.send(Ok::<Bytes, std::io::Error>(Bytes::from_static(
                        b"data: first\n\n",
                    )))
                    .await
                    .unwrap();
                    tokio::time::sleep(Duration::from_millis(25)).await;
                    let _ = tx.send(Err(std::io::Error::other("stream failed"))).await;
                });
                Response::builder()
                    .status(StatusCode::OK)
                    .header(header::CONTENT_TYPE, "text/event-stream")
                    .body(Body::from_stream(ReceiverStream::new(rx)))
                    .unwrap()
            }),
        );
        let first_addr = spawn_mock(first).await;

        let second_hits = Arc::new(AtomicUsize::new(0));
        let second_counter = second_hits.clone();
        let second = Router::new().route(
            "/v1/chat/completions",
            post(move || {
                second_counter.fetch_add(1, Ordering::SeqCst);
                async { Json(json!({"choices": []})) }
            }),
        );
        let second_addr = spawn_mock(second).await;

        let state = AppState::for_tests().unwrap();
        let response = route_chat_with_candidates(
            &state,
            &inbound_headers(),
            json!({"model": SMART_ROUTER_MODEL_ID, "messages": [], "stream": true}),
            vec![
                candidate(first_addr, "first"),
                candidate(second_addr, "second"),
            ],
        )
        .await;

        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            response.headers()["X-EchoBird-Routed-Via"],
            "first/first-model"
        );
        let collected = response.into_body().collect().await;
        assert!(collected.is_err());
        assert_eq!(second_hits.load(Ordering::SeqCst), 0);
    }

    #[tokio::test]
    async fn falls_back_when_success_stream_has_no_first_byte() {
        let first = Router::new().route(
            "/v1/chat/completions",
            post(|| async {
                Response::builder()
                    .status(StatusCode::OK)
                    .header(header::CONTENT_TYPE, "text/event-stream")
                    .body(Body::empty())
                    .unwrap()
            }),
        );
        let first_addr = spawn_mock(first).await;
        let second = Router::new().route(
            "/v1/chat/completions",
            post(|| async {
                let chunks = stream::once(async {
                    Ok::<Bytes, Infallible>(Bytes::from_static(b"data: second\n\n"))
                });
                Response::builder()
                    .status(StatusCode::OK)
                    .header(header::CONTENT_TYPE, "text/event-stream")
                    .body(Body::from_stream(chunks))
                    .unwrap()
            }),
        );
        let second_addr = spawn_mock(second).await;

        let state = AppState::for_tests().unwrap();
        let response = route_chat_with_candidates(
            &state,
            &inbound_headers(),
            json!({"model": SMART_ROUTER_MODEL_ID, "messages": [], "stream": true}),
            vec![
                candidate(first_addr, "first"),
                candidate(second_addr, "second"),
            ],
        )
        .await;

        assert_eq!(
            response.headers()["X-EchoBird-Routed-Via"],
            "second/second-model"
        );
    }

    #[tokio::test]
    async fn anthropic_request_falls_back_and_preserves_tool_use() {
        let first = Router::new().route(
            "/v1/chat/completions",
            post(|| async { StatusCode::TOO_MANY_REQUESTS }),
        );
        let first_addr = spawn_mock(first).await;
        let second = Router::new().route(
            "/v1/chat/completions",
            post(|Json(body): Json<Value>| async move {
                assert_eq!(body["model"], "second-model");
                assert_eq!(body["tool_choice"], "required");
                Json(json!({
                    "id": "chatcmpl-tool",
                    "model": body["model"],
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": null,
                            "tool_calls": [{
                                "id": "call_weather",
                                "type": "function",
                                "function": {"name": "weather", "arguments": "{\"city\":\"Shanghai\"}"}
                            }]
                        },
                        "finish_reason": "tool_calls"
                    }],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 8}
                }))
            }),
        );
        let second_addr = spawn_mock(second).await;

        let state = AppState::for_tests().unwrap();
        let response = route_messages_with_candidates(
            &state,
            &inbound_headers(),
            json!({
                "model": "claude-opus-5",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": "weather?"}],
                "tools": [{
                    "name": "weather",
                    "description": "Get weather",
                    "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}}
                }],
                "tool_choice": {"type": "any"}
            }),
            vec![
                candidate(first_addr, "first"),
                candidate(second_addr, "second"),
            ],
        )
        .await;

        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            response.headers()["X-EchoBird-Routed-Via"],
            "second/second-model"
        );
        let body = response.into_body().collect().await.unwrap().to_bytes();
        let body: Value = serde_json::from_slice(&body).unwrap();
        assert_eq!(body["type"], "message");
        assert_eq!(body["stop_reason"], "tool_use");
        assert_eq!(body["content"][0]["type"], "tool_use");
        assert_eq!(body["content"][0]["name"], "weather");
        assert_eq!(body["content"][0]["input"]["city"], "Shanghai");
    }

    #[tokio::test]
    async fn anthropic_stream_converts_text_and_tool_events() {
        let upstream = Router::new().route(
            "/v1/chat/completions",
            post(|| async {
                let chunks = stream::iter([
                    Ok::<Bytes, Infallible>(Bytes::from_static(
                        b"data: {\"choices\":[{\"delta\":{\"content\":\"hello\"},\"finish_reason\":null}]}\n\n",
                    )),
                    Ok(Bytes::from_static(
                        b"data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"id\":\"call_1\",\"function\":{\"name\":\"read_file\",\"arguments\":\"{\\\"path\\\":\"}}]},\"finish_reason\":null}]}\n\n",
                    )),
                    Ok(Bytes::from_static(
                        b"data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"function\":{\"arguments\":\"\\\"a.txt\\\"}\"}}]},\"finish_reason\":\"tool_calls\"}],\"usage\":{\"completion_tokens\":9}}\n\n",
                    )),
                    Ok(Bytes::from_static(b"data: [DONE]\n\n")),
                ]);
                Response::builder()
                    .status(StatusCode::OK)
                    .header(header::CONTENT_TYPE, "text/event-stream")
                    .body(Body::from_stream(chunks))
                    .unwrap()
            }),
        );
        let upstream_addr = spawn_mock(upstream).await;

        let state = AppState::for_tests().unwrap();
        let response = route_messages_with_candidates(
            &state,
            &inbound_headers(),
            json!({
                "model": "claude-opus-5",
                "max_tokens": 1024,
                "stream": true,
                "messages": [{"role": "user", "content": "read a file"}]
            }),
            vec![candidate(upstream_addr, "stream")],
        )
        .await;

        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            response.headers()[header::CONTENT_TYPE],
            "text/event-stream"
        );
        let body = response.into_body().collect().await.unwrap().to_bytes();
        let body = String::from_utf8(body.to_vec()).unwrap();
        assert!(body.contains("event: message_start"));
        assert!(body.contains("\"type\":\"text_delta\""));
        assert!(body.contains("\"text\":\"hello\""));
        assert!(body.contains("\"type\":\"tool_use\""));
        assert!(body.contains("\"partial_json\":\"{\\\"path\\\":\\\"a.txt\\\"}\""));
        assert!(body.contains("\"stop_reason\":\"tool_use\""));
        assert!(body.contains("event: message_stop"));
    }
}