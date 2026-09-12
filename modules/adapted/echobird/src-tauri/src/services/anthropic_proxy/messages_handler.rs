use axum::{
    body::Body,
    extract::State,
    http::{header, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    Json,
};
use bytes::Bytes;
use serde_json::{json, Value};
use std::path::PathBuf;

use crate::services::codex_proxy::AppState;

// Anthropic API version pinned by spec; Anthropic's docs say "the latest
// version is automatically used if the header is missing on most
// compatible providers" but it's safer to send an explicit value.
// 2023-06-01 is the long-standing stable header that every compatible
// upstream we ship in modelDirectory.json accepts.
const ANTHROPIC_VERSION: &str = "2023-06-01";

const RELAY_FILENAME: &str = "claudedesktop.json";
const RELAY_FILENAME_CLAUDECODE: &str = "claudecode.json";

struct Relay {
    base_url: String,
    api_key: String,
    /// Upstream's actual model id (e.g. "mimo-v2.5-pro"). When present
    /// we rewrite Claude Desktop's request model field to this. When
    /// absent the request goes through unchanged — works fine for
    /// smart upstreams that auto-route claude-* names.
    real_model_id: Option<String>,
}

/// Claude Desktop route — POST /v1/messages. Relay: claudedesktop.json.
pub async fn handle_messages(state: State<AppState>, body: Bytes) -> Response {
    handle_messages_with(state, body, RELAY_FILENAME).await
}

/// Claude Code route — POST /claudecode/v1/messages. Relay: claudecode.json.
/// A dedicated relay file (not claudedesktop.json) keeps Claude Code and
/// Claude Desktop independent — the user can point each at a different
/// upstream without one clobbering the other, even though both speak the
/// same Anthropic Messages API and would otherwise collide on /v1/messages.
pub async fn handle_messages_claudecode(state: State<AppState>, body: Bytes) -> Response {
    handle_messages_with(state, body, RELAY_FILENAME_CLAUDECODE).await
}

async fn handle_messages_with(
    State(state): State<AppState>,
    body: Bytes,
    relay_filename: &str,
) -> Response {
    let mut req_body: Value = match serde_json::from_slice(&body) {
        Ok(v) => v,
        Err(e) => {
            return (
                StatusCode::BAD_REQUEST,
                Json(json!({
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "message": format!("Invalid JSON body: {}", e),
                    }
                })),
            )
                .into_response();
        }
    };

    let relay = match read_relay(relay_filename) {
        Some(r) => r,
        None => {
            return (
                StatusCode::SERVICE_UNAVAILABLE,
                Json(json!({
                    "type": "error",
                    "error": {
                        "type": "service_unavailable",
                        "message": "No active model configured in EchoBird for this Claude app. Open EchoBird and apply a model.",
                    }
                })),
            )
                .into_response();
        }
    };

    // Model id rewrite — Claude Desktop hard-codes claude-sonnet-4-* /
    // claude-opus-* / claude-haiku-4-*. Strict upstreams need the
    // real id. Smart upstreams ignore this and use their own.
    if let Some(real) = relay.real_model_id.as_deref() {
        let current = req_body.get("model").and_then(|v| v.as_str()).unwrap_or("");
        if !real.is_empty() && real != current {
            log::info!("[AnthropicProxy] Model ID rewrite: {} → {}", current, real);
            req_body["model"] = Value::String(real.to_string());
        }
    }

    // Downstream id hygiene, last step of the conversion: the `[1m]` logical-
    // variant suffix is Claude-client vocabulary and must NEVER reach a
    // third-party upstream. It can still show up here two ways — Claude
    // Code / Desktop sending their built-in `claude-*[1m]` ids straight
    // through (no actualModel in the relay file), or a relay file written by
    // ≤v5.3.8 whose actualModel carries the suffix. Strip it unconditionally.
    let stripped = req_body
        .get("model")
        .and_then(|v| v.as_str())
        .and_then(|m| m.strip_suffix("[1m]"))
        .map(str::to_string);
    if let Some(bare) = stripped {
        log::info!("[AnthropicProxy] Stripped [1m] variant suffix → {}", bare);
        req_body["model"] = Value::String(bare);
    }

    // Reasoning-effort clamp — REQUIRED, do not remove. Claude Code's opus
    // tiers request `output_config.effort: "xhigh"` by default, but
    // third-party Anthropic-compatible upstreams accept only
    // low/medium/high/max and reject the request with a 400
    // ("output_config.effort ... got xhigh instead"), which surfaces to the
    // user as "the model doesn't work". Downgrade xhigh → high (the
    // universally-supported top tier). No-op for any other effort value.
    if let Some(effort) = req_body
        .get_mut("output_config")
        .and_then(|c| c.get_mut("effort"))
    {
        if effort.as_str() == Some("xhigh") {
            log::info!("[AnthropicProxy] Reasoning effort clamp: xhigh → high");
            *effort = Value::String("high".to_string());
        }
    }

    // URL composition matches llm_client.rs:404 — handle every shape
    // users (and our model directory templates) realistically put in
    // the relay's anthropic URL:
    //   1. already includes "/messages"     → use as-is
    //   2. ends with "/v1"                   → append "/messages"
    //      (avoid `/v1/v1/messages` doubling for vLLM/sglang/OpenAI-
    //      style baseURLs that include /v1 — issue #108)
    //   3. otherwise                          → append "/v1/messages"
    //      (canonical Anthropic-spec path)
    let base = relay.base_url.trim_end_matches('/');
    let upstream_url = if base.contains("/messages") {
        base.to_string()
    } else if base.ends_with("/v1") {
        format!("{}/messages", base)
    } else {
        format!("{}/v1/messages", base)
    };
    let is_stream = req_body
        .get("stream")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);

    let upstream_req = state
        .http_client
        .post(&upstream_url)
        .header(header::CONTENT_TYPE, "application/json")
        // Anthropic auth: providers accept either x-api-key or Bearer.
        // Send both — some "compatible" upstreams check the wrong one.
        .header("x-api-key", &relay.api_key)
        .header(header::AUTHORIZATION, format!("Bearer {}", relay.api_key))
        .header("anthropic-version", ANTHROPIC_VERSION)
        .header(
            header::ACCEPT,
            if is_stream {
                "text/event-stream"
            } else {
                "application/json"
            },
        )
        .json(&req_body);

    let upstream_resp = match upstream_req.send().await {
        Ok(r) => r,
        Err(e) => {
            log::error!("[AnthropicProxy] Upstream connect error: {e}");
            return (
                StatusCode::BAD_GATEWAY,
                Json(json!({
                    "type": "error",
                    "error": {
                        "type": "upstream_connect_error",
                        "message": e.to_string(),
                    }
                })),
            )
                .into_response();
        }
    };

    let status = upstream_resp.status();
    let upstream_content_type = upstream_resp
        .headers()
        .get(header::CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("application/json")
        .to_string();

    // Stream upstream body straight back — no parsing, no re-emission.
    // Works for both SSE (text/event-stream) and JSON. SSE keeps its
    // chunked semantics since we never buffer.
    let upstream_stream = upstream_resp.bytes_stream();
    let body = Body::from_stream(upstream_stream);

    let mut response = Response::builder()
        .status(status)
        .body(body)
        .unwrap_or_else(|_| Response::new(Body::empty()));
    if let Ok(ct) = HeaderValue::from_str(&upstream_content_type) {
        response.headers_mut().insert(header::CONTENT_TYPE, ct);
    }
    response
}

fn read_relay(filename: &str) -> Option<Relay> {
    let path = relay_path(filename)?;
    let content = std::fs::read_to_string(&path).ok()?;
    let parsed: Value = serde_json::from_str(&content).ok()?;

    let base_url = parsed
        .get("baseUrl")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())?
        .to_string();
    let api_key = parsed
        .get("apiKey")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())?
        .to_string();
    let real_model_id = parsed
        .get("actualModel")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .map(|s| s.to_string());

    Some(Relay {
        base_url,
        api_key,
        real_model_id,
    })
}

fn relay_path(filename: &str) -> Option<PathBuf> {
    Some(dirs::home_dir()?.join(".echobird").join(filename))
}