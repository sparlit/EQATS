// Chat Completions stream → Responses API SSE translator.
//
// Direct port of tools/codex/lib/stream-handler.cjs. The Node version
// owned a writable HTTP response and called `clientRes.write(...)` for
// each SSE event; the Rust version separates that into:
//
//   1. A pure state machine (`StreamState`) that consumes parsed Chat
//      Completions deltas and emits `SseEvent` values into an internal
//      buffer. Fully synchronous, fully testable.
//   2. An async driver (`drive_chat_stream`) that reads bytes from a
//      reqwest body stream, line-splits SSE, parses JSON, feeds the
//      state machine, and yields events as an `axum::response::sse::Event`
//      stream the handler can return verbatim.
//
// Splitting these two pieces means every translation rule that mattered
// in the .cjs (finish_reason → status, tool-call slot tracking,
// reasoning_content round-trip via SessionStore) has a unit test that
// runs without spinning up a TCP listener or fake HTTP server.

use std::collections::BTreeMap;

use serde_json::{json, Value};

use super::session_store::SessionStore;

// ---------------------------------------------------------------------------
// chat_usage_to_responses_usage — Chat usage shape → Responses usage shape.
// ---------------------------------------------------------------------------
//
// Codex's Rust client parses ResponseCompleted with strict serde and
// crashes with messages like "missing field input_tokens" when fields
// are absent. Chat Completions emits prompt_tokens/completion_tokens;
// Responses API expects the full nested shape:
//
//   {
//     input_tokens: N,
//     input_tokens_details: { cached_tokens: N },
//     output_tokens: N,
//     output_tokens_details: { reasoning_tokens: N },
//     total_tokens: N
//   }
//
// All five top-level fields AND both *_details objects are mandatory.
// We synthesize zeros when upstream omits anything (many third parties
// skip usage on streaming, or only emit prompt_tokens/completion_tokens
// without details).
pub fn chat_usage_to_responses_usage(chat_usage: Option<&Value>) -> Value {
    let u = chat_usage.unwrap_or(&Value::Null);

    let pick_u64 = |obj: &Value, keys: &[&str]| -> u64 {
        for k in keys {
            if let Some(n) = obj.get(*k).and_then(|v| v.as_u64()) {
                return n;
            }
        }
        0
    };

    let input = pick_u64(u, &["input_tokens", "prompt_tokens"]);
    let output = pick_u64(u, &["output_tokens", "completion_tokens"]);
    let total = u
        .get("total_tokens")
        .and_then(|v| v.as_u64())
        .unwrap_or(input + output);

    // Cached input tokens — newer providers nest under prompt_tokens_details.
    let cached_tokens = u
        .get("input_tokens_details")
        .and_then(|v| v.get("cached_tokens"))
        .and_then(|v| v.as_u64())
        .or_else(|| {
            u.get("prompt_tokens_details")
                .and_then(|v| v.get("cached_tokens"))
                .and_then(|v| v.as_u64())
        })
        .or_else(|| u.get("cached_tokens").and_then(|v| v.as_u64()))
        .unwrap_or(0);

    // Reasoning output tokens — for thinking models. Some providers nest
    // under completion_tokens_details, some emit a flat reasoning_tokens.
    let reasoning_tokens = u
        .get("output_tokens_details")
        .and_then(|v| v.get("reasoning_tokens"))
        .and_then(|v| v.as_u64())
        .or_else(|| {
            u.get("completion_tokens_details")
                .and_then(|v| v.get("reasoning_tokens"))
                .and_then(|v| v.as_u64())
        })
        .or_else(|| u.get("reasoning_tokens").and_then(|v| v.as_u64()))
        .unwrap_or(0);

    // Audio tokens — present when models emit speech responses (none of
    // our typical providers do, but spec-conformant emit means Codex's
    // strict usage parser won't trip when it eventually appears).
    let audio_tokens = u
        .get("output_tokens_details")
        .and_then(|v| v.get("audio_tokens"))
        .and_then(|v| v.as_u64())
        .or_else(|| {
            u.get("completion_tokens_details")
                .and_then(|v| v.get("audio_tokens"))
                .and_then(|v| v.as_u64())
        })
        .or_else(|| u.get("audio_tokens").and_then(|v| v.as_u64()))
        .unwrap_or(0);

    // Audio input tokens — speech-to-text style requests.
    let input_audio_tokens = u
        .get("input_tokens_details")
        .and_then(|v| v.get("audio_tokens"))
        .and_then(|v| v.as_u64())
        .or_else(|| {
            u.get("prompt_tokens_details")
                .and_then(|v| v.get("audio_tokens"))
                .and_then(|v| v.as_u64())
        })
        .unwrap_or(0);

    json!({
        "input_tokens": input,
        "input_tokens_details": {
            "cached_tokens": cached_tokens,
            "audio_tokens": input_audio_tokens,
        },
        "output_tokens": output,
        "output_tokens_details": {
            "reasoning_tokens": reasoning_tokens,
            "audio_tokens": audio_tokens,
        },
        "total_tokens": total,
    })
}

// ---------------------------------------------------------------------------
// extract_reasoning_delta — best-effort reasoning capture across providers.
// ---------------------------------------------------------------------------
//
// Returns the reasoning text (if any) hiding in a Chat Completions delta.
// Tries multiple field names + shapes because thinking-mode providers
// haven't standardized on one wire format yet:
//
//   • Plain strings:   delta.reasoning_content / delta.reasoning / delta.thinking
//   • Structured objects:  { type: "text", text: "..." } / { content: "..." }
//   • Arrays of structured parts: [{ text: "..." }, { text: "..." }]
//
// Returns None when no reasoning-like field is present. Concatenates all
// matching paths so providers that emit both reasoning_content AND
// thinking (rare but possible) don't lose either half.
pub(super) fn extract_reasoning_delta(delta: &Value) -> Option<String> {
    let mut out = String::new();
    for key in &["reasoning_content", "reasoning", "thinking"] {
        if let Some(v) = delta.get(*key) {
            append_reasoning_value(v, &mut out);
        }
    }
    if out.is_empty() {
        None
    } else {
        Some(out)
    }
}

fn append_reasoning_value(v: &Value, out: &mut String) {
    match v {
        Value::String(s) if !s.is_empty() => out.push_str(s),
        Value::Object(_) => {
            // {type:"text", text:"..."} | {text:"..."} | {content:"..."}
            for field in &["text", "content"] {
                if let Some(s) = v.get(*field).and_then(|x| x.as_str()) {
                    if !s.is_empty() {
                        out.push_str(s);
                        return;
                    }
                }
            }
        }
        Value::Array(parts) => {
            for p in parts {
                append_reasoning_value(p, out);
            }
        }
        _ => {}
    }
}

// ---------------------------------------------------------------------------
// chat_error_to_responses_error — wrap an upstream error in Responses shape.
// ---------------------------------------------------------------------------
//
// Translates an upstream /chat/completions error response (or transport
// error) into a /responses-shape error envelope that Codex can render.
// We pull out the upstream message text where possible so users see the
// underlying provider error verbatim (e.g. "Invalid API key", "Model not
// found") instead of a generic 502.
pub fn chat_error_to_responses_error(
    status_code: u16,
    upstream_body: Option<&str>,
    sessions: Option<&SessionStore>,
) -> Value {
    let response_id = match sessions {
        Some(s) => s.new_response_id(),
        None => format!(
            "resp_err_{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_millis())
                .unwrap_or(0)
        ),
    };

    let mut message = format!("Upstream returned {status_code}");
    let mut code = format!("upstream_{status_code}");

    if let Some(body) = upstream_body {
        if !body.is_empty() {
            match serde_json::from_str::<Value>(body) {
                Ok(parsed) => {
                    // OpenAI/DeepSeek/etc. nest under .error.{message,code,type};
                    // some providers return flat .message / .detail at the top.
                    let err_obj = parsed.get("error").unwrap_or(&parsed);
                    if let Some(s) = err_obj.get("message").and_then(|v| v.as_str()) {
                        message = s.to_string();
                    } else if let Some(s) = err_obj.get("detail").and_then(|v| v.as_str()) {
                        message = s.to_string();
                    }
                    if let Some(s) = err_obj.get("code").and_then(|v| v.as_str()) {
                        code = s.to_string();
                    } else if let Some(s) = err_obj.get("type").and_then(|v| v.as_str()) {
                        code = s.to_string();
                    }
                }
                Err(_) => {
                    // Body wasn't JSON — surface the raw text (truncated)
                    // so the user still gets *something* instead of just
                    // the status code.
                    let take = body.len().min(500);
                    message = body[..take].to_string();
                }
            }
        }
    }

    // Friendly-rewrite context-overflow 400s. Every provider phrases this
    // differently ("context length exceeded", "input too long",
    // "上下文过长", etc.) so we keyword-match across EN + zh-Hans and
    // swap the cryptic upstream wording for actionable advice. Only on
    // 400 — a 4xx on long context, never a 5xx (5xx means upstream
    // crashed; preserve verbatim so users see the real reason).
    if status_code == 400 && looks_like_context_overflow(&message) {
        message = "对话上下文已超出模型限制，请新建对话或精简历史后再试。 / The conversation history exceeds the model's context window — please start a new chat or trim earlier turns.".to_string();
        code = "context_length_exceeded".to_string();
    }

    // Friendly-rewrite "model can't see images" 400s. Cheap lite/flash
    // variants (deepseek-v4-flash, mimo-v2-flash, qwen-flash, base
    // deepseek-chat, etc.) reject image_url content with provider-
    // specific phrasing — bilingual keyword match catches the common
    // shapes and tells the user to switch to a vision-capable model.
    if status_code == 400 && looks_like_image_unsupported(&message) {
        message = "当前模型不支持图像输入，请切换到支持视觉的版本（如 *-pro / *-vl / *-omni 系列）。 / This model doesn't support image input — please switch to a vision-capable variant (e.g. *-pro, *-vl, *-omni).".to_string();
        code = "image_unsupported".to_string();
    }

    // Normalize the error code so Codex's specialized error-handling UI
    // fires (quota / overloaded / cyber-policy). Codex matches on
    // specific strings ("rate_limit_exceeded", "server_overloaded",
    // "cyber_policy", etc.) — upstream provider error codes vary widely,
    // so we map common shapes onto Codex's expected vocabulary.
    code = normalize_error_code(&code, status_code, &message);

    json!({
        "id": response_id,
        "object": "response",
        "status": "failed",
        "error": { "code": code, "message": message },
        "output": [],
    })
}

// Keyword/regex-less detection of "your context window is full" 400s.
// Bilingual because the user base spans EN + zh. Substring match keeps
// it cheap; false positives just mean a user-friendlier error for a
// non-overflow 400, which is acceptable.
fn looks_like_context_overflow(msg: &str) -> bool {
    let m = msg.to_lowercase();
    // English phrasings
    let en_hits = [
        "context length",
        "context window",
        "context_length",
        "maximum context",
        "input is too long",
        "too many tokens",
        "exceeds the maximum",
        "prompt is too long",
        "tokens exceed",
        "tokens exceeded",
    ];
    if en_hits.iter().any(|p| m.contains(p)) {
        return true;
    }
    // Chinese phrasings — match on raw `msg` not the lowercased copy
    // (CJK has no case, and lowercasing doesn't affect them anyway).
    let zh_hits = [
        "上下文过长",
        "上下文超长",
        "上下文超出",
        "输入过长",
        "输入超长",
        "超出最大长度",
        "超过最大",
        "请缩短",
        "token 数过多",
        "tokens 过多",
        "上下文长度",
    ];
    zh_hits.iter().any(|p| msg.contains(p))
}

// Map a (raw upstream code, HTTP status, message) tuple onto an error
// code Codex's UI recognizes. Codex's error-event consumer in
// `codex-rs/codex-api/src/sse/responses.rs` matches on specific
// strings: "context_length_exceeded", "rate_limit_exceeded",
// "server_overloaded", "cyber_policy", "invalid_prompt",
// "usage_not_included". Upstream providers use varied vocabulary
// (DeepSeek: "insufficient_quota"; MiMo: "billing_hard_limit"; Qwen:
// "RequestRateLimit"; etc.) — map them onto Codex's expected set so
// the right error UI surfaces.
//
// Preserves the upstream code on no-match so unknown errors still
// carry useful information for diagnostics.
fn normalize_error_code(upstream_code: &str, status_code: u16, message: &str) -> String {
    let low_msg = message.to_lowercase();
    let low_code = upstream_code.to_lowercase();

    // Already-normalized — pass through.
    let canonical = [
        "context_length_exceeded",
        "rate_limit_exceeded",
        "server_overloaded",
        "cyber_policy",
        "invalid_prompt",
        "usage_not_included",
        "image_unsupported",
    ];
    if canonical.iter().any(|c| &low_code == c) {
        return upstream_code.to_string();
    }

    // Rate-limit / quota family.
    let rate_limit_signals = [
        "rate_limit",
        "ratelimit",
        "rate-limit",
        "too_many_requests",
        "insufficient_quota",
        "insufficient_credit",
        "quota_exceeded",
        "billing_hard_limit",
        "balance",
    ];
    if status_code == 429
        || rate_limit_signals.iter().any(|p| low_code.contains(p))
        || rate_limit_signals.iter().any(|p| low_msg.contains(p))
    {
        return "rate_limit_exceeded".to_string();
    }

    // Server overload / unavailable family.
    let overload_signals = [
        "server_overloaded",
        "overloaded",
        "service_unavailable",
        "server_busy",
        "try_again_later",
    ];
    if status_code == 503
        || status_code == 529
        || overload_signals.iter().any(|p| low_code.contains(p))
        || overload_signals.iter().any(|p| low_msg.contains(p))
    {
        return "server_overloaded".to_string();
    }

    // Safety / content-policy family. Provider-specific names vary widely
    // — match a broad keyword set so the cyber_policy UI fires.
    let policy_signals = [
        "content_policy",
        "content_filter",
        "safety_violation",
        "policy_violation",
        "cyber_policy",
        "moderation",
        "responsible_ai",
        "敏感",
        "违规",
    ];
    if policy_signals.iter().any(|p| low_code.contains(p))
        || policy_signals.iter().any(|p| low_msg.contains(p))
        || message.contains("敏感")
        || message.contains("违规")
    {
        return "cyber_policy".to_string();
    }

    // Default: keep whatever upstream said. Empty codes fall back to
    // the http status — preserves the diagnostic.
    if upstream_code.is_empty() {
        format!("upstream_{status_code}")
    } else {
        upstream_code.to_string()
    }
}

// Detect "this model can't accept images" 400s across providers. Same
// bilingual substring strategy as looks_like_context_overflow — false
// positives just yield a user-friendlier error message on a 400, which
// is acceptable. Only matches on 400s where the upstream specifically
// names image/vision/multimodal terms; ordinary 400s pass through.
fn looks_like_image_unsupported(msg: &str) -> bool {
    let m = msg.to_lowercase();
    let en_hits = [
        "does not support image",
        "image not supported",
        "image is not supported",
        "vision is not supported",
        "does not support vision",
        "not multimodal",
        "no vision",
        "image input is not",
        "image_url is not",
        "image is unsupported",
        "model does not support multimodal",
        // DeepSeek's text-only chat/reasoner/v4 lineup rejects image
        // content parts with a JSON-deserialize-error wording rather
        // than a "model doesn't support" message. Catch the structural
        // signal: any `image_url` mention combined with deserialize-
        // failure vocabulary ("unknown variant", "expected", "invalid
        // type") means the provider's strict schema doesn't accept
        // image parts.
        "unknown variant `image_url`",
        "unknown variant \"image_url\"",
        "unknown variant 'image_url'",
        "unknown field `image_url`",
        "invalid type: image_url",
    ];
    if en_hits.iter().any(|p| m.contains(p)) {
        return true;
    }
    // Combo check: image_url referenced alongside common deserialization
    // error verbs. Avoids false positives on benign image_url mentions.
    if m.contains("image_url")
        && (m.contains("expected")
            || m.contains("deserialize")
            || m.contains("invalid")
            || m.contains("unknown"))
    {
        return true;
    }
    let zh_hits = [
        "不支持图像",
        "不支持图片",
        "不支持视觉",
        "不支持多模态",
        "不支持 image",
        "图片输入不支持",
        "图像输入不支持",
        "不支持视频",
    ];
    zh_hits.iter().any(|p| msg.contains(p))
}

// ---------------------------------------------------------------------------
// chat_to_responses_non_stream — single-shot translation, no SSE.
// ---------------------------------------------------------------------------
pub fn chat_to_responses_non_stream(
    chat_response: &Value,
    request_messages: Vec<Value>,
    sessions: &SessionStore,
    client_model: Option<&str>,
    store: bool,
) -> Value {
    let response_id = sessions.new_response_id();
    let choice = chat_response
        .get("choices")
        .and_then(|v| v.get(0))
        .cloned()
        .unwrap_or(Value::Null);
    let msg = choice.get("message").cloned().unwrap_or(Value::Null);

    let mut output: Vec<Value> = Vec::new();
    if let Some(content) = msg.get("content").and_then(|v| v.as_str()) {
        if !content.is_empty() {
            output.push(json!({
                "id": format!("item_{}_0", response_id),
                "type": "message",
                "role": "assistant",
                "content": [{ "type": "output_text", "text": content }],
            }));
        }
    }
    // Drop tool_calls with an empty/absent function name up front: a
    // nameless function_call is unroutable by Codex. Filtering here means
    // both the response `output` and the persisted-history `tool_calls`
    // below stay consistent, and the `tool_calls.is_empty()` branch falls
    // back to a plain assistant message when nothing survives.
    let tool_calls: Vec<Value> = msg
        .get("tool_calls")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .filter(|tc| {
            let named = tc
                .get("function")
                .and_then(|f| f.get("name"))
                .and_then(|v| v.as_str())
                .map(|n| !n.trim().is_empty())
                .unwrap_or(false);
            if !named {
                log::warn!("[CodexProxy] Skipping non-stream tool_call with empty function name");
            }
            named
        })
        .collect();
    for tc in &tool_calls {
        let id = tc.get("id").and_then(|v| v.as_str()).unwrap_or("");
        let name = tc
            .get("function")
            .and_then(|v| v.get("name"))
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let arguments = tc
            .get("function")
            .and_then(|v| v.get("arguments"))
            .and_then(|v| v.as_str())
            .unwrap_or("");
        output.push(json!({
            "id": id,
            "type": "function_call",
            "call_id": id,
            "name": name,
            "arguments": arguments,
        }));
    }

    // Persist reasoning + history (same shape as the streaming path so
    // a follow-up request with previous_response_id replays consistently).
    let mut assistant_msg = serde_json::Map::new();
    assistant_msg.insert("role".into(), Value::String("assistant".into()));
    if tool_calls.is_empty() {
        let content = msg
            .get("content")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        assistant_msg.insert("content".into(), Value::String(content));
    } else {
        // Preserve text prelude alongside tool_calls so a next-turn
        // previous_response_id replay sees the same plan/rationale the
        // model emitted (Chat Completions allows both fields together).
        let content_value = msg
            .get("content")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .map(|s| Value::String(s.to_string()))
            .unwrap_or(Value::Null);
        assistant_msg.insert("content".into(), content_value);
        let normalized: Vec<Value> = tool_calls
            .iter()
            .map(|tc| {
                let id = tc.get("id").and_then(|v| v.as_str()).unwrap_or("");
                let name = tc
                    .get("function")
                    .and_then(|v| v.get("name"))
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                let args = tc
                    .get("function")
                    .and_then(|v| v.get("arguments"))
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                json!({
                    "id": id,
                    "type": "function",
                    "function": { "name": name, "arguments": args },
                })
            })
            .collect();
        assistant_msg.insert("tool_calls".into(), Value::Array(normalized));
    }

    if let Some(reasoning) = msg.get("reasoning_content").and_then(|v| v.as_str()) {
        if !reasoning.is_empty() {
            assistant_msg.insert(
                "reasoning_content".into(),
                Value::String(reasoning.to_string()),
            );
            if !tool_calls.is_empty() {
                for tc in &tool_calls {
                    if let Some(id) = tc.get("id").and_then(|v| v.as_str()) {
                        sessions.store_reasoning(id, reasoning);
                    }
                }
            }
            if let Some(content) = msg.get("content").and_then(|v| v.as_str()) {
                if !content.is_empty() {
                    sessions.store_turn_reasoning(&Value::String(content.to_string()), reasoning);
                }
            }
        }
    }

    if store {
        let mut history = request_messages;
        history.push(Value::Object(assistant_msg));
        sessions.save_history(&response_id, history);
    }

    // "length" finish_reason → mark as incomplete so Codex can show the
    // response was truncated rather than treating it as a clean stop.
    let finish_reason = choice
        .get("finish_reason")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let status = if finish_reason == "length" {
        "incomplete"
    } else {
        "completed"
    };

    let mut response = json!({
        "id": response_id,
        "object": "response",
        "status": status,
        "output": output,
    });
    if let Some(m) = client_model {
        response["model"] = Value::String(m.to_string());
    }
    response["usage"] = chat_usage_to_responses_usage(chat_response.get("usage"));
    if finish_reason == "length" {
        response["incomplete_details"] = json!({ "reason": "max_output_tokens" });
    }
    response
}

// ---------------------------------------------------------------------------
// Streaming state machine
// ---------------------------------------------------------------------------

/// One Server-Sent Event. `event` is the `event:` line, `data` becomes
/// the JSON-serialized `data:` line. The axum handler converts these
/// to `axum::response::sse::Event` 1:1.
#[derive(Debug, Clone, PartialEq)]
pub struct SseEvent {
    pub event: String,
    pub data: Value,
}

impl SseEvent {
    pub fn new(event: impl Into<String>, data: Value) -> Self {
        Self {
            event: event.into(),
            data,
        }
    }

    /// Serialize to wire format (`event: ...\ndata: {...}\n\n`). Only
    /// used by tests that want to assert exact bytes — the production
    /// path goes through axum's `Sse` adapter, not this helper.
    #[cfg(test)]
    pub fn to_wire(&self) -> String {
        format!("event: {}\ndata: {}\n\n", self.event, self.data)
    }
}

#[derive(Debug, Clone)]
struct ToolCallSlot {
    id: String,
    name: String,
    arguments: String,
    output_index: i64,
    /// Whether `response.output_item.added` has been emitted for this slot.
    /// Deferred until a non-empty `name` is known: some providers send the
    /// call `id` in the first delta and the function `name` in a later one,
    /// and a few emit a tool_call that never carries a name at all. Holding
    /// `added` until the name materializes keeps us from announcing (or, on
    /// the never-named path, leaking) an empty-named function_call to Codex,
    /// which can't route it.
    added_emitted: bool,
    /// Bytes of `arguments` already forwarded via
    /// `function_call_arguments.delta`. While `added` is still deferred we
    /// keep accumulating arguments without streaming them; once `added`
    /// fires we flush everything past this offset in one delta, then resume
    /// incremental forwarding. Always lands on a provider-delta boundary
    /// (hence a UTF-8 char boundary), so slicing `arguments[..]` is safe.
    streamed_args_len: usize,
}

/// Streaming translator state. Owns the partial buffer, the current
/// text/tool slots, accumulated usage/finish_reason, and a queue of
/// pending SSE events. Drain via `take_events()` after each `feed_chunk()`.
pub struct StreamState {
    response_id: String,
    client_model: Option<String>,
    request_messages: Vec<Value>,
    text_open: bool,
    text_idx: i64,
    text_buf: String,
    /// `delta.annotations[]` accumulated across Chat deltas. OpenAI's
    /// search-preview / `web_search_options` Chat extension returns
    /// `{ type: "url_citation", url_citation: { url, title, start_index,
    /// end_index } }` items here, and Responses' `output_text.annotations[]`
    /// uses the same shape — so we just pass them through verbatim on
    /// `content_part.done` / `output_item.done`. Provider-specific shapes
    /// (Perplexity-style top-level `citations`, MiMo private builtin
    /// output, etc.) are intentionally NOT translated — that would be
    /// per-vendor shimming.
    text_annotations: Vec<Value>,
    /// Refusal item streaming state. Mirrors text-item handling but
    /// for the `refusal` content-part type. When upstream Chat emits
    /// `delta.refusal: "..."` (model declined for safety), we synthesize
    /// the Responses-API refusal event sequence so Codex shows the
    /// refusal text instead of an empty assistant message. Mutually
    /// exclusive with text/reasoning in practice — opens close any
    /// other in-flight item first.
    refusal_open: bool,
    refusal_idx: i64,
    refusal_buf: String,
    /// CUMULATIVE reasoning across the WHOLE response — every burst
    /// concatenated. Feeds the final assembled output + SessionStore
    /// round-trip (next-turn replay needs the model's complete
    /// reasoning). NOT used for per-panel summaries — see `reasoning_seg`.
    reasoning_buf: String,
    /// Current open reasoning panel's text ONLY. Reset every time a
    /// reasoning item closes, so each Codex "thinking" panel summarizes
    /// just its own burst. Without this, interleaved reasoning↔content
    /// made every panel re-print all earlier bursts (cumulative leak).
    reasoning_seg: String,
    /// `reasoning` output item open in the SSE stream. We synthesize the
    /// item + summary_text events so Codex's UI gets a "thinking..."
    /// panel when a thinking-mode upstream streams reasoning_content
    /// deltas. Opened on first reasoning delta, closed on first
    /// non-reasoning delta or at finish.
    reasoning_open: bool,
    reasoning_idx: i64,
    tool_calls: BTreeMap<i64, ToolCallSlot>,
    /// Order of tool-call insertion (chat delta index). Iterating
    /// `tool_calls.values()` in insertion order matters because Codex
    /// keys on it for replay.
    tool_call_order: Vec<i64>,
    next_output_index: i64,
    buffer: String,
    finished: bool,
    usage: Option<Value>,
    finish_reason: Option<String>,
    /// Echoed verbatim on `response.completed`. OpenAI uses
    /// `system_fingerprint` as an opaque cache-key for backend
    /// configuration — clients can detect when the upstream config
    /// changed between calls. `service_tier` reports which billing tier
    /// the request actually ran on (may differ from requested when
    /// OpenAI auto-downgrades). Both are passthroughs — no
    /// interpretation, no validation, no defaulting.
    system_fingerprint: Option<String>,
    service_tier: Option<String>,
    /// When the client requested `store: false` (ZDR / stateless mode),
    /// we MUST NOT persist the conversation history under our response
    /// id. The reasoning-by-call_id side-channel still operates (it's
    /// per-tool-call, not per-response). Default true = matches default
    /// OpenAI behavior (store=true).
    store: bool,
    /// Owned clone of the session store. Held here so `finish_internal`
    /// can persist history BEFORE emitting `response.completed`, closing
    /// a race where Codex's next /v1/responses POST (with
    /// previous_response_id) arrives before the outer driver loop
    /// reaches `state.finish(&sessions)`. SessionStore is cheap to
    /// clone — internally an Arc<Mutex<Inner>>.
    sessions: SessionStore,
    events: Vec<SseEvent>,
}

impl StreamState {
    pub fn new(
        sessions: &SessionStore,
        client_model: Option<String>,
        request_messages: Vec<Value>,
    ) -> Self {
        Self {
            response_id: sessions.new_response_id(),
            client_model,
            request_messages,
            text_open: false,
            text_idx: -1,
            text_buf: String::new(),
            text_annotations: Vec::new(),
            refusal_open: false,
            refusal_idx: -1,
            refusal_buf: String::new(),
            reasoning_buf: String::new(),
            reasoning_seg: String::new(),
            reasoning_open: false,
            reasoning_idx: -1,
            tool_calls: BTreeMap::new(),
            tool_call_order: Vec::new(),
            next_output_index: 0,
            buffer: String::new(),
            finished: false,
            usage: None,
            system_fingerprint: None,
            service_tier: None,
            store: true,
            sessions: sessions.clone(),
            finish_reason: None,
            events: Vec::new(),
        }
    }

    #[allow(dead_code)]
    pub fn response_id(&self) -> &str {
        &self.response_id
    }

    /// Honor the request's `store: false` flag. When set, persist_history
    /// becomes a no-op so we don't retain the conversation under our
    /// response id (ZDR / stateless mode contract).
    pub fn set_store(&mut self, store: bool) {
        self.store = store;
    }

    /// Emit the opening lifecycle events: `response.queued` →
    /// `response.created` → `response.in_progress`. Codex's Rust client
    /// only strictly requires `response.created`, but the spec orders
    /// queued first and Codex GUI / background mode parsers expect it.
    /// Cost is one extra event; safer to be conformant.
    pub fn start(&mut self) {
        self.emit(
            "response.queued",
            json!({
                "type": "response.queued",
                "response": self.stamp_model(json!({
                    "id": self.response_id,
                    "object": "response",
                    "status": "queued",
                    "output": [],
                })),
            }),
        );
        self.emit(
            "response.created",
            json!({
                "type": "response.created",
                "response": self.stamp_model(json!({
                    "id": self.response_id,
                    "object": "response",
                    "status": "in_progress",
                    "output": [],
                })),
            }),
        );
        self.emit(
            "response.in_progress",
            json!({
                "type": "response.in_progress",
                "response": self.stamp_model(json!({
                    "id": self.response_id,
                    "object": "response",
                    "status": "in_progress",
                })),
            }),
        );
    }

    /// Append a chunk of bytes from the upstream stream. Splits on
    /// newlines, ignores non-`data:` lines, parses each JSON payload,
    /// and feeds the state machine. Returns immediately after `[DONE]`.
    pub fn feed_chunk(&mut self, chunk: &str) {
        if self.finished {
            return;
        }
        self.buffer.push_str(chunk);
        // Split on '\n', keeping the trailing partial line buffered for
        // the next call. We copy lines out as owned Strings so we don't
        // hold an immutable borrow on self.buffer while invoking
        // handle_line (which mutates self).
        let mut lines: Vec<String> = Vec::new();
        let mut remainder = String::new();
        {
            let mut iter = self.buffer.split('\n').peekable();
            while let Some(line) = iter.next() {
                if iter.peek().is_none() {
                    // Last segment may be a partial line — keep it in the
                    // buffer for the next chunk.
                    remainder = line.to_string();
                } else {
                    lines.push(line.to_string());
                }
            }
        }
        self.buffer = remainder;
        for line in lines {
            self.handle_line(&line);
            if self.finished {
                break;
            }
        }
    }

    fn handle_line(&mut self, line: &str) {
        let line = line.trim_end_matches('\r');
        // Per the SSE spec (HTML §9.2.6) the space after `data:` is
        // optional; some providers (and proxies) emit `data:{...}` with
        // no space. Accept both forms.
        let payload = match line.strip_prefix("data:") {
            Some(rest) => rest,
            None => return,
        };
        let data = payload.trim();
        if data.is_empty() {
            return;
        }
        if data == "[DONE]" {
            self.finish_internal();
            return;
        }
        let parsed: Value = match serde_json::from_str(data) {
            Ok(v) => v,
            Err(_) => return,
        };

        // Capture usage / finish_reason on any chunk that includes them.
        // OpenAI emits usage as a trailing event when include_usage=true;
        // other providers attach it to the final delta chunk.
        if let Some(u) = parsed.get("usage") {
            if !u.is_null() {
                self.usage = Some(u.clone());
            }
        }
        if let Some(fr) = parsed
            .get("choices")
            .and_then(|v| v.get(0))
            .and_then(|c| c.get("finish_reason"))
            .and_then(|v| v.as_str())
        {
            self.finish_reason = Some(fr.to_string());
        }

        // Capture envelope-level fields for echo on response.completed.
        // These sit on the chunk root (not inside choices/delta) and OpenAI
        // repeats them across chunks — last-write-wins is fine.
        if let Some(sf) = parsed.get("system_fingerprint").and_then(|v| v.as_str()) {
            self.system_fingerprint = Some(sf.to_string());
        }
        if let Some(st) = parsed.get("service_tier").and_then(|v| v.as_str()) {
            self.service_tier = Some(st.to_string());
        }

        let delta = match parsed
            .get("choices")
            .and_then(|v| v.get(0))
            .and_then(|c| c.get("delta"))
        {
            Some(d) => d.clone(),
            None => return,
        };

        // Reasoning delta — thinking-mode providers stream their
        // "internal monologue" alongside content. We do TWO things now:
        //  1. Accumulate into reasoning_buf for SessionStore round-trip
        //     (existing behavior — keeps next turn's request valid)
        //  2. Synthesize the Responses-API reasoning_summary_* SSE
        //     events so Codex shows a "thinking" panel in the UI
        //
        // Field-name + shape variants we've seen in the wild:
        //   • DeepSeek-V4 / Kimi-K2.6 / MiMo-V2.5: `reasoning_content` string
        //   • Some MiMo deployments: `reasoning` string
        //   • Anthropic-bridged: `thinking` string
        //   • Structured form: `reasoning_content: { type, text }`
        //     (or array of such parts; we concatenate the text fields)
        if let Some(r) = extract_reasoning_delta(&delta) {
            if !self.reasoning_open {
                self.open_reasoning_item();
            }
            self.reasoning_buf.push_str(&r);
            self.reasoning_seg.push_str(&r);
            let idx = self.reasoning_idx;
            self.emit(
                "response.reasoning_summary_text.delta",
                json!({
                    "type": "response.reasoning_summary_text.delta",
                    "output_index": idx,
                    "summary_index": 0,
                    "delta": r,
                }),
            );
        }

        // Text delta
        if let Some(content) = delta.get("content").and_then(|v| v.as_str()) {
            if !content.is_empty() {
                if self.reasoning_open {
                    self.close_reasoning_item();
                }
                if self.refusal_open {
                    self.close_refusal_item();
                }
                if !self.text_open {
                    self.open_text_item();
                }
                self.text_buf.push_str(content);
                let idx = self.text_idx;
                self.emit(
                    "response.output_text.delta",
                    json!({
                        "type": "response.output_text.delta",
                        "output_index": idx,
                        "content_index": 0,
                        "delta": content,
                    }),
                );
            }
        }

        // Annotation delta (OpenAI search-preview Chat extension). Same
        // shape as Responses' `output_text.annotations[]` so just append
        // verbatim; we'll flush the full list on content_part.done /
        // output_item.done. See `text_annotations` doc on StreamState
        // for why only OpenAI-shape annotations are passed through.
        if let Some(anns) = delta.get("annotations").and_then(|v| v.as_array()) {
            for ann in anns {
                if ann.is_object() {
                    self.text_annotations.push(ann.clone());
                }
            }
        }

        // Refusal delta. When the model declines for safety, upstream
        // sends `delta.refusal: "I can't help with that."` instead of
        // (or in rare cases alongside) content. Synthesize the
        // Responses-API refusal event sequence so Codex surfaces the
        // refusal text instead of an empty assistant message. See
        // `refusal_open` doc on StreamState for mutual-exclusion
        // semantics with text/reasoning.
        if let Some(refusal) = delta.get("refusal").and_then(|v| v.as_str()) {
            if !refusal.is_empty() {
                if self.reasoning_open {
                    self.close_reasoning_item();
                }
                if self.text_open {
                    self.close_text_item();
                }
                if !self.refusal_open {
                    self.open_refusal_item();
                }
                self.refusal_buf.push_str(refusal);
                let idx = self.refusal_idx;
                self.emit(
                    "response.refusal.delta",
                    json!({
                        "type": "response.refusal.delta",
                        "output_index": idx,
                        "content_index": 0,
                        "delta": refusal,
                    }),
                );
            }
        }

        // Tool-call deltas. Chat splits arguments into multiple delta
        // chunks; we forward each one as a Responses arguments delta.
        if let Some(tcs) = delta.get("tool_calls").and_then(|v| v.as_array()) {
            if self.reasoning_open {
                self.close_reasoning_item();
            }
            if self.text_open {
                self.close_text_item();
            }
            if self.refusal_open {
                self.close_refusal_item();
            }
            for tc in tcs {
                let idx = tc.get("index").and_then(|v| v.as_i64()).unwrap_or(0);
                if !self.tool_calls.contains_key(&idx) {
                    self.open_tool_call(idx, tc);
                }
                // Update name + accumulate arguments first; we can't hold the
                // &mut slot across the emit() calls below.
                {
                    let slot = self.tool_calls.get_mut(&idx).expect("just inserted");
                    // The id is locked at open_tool_call time so the
                    // output_item.added event and every subsequent
                    // function_call_arguments.delta reference the same id.
                    // Some providers omit `id` on the first delta and supply
                    // it later; swapping here would orphan the arg deltas.
                    if let Some(name) = tc
                        .get("function")
                        .and_then(|v| v.get("name"))
                        .and_then(|v| v.as_str())
                    {
                        if slot.name.is_empty() && !name.is_empty() {
                            slot.name = name.to_string();
                        }
                    }
                    if let Some(args) = tc
                        .get("function")
                        .and_then(|v| v.get("arguments"))
                        .and_then(|v| v.as_str())
                    {
                        if !args.is_empty() {
                            slot.arguments.push_str(args);
                        }
                    }
                }
                // The name may have just arrived on a later delta — emit the
                // deferred `added` now so Codex learns about the item before
                // it receives any argument deltas for it.
                self.emit_tool_call_added(idx);
                // Forward newly-accumulated arguments, but only once `added`
                // has fired. Flush everything past streamed_args_len so a
                // slot whose `added` was deferred ships its backlog in one
                // delta, then resumes incremental forwarding.
                let pending = self.tool_calls.get(&idx).and_then(|slot| {
                    if slot.added_emitted && slot.arguments.len() > slot.streamed_args_len {
                        Some((
                            slot.output_index,
                            slot.id.clone(),
                            slot.arguments[slot.streamed_args_len..].to_string(),
                        ))
                    } else {
                        None
                    }
                });
                if let Some((out_idx, item_id, delta)) = pending {
                    if let Some(slot) = self.tool_calls.get_mut(&idx) {
                        slot.streamed_args_len = slot.arguments.len();
                    }
                    self.emit(
                        "response.function_call_arguments.delta",
                        json!({
                            "type": "response.function_call_arguments.delta",
                            "output_index": out_idx,
                            "item_id": item_id,
                            "delta": delta,
                        }),
                    );
                }
            }
        }
    }

    /// Mark end-of-stream and emit `response.completed` /
    /// `response.incomplete`. Idempotent. Persists assistant history +
    /// reasoning under the response id so a follow-up request with
    /// `previous_response_id` replays cleanly.
    ///
    /// The `sessions` argument is retained for source-compat with
    /// callers that still pass one in; the actual persistence uses the
    /// session store cloned into `self` at construction time so that
    /// the [DONE] codepath (which goes through `finish_internal` without
    /// the outer driver) saves history before `response.completed`
    /// reaches Codex. See `finish_internal` for the ordering rationale.
    pub fn finish(&mut self, _sessions: &SessionStore) {
        if self.finished {
            return;
        }
        self.finish_internal();
    }

    fn finish_internal(&mut self) {
        if self.finished {
            return;
        }
        self.finished = true;
        if self.reasoning_open {
            self.close_reasoning_item();
        }
        if self.text_open {
            self.close_text_item();
        }
        if self.refusal_open {
            self.close_refusal_item();
        }
        self.close_tool_calls();

        // Persist history BEFORE emitting response.completed. Otherwise
        // Codex sees response.completed, fires the next /v1/responses
        // with previous_response_id, and races the outer driver's
        // post-EOF finish() call — the lookup misses, history degrades
        // to "fresh conversation", and the model gives up mid-task
        // (see issue #185).
        self.persist_history();

        let assembled = self.build_assembled_output();
        let mut completed = self.stamp_model(json!({
            "id": self.response_id,
            "object": "response",
            "status": "completed",
            "output": assembled,
        }));
        completed["usage"] = chat_usage_to_responses_usage(self.usage.as_ref());
        if let Some(sf) = self.system_fingerprint.as_ref() {
            completed["system_fingerprint"] = Value::String(sf.clone());
        }
        if let Some(st) = self.service_tier.as_ref() {
            completed["service_tier"] = Value::String(st.clone());
        }

        // Finish-reason → Responses-API status mapping.
        //   • "length"           → incomplete (max_output_tokens)
        //   • "content_filter"   → incomplete (content_filter) — DeepSeek
        //                          / Qwen safety triggers fire this when
        //                          the model refuses; surfacing the reason
        //                          lets Codex tell the user "model
        //                          refused" instead of silent empty output
        //   • anything else      → completed
        let finish = self.finish_reason.as_deref();
        let incomplete_reason: Option<&str> = match finish {
            Some("length") => Some("max_output_tokens"),
            Some("content_filter") => Some("content_filter"),
            _ => None,
        };
        if let Some(reason) = incomplete_reason {
            completed["status"] = Value::String("incomplete".into());
            completed["incomplete_details"] = json!({ "reason": reason });
        }

        let event_name = if incomplete_reason.is_some() {
            "response.incomplete"
        } else {
            "response.completed"
        };
        self.emit(
            event_name,
            json!({
                "type": event_name,
                "response": completed,
            }),
        );
    }

    /// Emit a `response.failed` event and end the stream. Used when the
    /// upstream connection drops mid-stream — without this, Codex would
    /// receive response.completed with whatever partial output we got
    /// and think the request succeeded.
    pub fn fail(&mut self, message: &str, code: &str) {
        if self.finished {
            return;
        }
        self.finished = true;
        if self.reasoning_open {
            self.close_reasoning_item();
        }
        if self.text_open {
            self.close_text_item();
        }
        self.close_tool_calls();
        self.emit(
            "response.failed",
            json!({
                "type": "response.failed",
                "response": {
                    "id": self.response_id,
                    "object": "response",
                    "status": "failed",
                    "error": { "code": code, "message": message },
                    "output": self.build_assembled_output(),
                },
            }),
        );
    }

    /// Drain pending SSE events. Caller forwards these to the wire (or
    /// asserts on them in tests).
    pub fn take_events(&mut self) -> Vec<SseEvent> {
        std::mem::take(&mut self.events)
    }

    fn emit(&mut self, event: &str, data: Value) {
        self.events.push(SseEvent::new(event, data));
    }

    fn stamp_model(&self, mut resp: Value) -> Value {
        if let Some(m) = &self.client_model {
            resp["model"] = Value::String(m.clone());
        }
        // Spec: every Response envelope carries `created_at` (Unix seconds).
        // Codex's parser is lenient if it's missing but newer clients
        // (and OpenAI's own SDK) expect it.
        if resp.get("created_at").is_none() {
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_secs())
                .unwrap_or(0);
            resp["created_at"] = json!(now);
        }
        resp
    }

    fn open_text_item(&mut self) {
        self.text_idx = self.next_output_index;
        self.next_output_index += 1;
        let idx = self.text_idx;
        let item_id = format!("item_{}_{}", self.response_id, idx);
        self.emit(
            "response.output_item.added",
            json!({
                "type": "response.output_item.added",
                "output_index": idx,
                "item": {
                    "id": item_id,
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "status": "in_progress",
                    // After any tool round, Codex's "final answer"
                    // panel keys on phase="final_answer". For a
                    // proxy-side translator we can't reliably detect
                    // commentary-vs-final from upstream alone, so
                    // mark everything we emit as final_answer — the
                    // common case. Commentary support requires
                    // model-side cooperation we don't have.
                    "phase": "final_answer",
                },
            }),
        );
        self.emit(
            "response.content_part.added",
            json!({
                "type": "response.content_part.added",
                "output_index": idx,
                "content_index": 0,
                "part": { "type": "output_text", "text": "", "annotations": [] },
            }),
        );
        self.text_open = true;
        self.text_buf.clear();
        self.text_annotations.clear();
    }

    fn open_reasoning_item(&mut self) {
        self.reasoning_idx = self.next_output_index;
        self.next_output_index += 1;
        let idx = self.reasoning_idx;
        let item_id = format!("rs_{}_{}", self.response_id, idx);
        // 1. response.output_item.added — declare the reasoning item slot
        self.emit(
            "response.output_item.added",
            json!({
                "type": "response.output_item.added",
                "output_index": idx,
                "item": {
                    "id": item_id,
                    "type": "reasoning",
                    "summary": [],
                    "encrypted_content": null,
                    "status": "in_progress",
                },
            }),
        );
        // 2. response.reasoning_summary_part.added — Codex shows panel
        //    only after the part is registered.
        self.emit(
            "response.reasoning_summary_part.added",
            json!({
                "type": "response.reasoning_summary_part.added",
                "output_index": idx,
                "summary_index": 0,
                "part": { "type": "summary_text", "text": "" },
            }),
        );
        self.reasoning_open = true;
    }

    fn close_reasoning_item(&mut self) {
        if !self.reasoning_open {
            return;
        }
        let idx = self.reasoning_idx;
        // Per-panel summary = THIS panel's burst only (not the cumulative
        // `reasoning_buf`, which would re-print every earlier burst).
        let buf = self.reasoning_seg.clone();
        let item_id = format!("rs_{}_{}", self.response_id, idx);
        self.emit(
            "response.reasoning_summary_text.done",
            json!({
                "type": "response.reasoning_summary_text.done",
                "output_index": idx,
                "summary_index": 0,
                "text": buf,
            }),
        );
        self.emit(
            "response.reasoning_summary_part.done",
            json!({
                "type": "response.reasoning_summary_part.done",
                "output_index": idx,
                "summary_index": 0,
                "part": { "type": "summary_text", "text": buf },
            }),
        );
        self.emit(
            "response.output_item.done",
            json!({
                "type": "response.output_item.done",
                "output_index": idx,
                "item": {
                    "id": item_id,
                    "type": "reasoning",
                    "summary": [{ "type": "summary_text", "text": buf }],
                    "encrypted_content": null,
                    "status": "completed",
                },
            }),
        );
        // Reset the per-panel buffer so the NEXT reasoning burst starts
        // clean. `reasoning_buf` (cumulative) is deliberately left intact
        // for the finish-time assembled output + round-trip.
        self.reasoning_seg.clear();
        self.reasoning_open = false;
    }

    fn open_refusal_item(&mut self) {
        self.refusal_idx = self.next_output_index;
        self.next_output_index += 1;
        let idx = self.refusal_idx;
        let item_id = format!("item_{}_{}", self.response_id, idx);
        self.emit(
            "response.output_item.added",
            json!({
                "type": "response.output_item.added",
                "output_index": idx,
                "item": {
                    "id": item_id,
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "status": "in_progress",
                    "phase": "final_answer",
                },
            }),
        );
        self.emit(
            "response.content_part.added",
            json!({
                "type": "response.content_part.added",
                "output_index": idx,
                "content_index": 0,
                "part": { "type": "refusal", "refusal": "" },
            }),
        );
        self.refusal_open = true;
        self.refusal_buf.clear();
    }

    fn close_refusal_item(&mut self) {
        if !self.refusal_open {
            return;
        }
        let idx = self.refusal_idx;
        let buf = self.refusal_buf.clone();
        let item_id = format!("item_{}_{}", self.response_id, idx);
        self.emit(
            "response.refusal.done",
            json!({
                "type": "response.refusal.done",
                "output_index": idx,
                "content_index": 0,
                "refusal": buf,
            }),
        );
        self.emit(
            "response.content_part.done",
            json!({
                "type": "response.content_part.done",
                "output_index": idx,
                "content_index": 0,
                "part": { "type": "refusal", "refusal": buf },
            }),
        );
        self.emit(
            "response.output_item.done",
            json!({
                "type": "response.output_item.done",
                "output_index": idx,
                "item": {
                    "id": item_id,
                    "type": "message",
                    "role": "assistant",
                    "content": [{ "type": "refusal", "refusal": self.refusal_buf.clone() }],
                    "status": "completed",
                    "phase": "final_answer",
                },
            }),
        );
        self.refusal_open = false;
    }

    fn close_text_item(&mut self) {
        if !self.text_open {
            return;
        }
        let idx = self.text_idx;
        let buf = self.text_buf.clone();
        let annotations = self.text_annotations.clone();
        let item_id = format!("item_{}_{}", self.response_id, idx);
        self.emit(
            "response.output_text.done",
            json!({
                "type": "response.output_text.done",
                "output_index": idx,
                "content_index": 0,
                "text": buf,
            }),
        );
        self.emit(
            "response.content_part.done",
            json!({
                "type": "response.content_part.done",
                "output_index": idx,
                "content_index": 0,
                "part": { "type": "output_text", "text": buf, "annotations": annotations },
            }),
        );
        self.emit(
            "response.output_item.done",
            json!({
                "type": "response.output_item.done",
                "output_index": idx,
                "item": {
                    "id": item_id,
                    "type": "message",
                    "role": "assistant",
                    "content": [{ "type": "output_text", "text": buf, "annotations": self.text_annotations.clone() }],
                    "status": "completed",
                    "phase": "final_answer",
                },
            }),
        );
        self.text_open = false;
    }

    fn open_tool_call(&mut self, idx: i64, tc: &Value) {
        let output_index = self.next_output_index;
        self.next_output_index += 1;
        let call_id = tc
            .get("id")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string())
            .unwrap_or_else(|| {
                use rand::Rng;
                let mut rng = rand::thread_rng();
                let suffix: String = (0..10)
                    .map(|_| {
                        let n: u8 = rng.gen_range(0..36);
                        if n < 10 {
                            (b'0' + n) as char
                        } else {
                            (b'a' + (n - 10)) as char
                        }
                    })
                    .collect();
                format!("call_{suffix}")
            });
        let name = tc
            .get("function")
            .and_then(|v| v.get("name"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let slot = ToolCallSlot {
            id: call_id,
            name,
            arguments: String::new(),
            output_index,
            added_emitted: false,
            streamed_args_len: 0,
        };
        self.tool_calls.insert(idx, slot);
        self.tool_call_order.push(idx);
        // Announce the item now only if the name is already known (the common
        // case — providers usually send id+name in the first delta).
        // Otherwise emit_tool_call_added() fires once a later delta supplies
        // the name; if none ever does, the slot is dropped at finalization.
        self.emit_tool_call_added(idx);
    }

    /// Emit `response.output_item.added` for a tool slot once its `name` is
    /// known. Idempotent (guarded by `added_emitted`) and a no-op while the
    /// name is still empty, so a never-named tool_call is never announced.
    fn emit_tool_call_added(&mut self, idx: i64) {
        let (output_index, call_id, name) = match self.tool_calls.get_mut(&idx) {
            Some(slot) if !slot.added_emitted && !slot.name.is_empty() => {
                slot.added_emitted = true;
                (slot.output_index, slot.id.clone(), slot.name.clone())
            }
            _ => return,
        };
        self.emit(
            "response.output_item.added",
            json!({
                "type": "response.output_item.added",
                "output_index": output_index,
                "item": {
                    "id": call_id,
                    "type": "function_call",
                    "call_id": call_id,
                    "name": name,
                    "arguments": "",
                },
            }),
        );
    }

    fn close_tool_calls(&mut self) {
        // Snapshot first to avoid borrowing self while emitting. Slots that
        // never received a function name were never announced via `added`
        // (see emit_tool_call_added), so emitting done events for them would
        // reference an item Codex never saw — drop them instead.
        let mut skipped = 0usize;
        let snapshots: Vec<ToolCallSlot> = self
            .tool_call_order
            .iter()
            .filter_map(|i| self.tool_calls.get(i).cloned())
            .filter(|slot| {
                if slot.name.is_empty() {
                    skipped += 1;
                    false
                } else {
                    true
                }
            })
            .collect();
        if skipped > 0 {
            log::warn!(
                "[CodexProxy] Skipped {skipped} streaming tool_call(s) with empty function name"
            );
        }
        for slot in snapshots {
            self.emit(
                "response.function_call_arguments.done",
                json!({
                    "type": "response.function_call_arguments.done",
                    "output_index": slot.output_index,
                    "item_id": slot.id,
                    "arguments": slot.arguments,
                }),
            );
            self.emit(
                "response.output_item.done",
                json!({
                    "type": "response.output_item.done",
                    "output_index": slot.output_index,
                    "item": {
                        "id": slot.id,
                        "type": "function_call",
                        "call_id": slot.id,
                        "name": slot.name,
                        "arguments": slot.arguments,
                    },
                }),
            );
        }
    }

    fn build_assembled_output(&self) -> Vec<Value> {
        let mut out: Vec<Value> = Vec::new();
        // Reasoning item first — the spec ordering puts thinking before
        // assistant message + tool calls (Codex's UI also expects it
        // first when scanning response.output[]).
        if !self.reasoning_buf.is_empty() {
            let idx = if self.reasoning_idx >= 0 {
                self.reasoning_idx
            } else {
                0
            };
            out.push(json!({
                "id": format!("rs_{}_{}", self.response_id, idx),
                "type": "reasoning",
                "summary": [{ "type": "summary_text", "text": self.reasoning_buf }],
                "encrypted_content": null,
                "status": "completed",
            }));
        }
        if !self.text_buf.is_empty() {
            let idx = if self.text_idx >= 0 { self.text_idx } else { 0 };
            out.push(json!({
                "id": format!("item_{}_{}", self.response_id, idx),
                "type": "message",
                "role": "assistant",
                "content": [{ "type": "output_text", "text": self.text_buf, "annotations": self.text_annotations.clone() }],
                "status": "completed",
                "phase": "final_answer",
            }));
        }
        if !self.refusal_buf.is_empty() {
            let idx = if self.refusal_idx >= 0 {
                self.refusal_idx
            } else {
                0
            };
            out.push(json!({
                "id": format!("item_{}_{}", self.response_id, idx),
                "type": "message",
                "role": "assistant",
                "content": [{ "type": "refusal", "refusal": self.refusal_buf }],
                "status": "completed",
                "phase": "final_answer",
            }));
        }
        for i in &self.tool_call_order {
            if let Some(slot) = self.tool_calls.get(i) {
                if slot.name.is_empty() {
                    continue; // never-named call: not announced, unroutable
                }
                out.push(json!({
                    "id": slot.id,
                    "type": "function_call",
                    "call_id": slot.id,
                    "name": slot.name,
                    "arguments": slot.arguments,
                }));
            }
        }
        out
    }

    fn persist_history(&self) {
        let mut assistant_msg = serde_json::Map::new();
        assistant_msg.insert("role".into(), Value::String("assistant".into()));
        // Skip never-named tool calls (see emit_tool_call_added) so the
        // replayed history matches what Codex actually saw on the wire.
        let normalized: Vec<Value> = self
            .tool_call_order
            .iter()
            .filter_map(|i| self.tool_calls.get(i))
            .filter(|slot| !slot.name.is_empty())
            .map(|slot| {
                json!({
                    "id": slot.id,
                    "type": "function",
                    "function": { "name": slot.name, "arguments": slot.arguments },
                })
            })
            .collect();
        if normalized.is_empty() {
            assistant_msg.insert("content".into(), Value::String(self.text_buf.clone()));
        } else {
            // Chat Completions accepts assistants with BOTH a text content
            // and a tool_calls array. OpenAI o-series and several Chinese
            // providers narrate a plan before calling tools; dropping the
            // prelude here silently degrades the next replay turn.
            let content_value = if self.text_buf.is_empty() {
                Value::Null
            } else {
                Value::String(self.text_buf.clone())
            };
            assistant_msg.insert("content".into(), content_value);
            assistant_msg.insert("tool_calls".into(), Value::Array(normalized));
        }
        if !self.reasoning_buf.is_empty() {
            assistant_msg.insert(
                "reasoning_content".into(),
                Value::String(self.reasoning_buf.clone()),
            );
            // Store reasoning under every tool_call id so any of them
            // resolves on next-turn lookup.
            for i in &self.tool_call_order {
                if let Some(slot) = self.tool_calls.get(i) {
                    self.sessions.store_reasoning(&slot.id, &self.reasoning_buf);
                }
            }
            // And under a content-fingerprint key, so plain assistant
            // turns (no tool_calls) also round-trip.
            if !self.text_buf.is_empty() {
                self.sessions.store_turn_reasoning(
                    &Value::String(self.text_buf.clone()),
                    &self.reasoning_buf,
                );
            }
        }
        // Honor `store: false` — caller wants ZDR/stateless behavior,
        // we must NOT retain the assistant turn under response_id.
        // Reasoning store (per call_id) still persists; that's
        // conversation-state, not the conversation itself.
        if self.store {
            let mut history = self.request_messages.clone();
            history.push(Value::Object(assistant_msg));
            self.sessions.save_history(&self.response_id, history);
        }
    }
}

// ---------------------------------------------------------------------------
// Tests — pure state-machine assertions, no I/O.
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;

    fn collect_events(state: &mut StreamState) -> Vec<SseEvent> {
        state.take_events()
    }

    fn event_names(events: &[SseEvent]) -> Vec<&str> {
        events.iter().map(|e| e.event.as_str()).collect()
    }

    // ---- chat_usage_to_responses_usage ----

    #[test]
    fn usage_translates_prompt_completion_to_input_output() {
        let chat = json!({
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
        });
        let out = chat_usage_to_responses_usage(Some(&chat));
        assert_eq!(out["input_tokens"], 10);
        assert_eq!(out["output_tokens"], 20);
        assert_eq!(out["total_tokens"], 30);
        // Mandatory nested objects present even when upstream omits them.
        assert_eq!(out["input_tokens_details"]["cached_tokens"], 0);
        assert_eq!(out["output_tokens_details"]["reasoning_tokens"], 0);
    }

    #[test]
    fn usage_passes_through_responses_shape_unchanged() {
        let chat = json!({
            "input_tokens": 5,
            "input_tokens_details": { "cached_tokens": 2 },
            "output_tokens": 7,
            "output_tokens_details": { "reasoning_tokens": 3 },
            "total_tokens": 12,
        });
        let out = chat_usage_to_responses_usage(Some(&chat));
        assert_eq!(out["input_tokens"], 5);
        assert_eq!(out["input_tokens_details"]["cached_tokens"], 2);
        assert_eq!(out["output_tokens"], 7);
        assert_eq!(out["output_tokens_details"]["reasoning_tokens"], 3);
        assert_eq!(out["total_tokens"], 12);
    }

    #[test]
    fn usage_synthesizes_total_when_missing() {
        let chat = json!({ "prompt_tokens": 4, "completion_tokens": 6 });
        let out = chat_usage_to_responses_usage(Some(&chat));
        assert_eq!(out["total_tokens"], 10);
    }

    #[test]
    fn usage_extracts_cached_from_prompt_tokens_details() {
        let chat = json!({
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "prompt_tokens_details": { "cached_tokens": 40 },
        });
        let out = chat_usage_to_responses_usage(Some(&chat));
        assert_eq!(out["input_tokens_details"]["cached_tokens"], 40);
    }

    #[test]
    fn usage_extracts_reasoning_from_completion_tokens_details() {
        let chat = json!({
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "completion_tokens_details": { "reasoning_tokens": 8 },
        });
        let out = chat_usage_to_responses_usage(Some(&chat));
        assert_eq!(out["output_tokens_details"]["reasoning_tokens"], 8);
    }

    #[test]
    fn usage_falls_back_to_flat_cached_and_reasoning() {
        let chat = json!({
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "cached_tokens": 9,
            "reasoning_tokens": 11,
        });
        let out = chat_usage_to_responses_usage(Some(&chat));
        assert_eq!(out["input_tokens_details"]["cached_tokens"], 9);
        assert_eq!(out["output_tokens_details"]["reasoning_tokens"], 11);
    }

    #[test]
    fn usage_zeros_out_when_null() {
        let out = chat_usage_to_responses_usage(None);
        assert_eq!(out["input_tokens"], 0);
        assert_eq!(out["output_tokens"], 0);
        assert_eq!(out["total_tokens"], 0);
        assert_eq!(out["input_tokens_details"]["cached_tokens"], 0);
        assert_eq!(out["output_tokens_details"]["reasoning_tokens"], 0);
    }

    // ---- extract_reasoning_delta ----

    #[test]
    fn reasoning_extract_canonical_reasoning_content_string() {
        let d = json!({ "reasoning_content": "I should call shell." });
        assert_eq!(
            extract_reasoning_delta(&d),
            Some("I should call shell.".to_string())
        );
    }

    #[test]
    fn reasoning_extract_falls_back_to_reasoning_field() {
        // Some MiMo deployments stream `reasoning` instead of `reasoning_content`.
        let d = json!({ "reasoning": "let me think" });
        assert_eq!(
            extract_reasoning_delta(&d),
            Some("let me think".to_string())
        );
    }

    #[test]
    fn reasoning_extract_falls_back_to_thinking_field() {
        let d = json!({ "thinking": "anthropic style" });
        assert_eq!(
            extract_reasoning_delta(&d),
            Some("anthropic style".to_string())
        );
    }

    #[test]
    fn reasoning_extract_structured_text_object() {
        let d = json!({ "reasoning_content": { "type": "text", "text": "structured" } });
        assert_eq!(extract_reasoning_delta(&d), Some("structured".to_string()));
    }

    #[test]
    fn reasoning_extract_array_of_parts() {
        let d = json!({
            "reasoning_content": [
                { "text": "first " },
                { "text": "second" },
            ]
        });
        assert_eq!(
            extract_reasoning_delta(&d),
            Some("first second".to_string())
        );
    }

    #[test]
    fn reasoning_extract_returns_none_when_absent() {
        let d = json!({ "content": "regular text", "role": "assistant" });
        assert_eq!(extract_reasoning_delta(&d), None);
    }

    #[test]
    fn reasoning_extract_skips_empty_strings() {
        let d = json!({ "reasoning_content": "" });
        assert_eq!(extract_reasoning_delta(&d), None);
    }

    #[test]
    fn reasoning_extract_concatenates_multiple_fields_when_present() {
        // Defensive: if a provider mistakenly emits both fields we keep
        // both halves rather than silently dropping one.
        let d = json!({ "reasoning_content": "part1 ", "thinking": "part2" });
        let out = extract_reasoning_delta(&d).unwrap();
        assert!(out.contains("part1"));
        assert!(out.contains("part2"));
    }

    // ---- reasoning summary SSE events (H1 + H2) ----

    fn feed_chat_chunk(state: &mut StreamState, delta_json: Value) {
        // Build a Chat-Completions SSE-style chunk line.
        let payload = json!({
            "choices": [{ "delta": delta_json }]
        });
        let line = format!("data: {}\n", payload);
        state.feed_chunk(&line);
    }

    #[test]
    fn reasoning_delta_emits_summary_text_events() {
        let store = SessionStore::new();
        let mut state = StreamState::new(&store, Some("gpt-5".into()), vec![]);
        state.start();
        let _ = state.take_events(); // discard the opening pair

        feed_chat_chunk(&mut state, json!({ "reasoning_content": "Let me think." }));
        let events = state.take_events();
        let names = event_names(&events);

        // Expected ordering: output_item.added (reasoning) →
        // reasoning_summary_part.added → reasoning_summary_text.delta
        assert!(
            names.contains(&"response.output_item.added"),
            "got: {names:?}"
        );
        assert!(
            names.contains(&"response.reasoning_summary_part.added"),
            "got: {names:?}"
        );
        assert!(
            names.contains(&"response.reasoning_summary_text.delta"),
            "got: {names:?}"
        );

        // The output_item.added carries type=reasoning
        let added = events
            .iter()
            .find(|e| e.event == "response.output_item.added")
            .unwrap();
        assert_eq!(added.data["item"]["type"], "reasoning");
        assert_eq!(added.data["item"]["status"], "in_progress");
    }

    #[test]
    fn reasoning_finish_emits_summary_done_then_completed() {
        let store = SessionStore::new();
        let mut state = StreamState::new(&store, Some("gpt-5".into()), vec![]);
        state.start();
        let _ = state.take_events();

        feed_chat_chunk(
            &mut state,
            json!({ "reasoning_content": "Thinking about it..." }),
        );
        let _ = state.take_events();

        state.finish(&store);
        let events = state.take_events();
        let names = event_names(&events);

        // On finish we must emit the done sequence + then the response.completed.
        assert!(
            names.contains(&"response.reasoning_summary_text.done"),
            "got: {names:?}"
        );
        assert!(
            names.contains(&"response.reasoning_summary_part.done"),
            "got: {names:?}"
        );
        assert!(names.contains(&"response.completed"), "got: {names:?}");

        // Assembled output should contain the reasoning item with
        // the captured summary text.
        let completed = events
            .iter()
            .find(|e| e.event == "response.completed")
            .unwrap();
        let output = completed.data["response"]["output"].as_array().unwrap();
        let reasoning_item = output
            .iter()
            .find(|i| i["type"] == "reasoning")
            .expect("reasoning item in output");
        let text = reasoning_item["summary"][0]["text"].as_str().unwrap();
        assert!(text.contains("Thinking about it"));
    }

    #[test]
    fn reasoning_then_text_closes_reasoning_before_text() {
        let store = SessionStore::new();
        let mut state = StreamState::new(&store, Some("gpt-5".into()), vec![]);
        state.start();
        let _ = state.take_events();

        feed_chat_chunk(&mut state, json!({ "reasoning_content": "deciding..." }));
        feed_chat_chunk(&mut state, json!({ "content": "Hello!" }));
        let events = state.take_events();
        let names = event_names(&events);

        // Position of reasoning_summary_text.done should come BEFORE
        // the first response.output_text.delta (we close reasoning
        // when text starts).
        let pos_reasoning_done = names
            .iter()
            .position(|n| *n == "response.reasoning_summary_text.done");
        let pos_text_delta = names
            .iter()
            .position(|n| *n == "response.output_text.delta");
        assert!(pos_reasoning_done.is_some(), "{names:?}");
        assert!(pos_text_delta.is_some(), "{names:?}");
        assert!(
            pos_reasoning_done.unwrap() < pos_text_delta.unwrap(),
            "reasoning must close before text starts; {names:?}"
        );
    }

    #[test]
    fn interleaved_reasoning_segments_are_not_cumulative() {
        // Regression guard: when a thinking model interleaves reasoning
        // with content (reasoning → text → reasoning → text), each
        // reasoning panel's `summary_text.done` must carry ONLY that
        // panel's own burst — not a running concatenation of every
        // prior burst. The buggy version reused a single never-cleared
        // buffer, so panel 2 re-printed panel 1's text, which surfaced
        // in the Codex UI as repeatedly-growing "thinking" summaries.
        let store = SessionStore::new();
        let mut state = StreamState::new(&store, Some("gpt-5".into()), vec![]);
        state.start();
        let _ = state.take_events();

        // Burst 1, then a content delta forces panel 1 to close.
        feed_chat_chunk(&mut state, json!({ "reasoning_content": "FIRST burst." }));
        feed_chat_chunk(&mut state, json!({ "content": "answer-a" }));
        // Burst 2, then a content delta forces panel 2 to close.
        feed_chat_chunk(&mut state, json!({ "reasoning_content": "SECOND burst." }));
        feed_chat_chunk(&mut state, json!({ "content": "answer-b" }));

        let events = state.take_events();
        let done_texts: Vec<String> = events
            .iter()
            .filter(|e| e.event == "response.reasoning_summary_text.done")
            .map(|e| e.data["text"].as_str().unwrap_or_default().to_string())
            .collect();

        assert_eq!(
            done_texts.len(),
            2,
            "expected two reasoning panels to close; got: {done_texts:?}"
        );
        assert_eq!(done_texts[0], "FIRST burst.");
        assert_eq!(
            done_texts[1], "SECOND burst.",
            "second panel must summarize only its own burst, not repeat the first"
        );
        assert!(
            !done_texts[1].contains("FIRST"),
            "second panel leaked the first burst's text: {:?}",
            done_texts[1]
        );
    }

    #[test]
    fn interleaved_reasoning_keeps_full_text_in_assembled_output() {
        // The per-panel fix must NOT shrink the cumulative reasoning
        // that feeds the final assembled output + SessionStore
        // round-trip — next-turn replay needs the model's COMPLETE
        // reasoning, so the completed response keeps every burst.
        let store = SessionStore::new();
        let mut state = StreamState::new(&store, Some("gpt-5".into()), vec![]);
        state.start();
        let _ = state.take_events();

        feed_chat_chunk(&mut state, json!({ "reasoning_content": "FIRST burst. " }));
        feed_chat_chunk(&mut state, json!({ "content": "answer-a" }));
        feed_chat_chunk(&mut state, json!({ "reasoning_content": "SECOND burst." }));
        let _ = state.take_events();

        state.finish(&store);
        let events = state.take_events();
        let completed = events
            .iter()
            .find(|e| e.event == "response.completed")
            .unwrap();
        let output = completed.data["response"]["output"].as_array().unwrap();
        let reasoning_item = output
            .iter()
            .find(|i| i["type"] == "reasoning")
            .expect("reasoning item in assembled output");
        let text = reasoning_item["summary"][0]["text"].as_str().unwrap();
        assert!(text.contains("FIRST burst."), "got: {text:?}");
        assert!(text.contains("SECOND burst."), "got: {text:?}");
    }

    #[test]
    fn response_envelope_carries_created_at() {
        let store = SessionStore::new();
        let mut state = StreamState::new(&store, Some("gpt-5".into()), vec![]);
        state.start();
        let events = state.take_events();
        let created = events
            .iter()
            .find(|e| e.event == "response.created")
            .unwrap();
        let ts = created.data["response"]["created_at"]
            .as_u64()
            .expect("created_at must be a number");
        assert!(ts > 1_700_000_000, "created_at should be a recent Unix ts");
    }

    #[test]
    fn content_filter_finish_reason_becomes_incomplete() {
        let store = SessionStore::new();
        let mut state = StreamState::new(&store, Some("gpt-5".into()), vec![]);
        state.start();
        let _ = state.take_events();
        feed_chat_chunk(&mut state, json!({ "content": "partial answer" }));
        let _ = state.take_events();

        // Emit the finish_reason from upstream.
        let payload = json!({
            "choices": [{ "delta": {}, "finish_reason": "content_filter" }]
        });
        state.feed_chunk(&format!("data: {}\n", payload));
        state.finish(&store);
        let events = state.take_events();
        let last = events.iter().find(|e| e.event == "response.incomplete");
        assert!(last.is_some(), "expected response.incomplete");
        assert_eq!(
            last.unwrap().data["response"]["incomplete_details"]["reason"],
            "content_filter"
        );
    }

    // ---- chat_error_to_responses_error ----

    #[test]
    fn error_extracts_nested_message_from_openai_shape() {
        let body = r#"{"error":{"message":"Invalid API key","code":"invalid_api_key"}}"#;
        let out = chat_error_to_responses_error(401, Some(body), None);
        assert_eq!(out["status"], "failed");
        assert_eq!(out["error"]["message"], "Invalid API key");
        assert_eq!(out["error"]["code"], "invalid_api_key");
        assert_eq!(out["output"], json!([]));
    }

    #[test]
    fn error_extracts_flat_detail_message_and_normalizes_code() {
        // 429 + "rate_limit" type → normalized to "rate_limit_exceeded"
        // so Codex's specialized rate-limit UI fires.
        let body = r#"{"detail":"Rate limit exceeded","type":"rate_limit"}"#;
        let out = chat_error_to_responses_error(429, Some(body), None);
        assert_eq!(out["error"]["message"], "Rate limit exceeded");
        assert_eq!(out["error"]["code"], "rate_limit_exceeded");
    }

    #[test]
    fn error_truncates_non_json_body_to_500() {
        let body = "x".repeat(800);
        let out = chat_error_to_responses_error(502, Some(&body), None);
        let msg = out["error"]["message"].as_str().unwrap();
        assert_eq!(msg.len(), 500);
        assert_eq!(out["error"]["code"], "upstream_502");
    }

    // ---- context-overflow friendly rewrite ----

    #[test]
    fn context_overflow_400_gets_friendly_bilingual_message() {
        let body = r#"{"error":{"message":"This model's maximum context length is 128000 tokens, however your prompt is too long","code":"context_length_exceeded"}}"#;
        let out = chat_error_to_responses_error(400, Some(body), None);
        let msg = out["error"]["message"].as_str().unwrap();
        assert!(msg.contains("上下文"), "should include Chinese hint");
        assert!(
            msg.contains("context window"),
            "should include English hint"
        );
        assert_eq!(out["error"]["code"], "context_length_exceeded");
    }

    #[test]
    fn context_overflow_zh_phrasing_also_caught() {
        let body = r#"{"error":{"message":"输入的内容超出最大长度，请缩短后重试"}}"#;
        let out = chat_error_to_responses_error(400, Some(body), None);
        let msg = out["error"]["message"].as_str().unwrap();
        assert!(msg.contains("上下文"));
        assert!(msg.contains("context window"));
    }

    #[test]
    fn non_overflow_400_passes_through_unchanged() {
        // Generic 400 (bad parameter, etc.) shouldn't get rewritten.
        let body = r#"{"error":{"message":"Invalid value for temperature: 5.0","code":"invalid_request_error"}}"#;
        let out = chat_error_to_responses_error(400, Some(body), None);
        assert_eq!(
            out["error"]["message"],
            "Invalid value for temperature: 5.0"
        );
        assert_eq!(out["error"]["code"], "invalid_request_error");
    }

    #[test]
    fn overflow_keywords_in_500_are_preserved_verbatim() {
        // 5xx means upstream crashed — preserve verbatim so users see
        // the real reason, even if the message happens to mention
        // "context length" in a stack trace.
        let body = r#"{"error":{"message":"context length panic at line 42"}}"#;
        let out = chat_error_to_responses_error(500, Some(body), None);
        assert_eq!(out["error"]["message"], "context length panic at line 42");
    }

    #[test]
    fn looks_like_context_overflow_unit_cases() {
        // EN
        assert!(looks_like_context_overflow("Context length exceeded"));
        assert!(looks_like_context_overflow(
            "your input is too long for this model"
        ));
        assert!(looks_like_context_overflow("Too many tokens in prompt"));
        // zh
        assert!(looks_like_context_overflow("上下文过长，请缩短"));
        assert!(looks_like_context_overflow("超过最大长度限制"));
        // misses
        assert!(!looks_like_context_overflow("Invalid API key"));
        assert!(!looks_like_context_overflow("rate limit exceeded")); // exceeded alone isn't enough
        assert!(!looks_like_context_overflow(""));
    }

    // ---- image-unsupported friendly rewrite ----

    #[test]
    fn image_unsupported_400_gets_friendly_bilingual_message() {
        let body = r#"{"error":{"message":"This model does not support image input.","code":"invalid_input"}}"#;
        let out = chat_error_to_responses_error(400, Some(body), None);
        let msg = out["error"]["message"].as_str().unwrap();
        assert!(msg.contains("不支持图像"));
        assert!(msg.contains("vision-capable"));
        assert_eq!(out["error"]["code"], "image_unsupported");
    }

    #[test]
    fn image_unsupported_zh_phrasing_also_caught() {
        let body = r#"{"error":{"message":"当前模型不支持图片输入"}}"#;
        let out = chat_error_to_responses_error(400, Some(body), None);
        let msg = out["error"]["message"].as_str().unwrap();
        assert!(msg.contains("vision-capable"));
    }

    #[test]
    fn image_unsupported_deepseek_json_deserialize_wording_caught() {
        // DeepSeek's strict schema rejects image_url with a deserialize
        // error rather than "model doesn't support image". Issue #38
        // (msyrain) hit this on deepseek-v4-pro.
        let body = r#"{"error":{"message":"Failed to deserialize the JSON body into the target type: messages[372]: unknown variant `image_url`, expected `text` at line 1 column 768380","type":"invalid_request_error"}}"#;
        let out = chat_error_to_responses_error(400, Some(body), None);
        let msg = out["error"]["message"].as_str().unwrap();
        assert!(msg.contains("不支持图像") || msg.contains("vision-capable"));
        assert_eq!(out["error"]["code"], "image_unsupported");
    }

    #[test]
    fn looks_like_image_unsupported_unit_cases() {
        // EN
        assert!(looks_like_image_unsupported(
            "This model does not support image input"
        ));
        assert!(looks_like_image_unsupported("Vision is not supported"));
        assert!(looks_like_image_unsupported("model is not multimodal"));
        // zh
        assert!(looks_like_image_unsupported("当前模型不支持图像"));
        assert!(looks_like_image_unsupported("不支持图片输入"));
        assert!(looks_like_image_unsupported("该模型不支持多模态"));
        // misses — generic 400 about other things
        assert!(!looks_like_image_unsupported("Invalid API key"));
        assert!(!looks_like_image_unsupported("Context length exceeded"));
        assert!(!looks_like_image_unsupported(""));
    }

    #[test]
    fn image_unsupported_keywords_in_500_preserved_verbatim() {
        // 5xx upstream crash: keep verbatim even if message names images.
        let body = r#"{"error":{"message":"image not supported - server crashed"}}"#;
        let out = chat_error_to_responses_error(500, Some(body), None);
        assert_eq!(
            out["error"]["message"],
            "image not supported - server crashed"
        );
    }

    #[test]
    fn error_default_message_when_no_body_normalizes_503_to_overloaded() {
        // 503 → "server_overloaded" so Codex's retry-with-backoff UI
        // fires instead of treating it as a generic upstream error.
        let out = chat_error_to_responses_error(503, None, None);
        assert_eq!(out["error"]["message"], "Upstream returned 503");
        assert_eq!(out["error"]["code"], "server_overloaded");
    }

    // ---- normalize_error_code ----

    #[test]
    fn normalize_canonical_codes_pass_through() {
        assert_eq!(
            normalize_error_code("context_length_exceeded", 400, ""),
            "context_length_exceeded"
        );
        assert_eq!(
            normalize_error_code("image_unsupported", 400, ""),
            "image_unsupported"
        );
    }

    #[test]
    fn normalize_quota_codes_to_rate_limit_exceeded() {
        // Various upstream wordings for quota / billing limits all
        // collapse to the canonical name Codex matches on.
        assert_eq!(
            normalize_error_code("insufficient_quota", 400, ""),
            "rate_limit_exceeded"
        );
        assert_eq!(
            normalize_error_code("billing_hard_limit_reached", 402, ""),
            "rate_limit_exceeded"
        );
        // Status 429 alone is enough.
        assert_eq!(
            normalize_error_code("some_other_code", 429, ""),
            "rate_limit_exceeded"
        );
        // Message-text signal works too (some providers put the hint in
        // the message rather than the code).
        assert_eq!(
            normalize_error_code("GenericError", 400, "Your account balance is insufficient"),
            "rate_limit_exceeded"
        );
    }

    #[test]
    fn normalize_overload_codes_to_server_overloaded() {
        assert_eq!(
            normalize_error_code("service_unavailable", 503, ""),
            "server_overloaded"
        );
        assert_eq!(
            normalize_error_code("anything", 529, ""),
            "server_overloaded"
        );
        assert_eq!(
            normalize_error_code("X", 500, "server is overloaded, try again later"),
            "server_overloaded"
        );
    }

    #[test]
    fn normalize_safety_codes_to_cyber_policy() {
        assert_eq!(
            normalize_error_code("content_policy_violation", 400, ""),
            "cyber_policy"
        );
        assert_eq!(
            normalize_error_code("any", 400, "Request blocked by content moderation"),
            "cyber_policy"
        );
        // Chinese phrasings — providers like Qwen sometimes write in zh.
        assert_eq!(
            normalize_error_code("any", 400, "包含敏感内容，已被过滤"),
            "cyber_policy"
        );
    }

    #[test]
    fn normalize_unknown_code_passes_through() {
        // Genuine unique error codes stay verbatim — preserves
        // diagnostics for unknown failure modes.
        assert_eq!(
            normalize_error_code("invalid_api_key", 401, ""),
            "invalid_api_key"
        );
    }

    // ---- chat_to_responses_non_stream ----

    #[test]
    fn non_stream_translates_text_message() {
        let store = SessionStore::new();
        let chat = json!({
            "choices": [{
                "message": { "role": "assistant", "content": "hello world" },
                "finish_reason": "stop",
            }],
            "usage": { "prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5 },
        });
        let out = chat_to_responses_non_stream(&chat, vec![], &store, Some("gpt-5.5"), true);
        assert_eq!(out["status"], "completed");
        assert_eq!(out["model"], "gpt-5.5");
        assert_eq!(out["output"][0]["type"], "message");
        assert_eq!(out["output"][0]["content"][0]["text"], "hello world");
        assert_eq!(out["usage"]["input_tokens"], 3);
        assert_eq!(out["usage"]["output_tokens"], 2);
    }

    #[test]
    fn non_stream_translates_tool_calls() {
        let store = SessionStore::new();
        let chat = json!({
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": null,
                    "tool_calls": [{
                        "id": "call_abc",
                        "type": "function",
                        "function": { "name": "shell", "arguments": "{\"cmd\":\"ls\"}" },
                    }],
                },
                "finish_reason": "tool_calls",
            }],
        });
        let out = chat_to_responses_non_stream(&chat, vec![], &store, None, true);
        assert_eq!(out["output"][0]["type"], "function_call");
        assert_eq!(out["output"][0]["call_id"], "call_abc");
        assert_eq!(out["output"][0]["name"], "shell");
        assert_eq!(out["output"][0]["arguments"], "{\"cmd\":\"ls\"}");
    }

    #[test]
    fn non_stream_skips_tool_call_with_empty_name() {
        // Some providers emit a tool_call whose function.name is empty;
        // a nameless function_call is unroutable, so it must be dropped.
        let store = SessionStore::new();
        let chat = json!({
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": null,
                    "tool_calls": [{
                        "id": "call_noname",
                        "type": "function",
                        "function": { "name": "", "arguments": "{}" },
                    }],
                },
                "finish_reason": "tool_calls",
            }],
        });
        let out = chat_to_responses_non_stream(&chat, vec![], &store, None, true);
        let has_fn = out["output"]
            .as_array()
            .map(|a| a.iter().any(|item| item["type"] == "function_call"))
            .unwrap_or(false);
        assert!(!has_fn, "nameless tool_call should be skipped from output");
    }

    #[test]
    fn non_stream_marks_length_as_incomplete() {
        let store = SessionStore::new();
        let chat = json!({
            "choices": [{
                "message": { "role": "assistant", "content": "partial" },
                "finish_reason": "length",
            }],
        });
        let out = chat_to_responses_non_stream(&chat, vec![], &store, None, true);
        assert_eq!(out["status"], "incomplete");
        assert_eq!(out["incomplete_details"]["reason"], "max_output_tokens");
    }

    #[test]
    fn non_stream_omits_model_when_no_client_model() {
        let store = SessionStore::new();
        let chat = json!({
            "choices": [{ "message": { "role": "assistant", "content": "x" } }],
        });
        let out = chat_to_responses_non_stream(&chat, vec![], &store, None, true);
        assert!(out.get("model").is_none());
    }

    // ---- StreamState ----

    fn make_state(model: Option<&str>) -> StreamState {
        let store = SessionStore::new();
        StreamState::new(&store, model.map(|s| s.to_string()), vec![])
    }

    #[test]
    fn stream_start_emits_queued_created_in_progress() {
        let mut s = make_state(Some("gpt-5.5"));
        s.start();
        let events = collect_events(&mut s);
        assert_eq!(
            event_names(&events),
            vec![
                "response.queued",
                "response.created",
                "response.in_progress"
            ]
        );
        assert_eq!(events[0].data["response"]["status"], "queued");
        assert_eq!(events[1].data["response"]["model"], "gpt-5.5");
        assert_eq!(events[1].data["response"]["status"], "in_progress");
    }

    #[test]
    fn done_in_chunk_persists_history_before_completed_event() {
        // Regression for issue #185: [DONE] in the upstream stream used
        // to fire response.completed without persisting history; the
        // outer driver loop only persisted after upstream EOF, racing
        // Codex's follow-up /v1/responses POST with previous_response_id.
        // After fix: persist_history must complete before the
        // response.completed event is queued.
        let store = SessionStore::new();
        let mut state = StreamState::new(&store, Some("gpt-5.5".into()), vec![]);
        state.start();
        collect_events(&mut state);

        state.feed_chunk("data: {\"choices\":[{\"delta\":{\"content\":\"hi\"}}]}\n");
        state.feed_chunk("data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"stop\"}]}\n");

        let response_id = state.response_id().to_string();
        // Snapshot history BEFORE the [DONE] line.
        assert!(
            store.get_history(&response_id).is_empty(),
            "history should not exist yet before [DONE]"
        );

        // [DONE] is the trigger that used to be racy. Send it and check
        // that history exists the moment the response.completed event
        // becomes available (i.e. before any outer-driver finish() call).
        state.feed_chunk("data: [DONE]\n");

        // Now history must be persisted, because Codex will see
        // response.completed as soon as the next forward_events() runs
        // and could fire a follow-up POST immediately.
        let history = store.get_history(&response_id);
        assert!(
            !history.is_empty(),
            "history must be persisted before response.completed reaches the client"
        );

        // And response.completed must still be in the emitted-event queue.
        let events = collect_events(&mut state);
        assert!(
            events.iter().any(|e| e.event == "response.completed"),
            "response.completed must still be emitted after [DONE]"
        );
    }

    #[test]
    fn store_false_skips_save_history_but_keeps_reasoning_store() {
        let store = SessionStore::new();
        let mut state = StreamState::new(&store, None, vec![]);
        state.set_store(false);
        state.start();
        let _ = state.take_events();

        // Feed a chunk with reasoning + content so persist_history would
        // try to write to both stores in the default (store=true) case.
        feed_chat_chunk(
            &mut state,
            json!({ "reasoning_content": "thought", "content": "ok" }),
        );
        state.finish(&store);

        let response_id = state.response_id().to_string();
        // store=false → no history saved under our response id
        assert!(
            store.get_history(&response_id).is_empty(),
            "store=false must not persist history"
        );
    }

    #[test]
    fn stream_text_delta_opens_item_and_emits_delta() {
        let mut s = make_state(None);
        s.start();
        collect_events(&mut s);
        s.feed_chunk("data: {\"choices\":[{\"delta\":{\"content\":\"hi\"}}]}\n");
        let events = collect_events(&mut s);
        assert_eq!(
            event_names(&events),
            vec![
                "response.output_item.added",
                "response.content_part.added",
                "response.output_text.delta",
            ]
        );
        assert_eq!(events[2].data["delta"], "hi");
    }

    #[test]
    fn stream_done_closes_text_and_completes() {
        let mut s = make_state(Some("gpt-5.5"));
        s.start();
        collect_events(&mut s);
        s.feed_chunk("data: {\"choices\":[{\"delta\":{\"content\":\"hi\"}}]}\n");
        s.feed_chunk("data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"stop\"}]}\n");
        s.feed_chunk("data: [DONE]\n");
        let events = collect_events(&mut s);
        let names = event_names(&events);
        assert!(names.contains(&"response.output_text.done"));
        assert!(names.contains(&"response.content_part.done"));
        assert!(names.contains(&"response.output_item.done"));
        assert!(names.contains(&"response.completed"));
        // Find the completed event
        let completed = events
            .iter()
            .find(|e| e.event == "response.completed")
            .unwrap();
        assert_eq!(completed.data["response"]["status"], "completed");
        assert_eq!(completed.data["response"]["model"], "gpt-5.5");
        assert_eq!(completed.data["response"]["output"][0]["type"], "message");
    }

    #[test]
    fn stream_tool_call_delta_emits_added_and_arguments_delta() {
        let mut s = make_state(None);
        s.start();
        collect_events(&mut s);
        s.feed_chunk(
            "data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"id\":\"call_x\",\"function\":{\"name\":\"shell\",\"arguments\":\"{\\\"cmd\\\":\\\"ls\"}}]}}]}\n",
        );
        let events = collect_events(&mut s);
        let names = event_names(&events);
        assert!(names.contains(&"response.output_item.added"));
        assert!(names.contains(&"response.function_call_arguments.delta"));
        // Find the args delta
        let args_delta = events
            .iter()
            .find(|e| e.event == "response.function_call_arguments.delta")
            .unwrap();
        assert_eq!(args_delta.data["item_id"], "call_x");
        assert_eq!(args_delta.data["delta"], "{\"cmd\":\"ls");
    }

    #[test]
    fn stream_finish_emits_arguments_done_and_item_done_for_each_tool() {
        let mut s = make_state(None);
        s.start();
        collect_events(&mut s);
        s.feed_chunk("data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"id\":\"call_y\",\"function\":{\"name\":\"shell\",\"arguments\":\"{}\"}}]}}]}\n");
        s.feed_chunk("data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"tool_calls\"}]}\n");
        s.feed_chunk("data: [DONE]\n");
        let events = collect_events(&mut s);
        let names = event_names(&events);
        assert!(names.contains(&"response.function_call_arguments.done"));
        assert!(names.contains(&"response.output_item.done"));
        assert!(names.contains(&"response.completed"));
    }

    #[test]
    fn stream_tool_call_defers_added_until_name_arrives() {
        // Provider sends the call id in the first delta and the function
        // name only in a later one. `added` must be held until the name is
        // known, then precede any argument delta.
        let mut s = make_state(None);
        s.start();
        collect_events(&mut s);
        s.feed_chunk(
            "data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"id\":\"call_x\",\"function\":{\"arguments\":\"\"}}]}}]}\n",
        );
        let early = collect_events(&mut s);
        assert!(
            !event_names(&early).contains(&"response.output_item.added"),
            "added must be deferred until the name is known"
        );

        s.feed_chunk(
            "data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"function\":{\"name\":\"shell\",\"arguments\":\"{}\"}}]}}]}\n",
        );
        let later = collect_events(&mut s);
        let added_pos = later
            .iter()
            .position(|e| e.event == "response.output_item.added")
            .expect("added emitted once name arrives");
        let args_pos = later
            .iter()
            .position(|e| e.event == "response.function_call_arguments.delta")
            .expect("arguments forwarded after added");
        assert!(
            added_pos < args_pos,
            "added must precede the argument delta"
        );
        let added = &later[added_pos];
        assert_eq!(added.data["item"]["name"], "shell");
        assert_eq!(added.data["item"]["call_id"], "call_x");
        // The backlog ("{}") flushes in one delta once added fires.
        assert_eq!(later[args_pos].data["delta"], "{}");
    }

    #[test]
    fn stream_drops_tool_call_that_never_gets_a_name() {
        // A tool_call delta streams arguments but never supplies a name.
        // It must never be announced, never finalized, and absent from the
        // completed response output.
        let mut s = make_state(None);
        s.start();
        collect_events(&mut s);
        s.feed_chunk(
            "data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"id\":\"call_ghost\",\"function\":{\"arguments\":\"{\\\"a\\\":1}\"}}]}}]}\n",
        );
        s.feed_chunk("data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"tool_calls\"}]}\n");
        s.feed_chunk("data: [DONE]\n");
        let events = collect_events(&mut s);
        let names = event_names(&events);
        assert!(!names.contains(&"response.output_item.added"));
        assert!(!names.contains(&"response.output_item.done"));
        assert!(!names.contains(&"response.function_call_arguments.delta"));
        let completed = events
            .iter()
            .find(|e| e.event == "response.completed")
            .expect("response.completed emitted");
        let has_fn = completed.data["response"]["output"]
            .as_array()
            .map(|a| a.iter().any(|item| item["type"] == "function_call"))
            .unwrap_or(false);
        assert!(!has_fn, "never-named tool_call must not reach the output");
    }

    #[test]
    fn stream_length_finish_reason_emits_incomplete() {
        let mut s = make_state(None);
        s.start();
        collect_events(&mut s);
        s.feed_chunk("data: {\"choices\":[{\"delta\":{\"content\":\"truncated\"},\"finish_reason\":\"length\"}]}\n");
        s.feed_chunk("data: [DONE]\n");
        let events = collect_events(&mut s);
        let names = event_names(&events);
        assert!(names.contains(&"response.incomplete"));
        assert!(!names.contains(&"response.completed"));
        let incomplete = events
            .iter()
            .find(|e| e.event == "response.incomplete")
            .unwrap();
        assert_eq!(incomplete.data["response"]["status"], "incomplete");
        assert_eq!(
            incomplete.data["response"]["incomplete_details"]["reason"],
            "max_output_tokens"
        );
    }

    #[test]
    fn stream_partial_line_buffered_across_chunks() {
        let mut s = make_state(None);
        s.start();
        collect_events(&mut s);
        // Split a single SSE line across two feeds.
        s.feed_chunk("data: {\"choices\":[{\"delta\":{\"con");
        let mid = collect_events(&mut s);
        assert!(mid.is_empty(), "no events should fire on partial line");
        s.feed_chunk("tent\":\"abc\"}}]}\n");
        let events = collect_events(&mut s);
        let names = event_names(&events);
        assert!(names.contains(&"response.output_text.delta"));
    }

    #[test]
    fn stream_ignores_non_data_lines_and_blank_data() {
        let mut s = make_state(None);
        s.start();
        collect_events(&mut s);
        s.feed_chunk(": comment line\n");
        s.feed_chunk("event: ping\n");
        s.feed_chunk("data: \n");
        s.feed_chunk("\n");
        let events = collect_events(&mut s);
        assert!(events.is_empty());
    }

    #[test]
    fn stream_ignores_invalid_json_data() {
        let mut s = make_state(None);
        s.start();
        collect_events(&mut s);
        s.feed_chunk("data: not-json-at-all\n");
        let events = collect_events(&mut s);
        assert!(events.is_empty());
    }

    #[test]
    fn stream_usage_attached_to_completed_event() {
        let mut s = make_state(None);
        s.start();
        collect_events(&mut s);
        s.feed_chunk("data: {\"choices\":[{\"delta\":{\"content\":\"x\"}}]}\n");
        s.feed_chunk(
            "data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"stop\"}],\"usage\":{\"prompt_tokens\":7,\"completion_tokens\":1}}\n",
        );
        s.feed_chunk("data: [DONE]\n");
        let events = collect_events(&mut s);
        let completed = events
            .iter()
            .find(|e| e.event == "response.completed")
            .unwrap();
        assert_eq!(completed.data["response"]["usage"]["input_tokens"], 7);
        assert_eq!(completed.data["response"]["usage"]["output_tokens"], 1);
        // Mandatory nested objects always present.
        assert!(completed.data["response"]["usage"]["input_tokens_details"].is_object());
        assert!(completed.data["response"]["usage"]["output_tokens_details"].is_object());
    }

    #[test]
    fn stream_fail_emits_failed_event() {
        let mut s = make_state(None);
        s.start();
        collect_events(&mut s);
        s.feed_chunk("data: {\"choices\":[{\"delta\":{\"content\":\"partial\"}}]}\n");
        collect_events(&mut s);
        s.fail(
            "Upstream stream error: connection reset",
            "upstream_stream_error",
        );
        let events = collect_events(&mut s);
        let failed = events
            .iter()
            .find(|e| e.event == "response.failed")
            .unwrap();
        assert_eq!(failed.data["response"]["status"], "failed");
        assert_eq!(
            failed.data["response"]["error"]["code"],
            "upstream_stream_error"
        );
        assert_eq!(
            failed.data["response"]["error"]["message"],
            "Upstream stream error: connection reset"
        );
        // Partial output preserved.
        assert_eq!(failed.data["response"]["output"][0]["type"], "message");
    }

    #[test]
    fn stream_text_then_tool_call_closes_text_first() {
        let mut s = make_state(None);
        s.start();
        collect_events(&mut s);
        s.feed_chunk("data: {\"choices\":[{\"delta\":{\"content\":\"thinking\"}}]}\n");
        s.feed_chunk("data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"id\":\"call_z\",\"function\":{\"name\":\"shell\",\"arguments\":\"{}\"}}]}}]}\n");
        let events = collect_events(&mut s);
        let names = event_names(&events);
        // The text item must close BEFORE the tool item opens — Codex
        // chokes if a function_call.added appears while a message item
        // is still mid-stream.
        let text_done = names
            .iter()
            .position(|n| *n == "response.output_item.done")
            .unwrap();
        let tool_added = names
            .iter()
            .enumerate()
            .filter(|(_, n)| **n == "response.output_item.added")
            .map(|(i, _)| i)
            .next_back()
            .unwrap();
        assert!(text_done < tool_added);
    }

    #[test]
    fn stream_to_wire_serialization_is_event_data_format() {
        let evt = SseEvent::new("response.created", json!({"hello":"world"}));
        let wire = evt.to_wire();
        assert_eq!(
            wire,
            "event: response.created\ndata: {\"hello\":\"world\"}\n\n"
        );
    }

    // ---- annotation passthrough (OpenAI search-preview Chat extension) ----

    #[test]
    fn annotations_passthrough_on_part_done_and_item_done() {
        // OpenAI's search-preview / web_search_options Chat response
        // returns annotations on the assistant message; same shape as
        // Responses' output_text.annotations[]. Verify we forward the
        // full list verbatim instead of hardcoding [].
        let store = SessionStore::new();
        let mut state = StreamState::new(&store, Some("gpt-5".into()), vec![]);
        state.start();
        let _ = state.take_events();

        let ann = json!({
            "type": "url_citation",
            "url_citation": {
                "url": "https://example.com/article",
                "title": "Example Article",
                "start_index": 0,
                "end_index": 5,
            },
        });
        feed_chat_chunk(
            &mut state,
            json!({ "content": "Hello", "annotations": [ann.clone()] }),
        );
        state.finish(&store);
        let events = state.take_events();

        let part_done = events
            .iter()
            .find(|e| e.event == "response.content_part.done")
            .expect("content_part.done emitted");
        assert_eq!(part_done.data["part"]["annotations"], json!([ann.clone()]));

        let item_done = events
            .iter()
            .find(|e| e.event == "response.output_item.done")
            .expect("output_item.done emitted");
        assert_eq!(
            item_done.data["item"]["content"][0]["annotations"],
            json!([ann])
        );
    }

    #[test]
    fn annotations_accumulate_across_multiple_chunks() {
        // Each chunk's delta.annotations is incremental — concatenate
        // rather than overwrite.
        let store = SessionStore::new();
        let mut state = StreamState::new(&store, Some("gpt-5".into()), vec![]);
        state.start();
        let _ = state.take_events();

        let ann1 = json!({ "type": "url_citation", "url_citation": { "url": "https://a.com" } });
        let ann2 = json!({ "type": "url_citation", "url_citation": { "url": "https://b.com" } });

        feed_chat_chunk(
            &mut state,
            json!({ "content": "First.", "annotations": [ann1.clone()] }),
        );
        feed_chat_chunk(
            &mut state,
            json!({ "content": " Second.", "annotations": [ann2.clone()] }),
        );
        state.finish(&store);
        let events = state.take_events();

        let part_done = events
            .iter()
            .find(|e| e.event == "response.content_part.done")
            .unwrap();
        assert_eq!(part_done.data["part"]["annotations"], json!([ann1, ann2]));
    }

    #[test]
    fn refusal_delta_emits_refusal_event_sequence() {
        // Upstream Chat returns delta.refusal when the model declines.
        // We synthesize response.refusal.delta + .done + the surrounding
        // content_part / output_item events so Codex shows the refusal
        // text instead of an empty assistant message.
        let store = SessionStore::new();
        let mut state = StreamState::new(&store, Some("gpt-5".into()), vec![]);
        state.start();
        let _ = state.take_events();

        feed_chat_chunk(&mut state, json!({ "refusal": "I can't help with that." }));
        state.finish(&store);
        let events = state.take_events();
        let names = event_names(&events);

        assert!(names.contains(&"response.refusal.delta"), "got: {names:?}");
        assert!(names.contains(&"response.refusal.done"), "got: {names:?}");

        let delta_evt = events
            .iter()
            .find(|e| e.event == "response.refusal.delta")
            .unwrap();
        assert_eq!(delta_evt.data["delta"], "I can't help with that.");

        let done_evt = events
            .iter()
            .find(|e| e.event == "response.refusal.done")
            .unwrap();
        assert_eq!(done_evt.data["refusal"], "I can't help with that.");

        // The output_item.done for the refusal item carries refusal
        // content-part type (not output_text).
        let item_done = events
            .iter()
            .find(|e| {
                e.event == "response.output_item.done"
                    && e.data["item"]["content"][0]["type"] == "refusal"
            })
            .expect("output_item.done with refusal part");
        assert_eq!(
            item_done.data["item"]["content"][0]["refusal"],
            "I can't help with that."
        );
    }

    #[test]
    fn refusal_accumulates_across_multiple_deltas() {
        let store = SessionStore::new();
        let mut state = StreamState::new(&store, Some("gpt-5".into()), vec![]);
        state.start();
        let _ = state.take_events();

        feed_chat_chunk(&mut state, json!({ "refusal": "I can't " }));
        feed_chat_chunk(&mut state, json!({ "refusal": "help with that." }));
        state.finish(&store);
        let events = state.take_events();

        let done_evt = events
            .iter()
            .find(|e| e.event == "response.refusal.done")
            .unwrap();
        assert_eq!(done_evt.data["refusal"], "I can't help with that.");
    }

    #[test]
    fn system_fingerprint_and_service_tier_echoed_on_completed() {
        // Chunk-level envelope fields — capture last-seen, emit on
        // response.completed so Codex can detect upstream config
        // changes (system_fingerprint) and which tier ran (service_tier).
        let store = SessionStore::new();
        let mut state = StreamState::new(&store, Some("gpt-5".into()), vec![]);
        state.start();
        let _ = state.take_events();

        // Inject a chunk with envelope fields.
        let payload = json!({
            "system_fingerprint": "fp_abc123",
            "service_tier": "scale",
            "choices": [{ "delta": { "content": "hi" } }],
        });
        state.feed_chunk(&format!("data: {}\n", payload));
        state.finish(&store);
        let events = state.take_events();

        let completed = events
            .iter()
            .find(|e| e.event == "response.completed")
            .expect("response.completed emitted");
        assert_eq!(
            completed.data["response"]["system_fingerprint"],
            "fp_abc123"
        );
        assert_eq!(completed.data["response"]["service_tier"], "scale");
    }

    #[test]
    fn envelope_fields_omitted_when_upstream_doesnt_send_them() {
        // Third-party providers (DeepSeek, Kimi, GLM) don't emit
        // system_fingerprint or service_tier. We must NOT inject
        // defaults — leave the keys absent so consumers can detect
        // "upstream didn't say".
        let store = SessionStore::new();
        let mut state = StreamState::new(&store, Some("gpt-5".into()), vec![]);
        state.start();
        let _ = state.take_events();

        feed_chat_chunk(&mut state, json!({ "content": "hi" }));
        state.finish(&store);
        let events = state.take_events();

        let completed = events
            .iter()
            .find(|e| e.event == "response.completed")
            .unwrap();
        assert!(completed.data["response"]
            .get("system_fingerprint")
            .is_none());
        assert!(completed.data["response"].get("service_tier").is_none());
    }

    #[test]
    fn annotations_empty_when_upstream_omits_them() {
        // Existing behavior preserved when upstream sends no annotations:
        // emit an empty array rather than null or missing key.
        let store = SessionStore::new();
        let mut state = StreamState::new(&store, Some("gpt-5".into()), vec![]);
        state.start();
        let _ = state.take_events();

        feed_chat_chunk(&mut state, json!({ "content": "plain text" }));
        state.finish(&store);
        let events = state.take_events();

        let part_done = events
            .iter()
            .find(|e| e.event == "response.content_part.done")
            .unwrap();
        assert_eq!(part_done.data["part"]["annotations"], json!([]));
    }
}