// Responses API → Chat Completions request translator.
//
// Direct port of tools/codex/lib/protocol-converter.cjs. Behavior parity
// is the goal — every branch in the JS version has a matching branch
// here, with the same dedup rules, the same MiniMax detour, the same
// reorder pass for tool-message pairing, the same tool-array filter.
//
// Why the dictionary is non-trivial: Codex's Responses API input is a
// heterogeneous array of items where every turn / tool call / model
// reasoning step / context-compaction summary lands as a typed
// dictionary entry. Faithful translation matters because dropping even
// one item type produces a Chat Completions message array the upstream
// rejects (the "insufficient tool messages" class of error documented
// in issue #38).

use serde_json::{json, Value};
use std::collections::{BTreeSet, HashSet};

use super::content_mapper::value_to_chat_content;
use super::session_store::SessionStore;
use super::vendors::{adapter_for, WebSearchSupport};

/// Translate one Codex Responses-API request body into the equivalent
/// Chat Completions request body. Returns a fresh JSON value ready to
/// serialize and POST to the upstream `/v1/chat/completions`.
pub fn responses_to_chat(body: &Value, sessions: &SessionStore) -> Value {
    // 1) Replay history stashed under previous_response_id, if any.
    // If Codex hands us an id we don't have a record of (proxy restart,
    // FIFO eviction past MAP_CAPACITY, second EchoBird instance), the
    // conversation silently degrades to "first turn" semantics. Surface
    // it in logs so the silent-forget case is at least diagnosable.
    let mut messages: Vec<Value> = body
        .get("previous_response_id")
        .and_then(|v| v.as_str())
        .map(|id| {
            if !id.is_empty() && !sessions.has_history(id) {
                log::warn!(
                    "[CodexProxy] previous_response_id={id} not in session store — replaying as fresh conversation"
                );
            }
            sessions.get_history(id)
        })
        .unwrap_or_default();

    // 2) System instructions — prepend if the message list doesn't
    // already start with one; REPLACE the head if a different
    // instructions value is supplied. The spec says `instructions`
    // applies only to the current call — when Codex changes
    // instructions mid-conversation, the new value must take effect
    // rather than the old one persisting from `previous_response_id`
    // history replay (L10).
    if let Some(instr) = body.get("instructions").and_then(|v| v.as_str()) {
        if !instr.is_empty() {
            let head_is_system = messages
                .first()
                .and_then(|m| m.get("role"))
                .and_then(|v| v.as_str())
                == Some("system");
            if head_is_system {
                // Replace existing head system content with the new
                // instructions text. Keeps message ordering stable.
                if let Some(first) = messages.first_mut() {
                    first["content"] = Value::String(instr.to_string());
                }
            } else {
                messages.insert(0, json!({ "role": "system", "content": instr }));
            }
        }
    }

    // 3) Input: either a plain string ("user said this") or an array of
    // typed items (the heterogeneous turn history).
    if let Some(s) = body.get("input").and_then(|v| v.as_str()) {
        messages.push(json!({ "role": "user", "content": s }));
    } else if let Some(items) = body.get("input").and_then(|v| v.as_array()) {
        process_input_items(&mut messages, items, sessions);
    }

    // 3b) Empty-function-name guard (issue #206). A tool_call whose
    // function.name is empty is unusable and makes strict third-party
    // providers (Xiaomi MiMo, ...) 400 the whole request. Drop those
    // calls and their paired results before any further shaping so the
    // conversation degrades gracefully instead of dying hard.
    strip_nameless_tool_calls(&mut messages);

    // 4) Provider-specific message-list shaping.
    let is_minimax = body
        .get("model")
        .and_then(|v| v.as_str())
        .map(|m| m.to_lowercase().contains("minimax"))
        .unwrap_or(false);
    let mut merged = if is_minimax {
        minimax_merge(messages)
    } else {
        coalesce_consecutive(messages)
    };

    // 5) Reorder so every assistant.tool_calls is followed immediately
    // by its matching tool messages.
    merged = reorder_tool_messages(merged);

    // 5a) Orphan tool-call backstop. When Codex sends function_call items
    // without their matching function_call_output (e.g. user interrupted
    // mid-tool-execution, or a Codex client bug like openai/codex#8479),
    // the upstream gets assistant{tool_calls} with no role:tool follow-up
    // and 400s with "tool_calls require matching tool messages". Synth
    // a placeholder tool message for every unmatched call_id so the
    // conversation stays alive — the model sees "(no result)" and can
    // re-plan rather than dying hard.
    ensure_tool_outputs_paired(&mut merged);

    // 5b) Defensive guard for thinking-model providers (MiMo, DeepSeek-V4
    // thinking variants, etc.). Anything that flowed in via
    // `previous_response_id` history replay — or a stranger path we don't
    // yet model — could be missing `reasoning_content`. We look one more
    // time across every available SessionStore key before committing.
    // Last-resort placeholder ensures the upstream API contract is met
    // even when our store has nothing; without it some providers 400 with
    // "The reasoning_content in the thinking mode must be passed back".
    ensure_reasoning_for_tool_calls(&mut merged, sessions);

    // 6) Assemble the Chat Completions request body.
    let stream_default = body.get("stream").and_then(|v| v.as_bool()).unwrap_or(true);
    let mut chat_body = json!({
        "model": body.get("model").cloned().unwrap_or(Value::Null),
        "messages": merged,
        "stream": stream_default,
    });

    // include_usage: OpenAI-compatible upstreams only emit the trailing
    // usage chunk on a *streaming* response when `stream_options.include_usage`
    // is set. Codex's Responses requests never carry `stream_options`, so
    // without this injection the streamed token / cost / cache-hit stats come
    // back zero for Kimi / MiniMax / DeepSeek etc. — and Codex reads those
    // numbers to drive its context-window tracking and auto-compact trigger,
    // so silently-zero usage isn't just cosmetic. Inject only when streaming;
    // merge into any client-supplied `stream_options` rather than clobbering
    // it (Codex doesn't send one today, but a future client might).
    if stream_default {
        // Seed from any client-supplied stream_options (preserves fields like
        // continuous_usage_stats), then force include_usage on.
        let mut opts = body
            .get("stream_options")
            .and_then(|v| v.as_object())
            .cloned()
            .unwrap_or_default();
        opts.insert("include_usage".to_string(), Value::Bool(true));
        chat_body["stream_options"] = Value::Object(opts);
    }

    if let Some(v) = body.get("max_output_tokens") {
        if !v.is_null() {
            chat_body["max_tokens"] = v.clone();
        }
    }
    if let Some(v) = body.get("temperature") {
        if !v.is_null() {
            chat_body["temperature"] = v.clone();
        }
    }
    // stop_sequences is the Responses-API name; some clients pass it
    // through as "stop". Either is fine on the Chat side.
    if let Some(v) = body.get("stop_sequences") {
        if !v.is_null() {
            chat_body["stop"] = v.clone();
        }
    }
    if let Some(v) = body.get("stop") {
        if !v.is_null() {
            chat_body["stop"] = v.clone();
        }
    }

    // 6b) Pass-through fields that Chat Completions accepts verbatim.
    // Previously dropped silently — Codex sends these on every request,
    // and ignoring them gave users no effect when they tuned settings.
    //
    //   • reasoning.effort     → `reasoning_effort` (Chat side name).
    //                            OpenAI o-series + many third-parties
    //                            honor it. We translate `summary`
    //                            separately by emitting reasoning
    //                            summary events ourselves (H1).
    //   • parallel_tool_calls  → passthrough; defaults to true upstream
    //   • top_p, frequency_penalty, presence_penalty, seed, user,
    //     prompt_cache_key, service_tier, safety_identifier,
    //     max_tool_calls, metadata
    //                          → straight passthrough on non-null
    //   • text.format          → structured outputs (json_schema /
    //                            text). Mapped to Chat's
    //                            `response_format`.
    if let Some(reasoning) = body.get("reasoning") {
        if let Some(effort) = reasoning.get("effort").and_then(|v| v.as_str()) {
            // Third-party Chat-Completions upstreams (MiMo, DeepSeek,
            // most non-OpenAI providers) validate `reasoning_effort`
            // strictly against the legacy enum {low, medium, high} and
            // 400 on anything else. OpenAI's GPT-5 family added two
            // new levels — `minimal` (below low) and `xhigh` (above
            // high) — that Codex CLI sends when the user dials effort
            // to the extreme. Clamp those to the nearest legacy bucket
            // so the request survives; pass every other value through
            // so we don't break when upstream adds a tier we haven't
            // mapped yet.
            let normalized = match effort {
                "minimal" => "low",
                "xhigh" => "high",
                other => other,
            };
            chat_body["reasoning_effort"] = Value::String(normalized.to_string());
        }
    }
    for key in &[
        "parallel_tool_calls",
        "top_p",
        "frequency_penalty",
        "presence_penalty",
        "seed",
        "user",
        "prompt_cache_key",
        "service_tier",
        "safety_identifier",
        "max_tool_calls",
        "metadata",
        // M12: `truncation` — "auto" lets the upstream silently drop
        //   oldest turns when prompt exceeds context. Chat API also
        //   accepts it now (mid-2026); pass through verbatim.
        "truncation",
        // L6: `include` — array of additional fields to surface on
        //   the response (e.g. ["reasoning.encrypted_content",
        //   "message.output_text.logprobs"]). Upstream Chat tolerates
        //   the field as unknown; OpenAI-direct uses it natively.
        "include",
    ] {
        if let Some(v) = body.get(*key) {
            if !v.is_null() {
                chat_body[*key] = v.clone();
            }
        }
    }
    // text.format → response_format. The Responses-API shape nests
    // under `text.format`; Chat expects `response_format` at the top.
    //
    // We pass `json_object`, `text`, and `json_schema` through verbatim.
    // The Responses shape `{name, schema, strict}` is repackaged into
    // Chat's `{json_schema: {name, schema, strict}}` envelope.
    //
    // For `json_schema` specifically: OpenAI Chat has natively accepted
    // this since 2024-08. Third-party providers that don't support it
    // (DeepSeek, MiMo, some Qwen / GLM deployments) will 400 with a
    // clear error message — that's strictly better than silently
    // dropping the schema and producing free-form text the user
    // expected to be structured. Let the upstream tell us.
    if let Some(text) = body.get("text") {
        if let Some(format) = text.get("format") {
            let format_type = format.get("type").and_then(|v| v.as_str()).unwrap_or("");
            match format_type {
                "json_object" | "text" => {
                    chat_body["response_format"] = json!({ "type": format_type });
                }
                "json_schema" => {
                    let mut inner = serde_json::Map::new();
                    if let Some(name) = format.get("name") {
                        inner.insert("name".to_string(), name.clone());
                    }
                    if let Some(schema) = format.get("schema") {
                        inner.insert("schema".to_string(), schema.clone());
                    }
                    if let Some(strict) = format.get("strict") {
                        inner.insert("strict".to_string(), strict.clone());
                    }
                    chat_body["response_format"] = json!({
                        "type": "json_schema",
                        "json_schema": Value::Object(inner),
                    });
                }
                // Unknown format types: silently dropped. Future-proofs
                // against new OpenAI format extensions we haven't seen.
                _ => {}
            }
        }
    }

    // 7) Tool definitions filter. Built-in Responses tools (local_shell,
    // web_search, file_search, computer_use_preview, custom, ...) have
    // no Chat Completions analogue — passing them through as
    // type=function would produce `tools[N].function: missing field
    // "name"` 400s upstream. Keep only `function` and unpack `namespace`.
    if let Some(tools) = body.get("tools").and_then(|v| v.as_array()) {
        // Codex's built-in `web_search` Responses tool has no universal Chat
        // analogue, and every vendor exposes search differently (MiMo: bare
        // tool, GLM: nested tool, Qwen: a request param). Route by the real
        // upstream model id through a per-vendor adapter — see
        // codex_proxy::vendors. Generic upstreams drop it (a bare
        // `{type:"web_search"}` 400s a provider that doesn't recognize it).
        let adapter = adapter_for(body.get("model").and_then(|v| v.as_str()).unwrap_or(""));
        let mut out: Vec<Value> = Vec::new();
        let mut dropped: Vec<String> = Vec::new();
        // Request-body params some vendors use to enable search instead of a
        // tool (e.g. Qwen's `enable_search`); applied after the tool loop.
        let mut web_search_params: Vec<(String, Value)> = Vec::new();
        for tool in tools {
            let tt = tool.get("type").and_then(|v| v.as_str());
            match tt {
                Some("function") => out.push(normalize_function_tool(tool)),
                Some("namespace") => {
                    // Codex wraps MCP / extension tools as
                    // `{type:"namespace", name:"mcp__<server>", tools:[{type:
                    // "function", name:"<bare-tool>"}]}`. A flat Chat `tools`
                    // array has no namespace grouping, so we lift each inner
                    // function AND qualify its bare name to Codex's canonical
                    // `mcp__<server>__<tool>` form — otherwise bare names
                    // collide across namespaces (strict providers 400 on
                    // duplicate names) and the returned call can't be routed.
                    let ns_name = tool.get("name").and_then(|v| v.as_str()).unwrap_or("");
                    if let Some(subs) = tool.get("tools").and_then(|v| v.as_array()) {
                        for sub in subs {
                            if sub.get("type").and_then(|v| v.as_str()) == Some("function") {
                                let mut fn_tool = normalize_function_tool(sub);
                                qualify_namespaced_tool_name(&mut fn_tool, ns_name);
                                out.push(fn_tool);
                            }
                        }
                    }
                }
                Some("web_search") => match adapter.web_search() {
                    WebSearchSupport::RequestParams(params) => web_search_params = params,
                    WebSearchSupport::ToolWithParams(t, params) => {
                        out.push(t);
                        web_search_params = params;
                    }
                    WebSearchSupport::Drop => dropped.push("web_search".to_string()),
                },
                Some(other) => dropped.push(other.to_string()),
                None => {}
            }
        }
        if !out.is_empty() {
            chat_body["tools"] = Value::Array(out);
            if let Some(tc) = body.get("tool_choice") {
                if !tc.is_null() {
                    chat_body["tool_choice"] = tc.clone();
                }
            }
        }
        // Apply vendor request-body search params (e.g. Qwen enable_search).
        for (key, value) in web_search_params {
            chat_body[key] = value;
        }
        if !dropped.is_empty() {
            let unique: BTreeSet<&str> = dropped.iter().map(String::as_str).collect();
            let list: Vec<&str> = unique.into_iter().collect();
            log::warn!(
                "[CodexProxy] Dropped {} non-function tool(s): {}",
                dropped.len(),
                list.join(", ")
            );
        }
    }

    chat_body
}

// ────────────────────────────────────────────────────────────────────
// Item-array processing: heterogeneous Responses items → flat messages.
// ────────────────────────────────────────────────────────────────────

fn process_input_items(messages: &mut Vec<Value>, items: &[Value], sessions: &SessionStore) {
    // Per-call dedup: when previous_response_id + input both replay the
    // same items we don't want them twice in the upstream history.
    let mut emitted_call_ids: HashSet<String> = HashSet::new();
    let mut emitted_tool_responses: HashSet<String> = HashSet::new();
    // Reasoning text from a preceding `reasoning` item, waiting to be
    // attached to the next assistant.tool_calls message we construct.
    let mut pending_reasoning: Option<String> = None;

    let mut i = 0;
    while i < items.len() {
        let item = &items[i];
        let t = item.get("type").and_then(|v| v.as_str()).unwrap_or("");

        // ── function_call (group all consecutive into one assistant) ──
        if t == "function_call" {
            let mut grouped: Vec<Value> = Vec::new();
            while i < items.len()
                && items[i].get("type").and_then(|v| v.as_str()) == Some("function_call")
            {
                let cur = &items[i];
                let call_id = extract_call_id(cur).unwrap_or_else(random_call_id);
                if !emitted_call_ids.contains(&call_id) {
                    emitted_call_ids.insert(call_id.clone());
                    let name = cur
                        .get("name")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string();
                    let args = stringify_args(cur.get("arguments"));
                    grouped.push(json!({
                        "id": call_id,
                        "type": "function",
                        "function": { "name": name, "arguments": args },
                    }));
                }
                i += 1;
            }
            if !grouped.is_empty() {
                push_assistant_tool_calls(messages, grouped, sessions, &mut pending_reasoning);
            }
            continue;
        }

        // ── tool-result items (function_call_output, *_call_output, tool_search_output, ...) ──
        // Suffix is `_output` rather than `_call_output` because some
        // newer types (tool_search_output) drop the `_call_` infix.
        // call_id required to avoid catching content parts like
        // `output_text` / `output_image`.
        if t.ends_with("_output") && item.get("call_id").is_some() {
            if let Some(call_id) = item
                .get("call_id")
                .and_then(|v| v.as_str())
                .map(String::from)
            {
                if !emitted_tool_responses.contains(&call_id) {
                    emitted_tool_responses.insert(call_id.clone());
                    let content = stringify_output(item.get("output"));
                    messages.push(json!({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": content,
                    }));
                }
            }
            i += 1;
            continue;
        }

        // ── local_shell_call (Codex's built-in shell tool) ──
        if t == "local_shell_call" {
            let call_id = extract_call_id(item).unwrap_or_else(random_call_id);
            if !emitted_call_ids.contains(&call_id) {
                emitted_call_ids.insert(call_id.clone());
                let args = match item.get("action") {
                    Some(v) => serde_json::to_string(v).unwrap_or_else(|_| "{}".to_string()),
                    None => "{}".to_string(),
                };
                let tool_calls = vec![json!({
                    "id": call_id,
                    "type": "function",
                    "function": { "name": "local_shell", "arguments": args },
                })];
                push_assistant_tool_calls(messages, tool_calls, sessions, &mut pending_reasoning);
            }
            i += 1;
            continue;
        }

        // ── reasoning (buffer for next assistant.tool_calls) ──
        //
        // Read order:
        //   1. `encrypted_content` (preferred — our /compact handler
        //      writes the upstream summary here, and OpenAI's native
        //      flow stores latent state here when `include` was set)
        //   2. `summary[].text` array  (OpenAI's normal reasoning item
        //      shape: `[{type:"summary_text",text:"..."}]`)
        //   3. `summary` raw string  (legacy / our older synthesizer)
        //   4. `text` / `content` fallback
        if t == "reasoning" {
            let mut summary_str = String::new();
            if let Some(enc) = item.get("encrypted_content").and_then(|v| v.as_str()) {
                if !enc.is_empty() && !enc.starts_with("gAAAAA") {
                    summary_str = enc.to_string();
                }
            }
            if summary_str.is_empty() {
                if let Some(arr) = item.get("summary").and_then(|v| v.as_array()) {
                    let parts: Vec<&str> = arr
                        .iter()
                        .filter_map(|p| p.get("text").and_then(|v| v.as_str()))
                        .collect();
                    if !parts.is_empty() {
                        summary_str = parts.join("");
                    }
                }
            }
            if summary_str.is_empty() {
                let raw = item
                    .get("summary")
                    .or_else(|| item.get("text"))
                    .or_else(|| item.get("content"));
                summary_str = match raw {
                    Some(Value::String(s)) => s.clone(),
                    Some(other) => other.to_string(),
                    None => String::new(),
                };
            }
            if !summary_str.is_empty() {
                pending_reasoning = Some(summary_str);
            }
            i += 1;
            continue;
        }

        // ── message (user / assistant / system / developer→system) ──
        if t == "message" {
            let mut role = item
                .get("role")
                .and_then(|v| v.as_str())
                .unwrap_or("user")
                .to_string();
            if role == "developer" {
                role = "system".to_string();
            }
            let content = value_to_chat_content(item.get("content"));
            let has_content = match &content {
                Value::String(s) => !s.is_empty(),
                Value::Array(a) => !a.is_empty(),
                _ => false,
            };
            if has_content {
                let mut msg = json!({ "role": role, "content": content });
                if role == "assistant" {
                    let rc_from_store = sessions.get_turn_reasoning(&msg["content"]);
                    let rc = if let Some(r) = rc_from_store {
                        Some(r)
                    } else if let Some(r) = pending_reasoning.take() {
                        sessions.store_turn_reasoning(&msg["content"], &r);
                        Some(r)
                    } else {
                        None
                    };
                    if let Some(r) = rc {
                        msg["reasoning_content"] = Value::String(r);
                    }
                }
                messages.push(msg);
            }
            i += 1;
            continue;
        }

        // ── compaction (Codex 0.130+ context compaction) ──
        //
        // Codex sends a compaction item back in the input when it has
        // previously called /v1/responses/compact. OpenAI's native flow
        // ships `encrypted_content` as an opaque blob the model server
        // decrypts. Our /v1/responses/compact handler instead writes a
        // plain-text upstream-generated summary into the same field
        // (the upstream we proxy can't do real encrypted compaction).
        //
        // So: prefer the summary text from `encrypted_content` when it
        // looks like real text; fall back to the generic placeholder
        // when it's empty or actually-opaque (a real OpenAI blob that
        // somehow ended up here).
        // Alias: Codex's newer enum has `context_compaction` (with
        // underscore) as a distinct variant for the standalone-endpoint
        // compaction. Treat identically.
        if t == "compaction" || t == "context_compaction" {
            let summary = item
                .get("encrypted_content")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let content = if !summary.is_empty()
                && !summary.starts_with("gAAAAA")  // common encrypted prefix
                && summary.is_char_boundary(summary.len().min(8))
            {
                format!("[Summary of earlier conversation (from compaction)]\n{summary}")
            } else {
                "[Earlier portion of this conversation was compacted by Codex and is not available to the model.]".to_string()
            };
            messages.push(json!({
                "role": "system",
                "content": content,
            }));
            i += 1;
            continue;
        }

        // ── compaction_trigger (remote-compaction-v2 sentinel) ──
        // Codex appends a bare `{"type":"compaction_trigger"}` to the input
        // of a remote-compaction-v2 request to signal "summarize now". It
        // carries no content; the real handling lives in server.rs
        // (handle_inline_compaction). If one reaches the translator, drop it
        // — turning it into a message would pollute the summarization input.
        if t == "compaction_trigger" {
            i += 1;
            continue;
        }

        // ── tool_search_call / web_search_call / image_generation_call ──
        // Codex echoes these in input when the prior turn used the
        // built-in search/generation tools. They don't have a Chat
        // Completions analogue — we synthesize a system note so the
        // model knows a search/generation happened without hard-erroring
        // on "unknown input item type". When the tool result is
        // available (call_id present + matching *_output), the result
        // text is what actually mattered.
        if t == "web_search_call"
            || t == "tool_search_call"
            || t == "image_generation_call"
            || t == "file_search_call"
        {
            let kind = t.trim_end_matches("_call");
            let action = item.get("action").or_else(|| item.get("query"));
            let action_str = match action {
                Some(Value::String(s)) => s.clone(),
                Some(other) => serde_json::to_string(other).unwrap_or_default(),
                None => String::new(),
            };
            let note = if action_str.is_empty() {
                format!("[Codex used the built-in {kind} tool earlier; result is in the next tool output below.]")
            } else {
                format!("[Codex used the built-in {kind} tool: {action_str}]")
            };
            messages.push(json!({
                "role": "system",
                "content": note,
            }));
            i += 1;
            continue;
        }

        // ── generic *_call (custom_tool_call, apply_patch_tool_call, etc.) ──
        // Wrapped as function-style tool_calls so the upstream understands
        // the assistant→tool round-trip. Tool name derives from item.type
        // by stripping the trailing `_call`, unless an explicit `name`
        // is present. Argument field varies (`arguments` for function_call,
        // `input` for custom_tool_call, `action` for local_shell_call).
        if t.ends_with("_call") && item.get("call_id").is_some() {
            if let Some(call_id) = item
                .get("call_id")
                .and_then(|v| v.as_str())
                .map(String::from)
            {
                if !emitted_call_ids.contains(&call_id) {
                    emitted_call_ids.insert(call_id.clone());
                    let tool_name = item
                        .get("name")
                        .and_then(|v| v.as_str())
                        .map(String::from)
                        .unwrap_or_else(|| t.trim_end_matches("_call").to_string());
                    let raw_args = item
                        .get("arguments")
                        .or_else(|| item.get("input"))
                        .or_else(|| item.get("action"));
                    let args = match raw_args {
                        Some(Value::String(s)) => s.clone(),
                        Some(other) => {
                            serde_json::to_string(other).unwrap_or_else(|_| "{}".to_string())
                        }
                        None => "{}".to_string(),
                    };
                    let tool_calls = vec![json!({
                        "id": call_id,
                        "type": "function",
                        "function": { "name": tool_name, "arguments": args },
                    })];
                    push_assistant_tool_calls(
                        messages,
                        tool_calls,
                        sessions,
                        &mut pending_reasoning,
                    );
                }
            }
            i += 1;
            continue;
        }

        log::warn!("[CodexProxy] Skipping unknown input item type: {t}");
        i += 1;
    }
}

// ────────────────────────────────────────────────────────────────────
// Helpers
// ────────────────────────────────────────────────────────────────────

fn extract_call_id(item: &Value) -> Option<String> {
    item.get("call_id")
        .or_else(|| item.get("id"))
        .and_then(|v| v.as_str())
        .map(String::from)
}

fn random_call_id() -> String {
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
    format!("call_{}", suffix)
}

fn stringify_args(v: Option<&Value>) -> String {
    match v {
        Some(Value::String(s)) => s.clone(),
        Some(other) => serde_json::to_string(other).unwrap_or_else(|_| "{}".to_string()),
        None => "{}".to_string(),
    }
}

fn stringify_output(v: Option<&Value>) -> String {
    match v {
        Some(Value::String(s)) => s.clone(),
        Some(Value::Null) | None => "\"\"".to_string(),
        // Spec: function_call_output.output can be a structured array of
        // content items (`[{type:"output_text",text:...}]` or
        // `[{type:"input_text",text:...}]`) rather than a plain string.
        // Join the text parts so the upstream sees natural text, not a
        // JSON-encoded array the model has to parse.
        Some(Value::Array(parts)) => {
            let collected: Vec<&str> = parts
                .iter()
                .filter_map(|p| {
                    p.get("text")
                        .and_then(|v| v.as_str())
                        .filter(|s| !s.is_empty())
                })
                .collect();
            if collected.is_empty() {
                // Array but no text parts → fall back to JSON stringify
                // so structured non-text content (e.g. image refs) at
                // least lands as readable JSON.
                serde_json::to_string(v.unwrap()).unwrap_or_else(|_| "\"\"".to_string())
            } else {
                collected.join("")
            }
        }
        Some(other) => serde_json::to_string(other).unwrap_or_else(|_| "\"\"".to_string()),
    }
}

fn push_assistant_tool_calls(
    messages: &mut Vec<Value>,
    tool_calls: Vec<Value>,
    sessions: &SessionStore,
    pending_reasoning: &mut Option<String>,
) {
    let first_id = tool_calls
        .first()
        .and_then(|tc| tc.get("id"))
        .and_then(|v| v.as_str())
        .map(String::from)
        .unwrap_or_default();
    let mut reasoning = if !first_id.is_empty() {
        sessions.get_reasoning(&first_id)
    } else {
        None
    };
    if reasoning.is_none() {
        if let Some(pending) = pending_reasoning.take() {
            // Persist under every call_id so subsequent turns find it.
            for tc in &tool_calls {
                if let Some(id) = tc.get("id").and_then(|v| v.as_str()) {
                    sessions.store_reasoning(id, &pending);
                }
            }
            reasoning = Some(pending);
        }
    }
    let mut msg = json!({
        "role": "assistant",
        "content": Value::Null,
        "tool_calls": tool_calls,
    });
    if let Some(r) = reasoning {
        msg["reasoning_content"] = Value::String(r);
    }
    messages.push(msg);
}

/// Orphan tool-call backstop. Every `id` listed in an assistant message's
/// `tool_calls` array must have a matching `role: "tool"` message present
/// somewhere in the request — otherwise the upstream Chat Completions API
/// rejects with "messages with tool_calls require matching tool messages"
/// (or a 400 phrased similarly). Codex normally pairs them, but real-world
/// failure modes leave orphans behind:
///
///   • User cancels mid-parallel-tool-call → some outputs never sent
///   • Codex client desync (e.g. openai/codex#8479) → tool_call emitted
///     but matching function_call_output omitted on next turn
///   • previous_response_id history replay racing input items
///
/// For each orphaned call_id we splice in a `{role: "tool", tool_call_id,
/// content: "(no result)"}` placeholder right after the assistant message
/// that introduced it. The model sees the gap explicitly and can re-plan
/// rather than the whole conversation dying with a 400.
fn ensure_tool_outputs_paired(messages: &mut Vec<Value>) {
    use std::collections::HashSet;

    // First pass: collect every tool_call_id that already has a tool
    // message somewhere. (A tool message in any position counts — Anthropic
    // is strict about adjacency, Chat Completions APIs are lenient.)
    let mut satisfied: HashSet<String> = HashSet::new();
    for m in messages.iter() {
        if m.get("role").and_then(|v| v.as_str()) == Some("tool") {
            if let Some(id) = m.get("tool_call_id").and_then(|v| v.as_str()) {
                satisfied.insert(id.to_string());
            }
        }
    }

    // Second pass: for every assistant tool_calls message, find any
    // call_id that isn't satisfied, and remember where to splice the
    // synthetic tool message (right after this assistant message).
    let mut inserts: Vec<(usize, Vec<String>)> = Vec::new();
    for (i, m) in messages.iter().enumerate() {
        if m.get("role").and_then(|v| v.as_str()) != Some("assistant") {
            continue;
        }
        let Some(tcs) = m.get("tool_calls").and_then(|v| v.as_array()) else {
            continue;
        };
        let missing: Vec<String> = tcs
            .iter()
            .filter_map(|tc| tc.get("id").and_then(|v| v.as_str()).map(String::from))
            .filter(|id| !satisfied.contains(id))
            .collect();
        if !missing.is_empty() {
            // Mark as now-satisfied so the same call_id doesn't get a
            // second placeholder if it appears in a later assistant.
            for id in &missing {
                satisfied.insert(id.clone());
            }
            inserts.push((i, missing));
        }
    }

    if inserts.is_empty() {
        return;
    }

    // Splice in reverse so earlier indices stay valid.
    for (idx, ids) in inserts.into_iter().rev() {
        log::warn!(
            "[CodexProxy] Synthesizing placeholder tool messages for orphan call_ids {:?} \
             after assistant at index {}",
            ids,
            idx
        );
        let placeholders: Vec<Value> = ids
            .into_iter()
            .map(|id| {
                json!({
                    "role": "tool",
                    "tool_call_id": id,
                    "content": "(no result — tool execution was interrupted)",
                })
            })
            .collect();
        // Insert each placeholder at idx+1; insertion is contiguous so
        // they end up in `tool_calls` order right after the assistant.
        for (offset, p) in placeholders.into_iter().enumerate() {
            messages.insert(idx + 1 + offset, p);
        }
    }
}

/// Last-mile guard: every assistant message with `tool_calls` must carry
/// a non-empty `reasoning_content` field before we send to upstream.
/// Required by thinking-mode providers (MiMo, DeepSeek-V4 thinking, etc.)
/// per their multi-turn API contract — see issue #42 + #40 + #41.
///
/// Lookup is exhaustive: we try every tool_call.id against the reasoning
/// store, not just the first one. Falls back to a short neutral
/// placeholder sentence (see `PLACEHOLDER`) when nothing is found so the
/// upstream API doesn't 400 — the model loses
/// some prior context but the conversation stays alive instead of dying
/// hard. Logs a warning when the placeholder fires so we can spot which
/// branches still leak.
fn ensure_reasoning_for_tool_calls(messages: &mut [Value], sessions: &SessionStore) {
    // Substantive (not whitespace) — MiMo specifically goes silent when
    // fed a single-space stub: the model treats it as "I had a thought
    // but it was empty," then declines to continue. A short neutral
    // sentence keeps the contract satisfied AND gives the model
    // something coherent to anchor against without leaking implementation
    // details into the user-visible context.
    const PLACEHOLDER: &str = "Continuing from previous tool call.";

    for msg in messages.iter_mut() {
        let is_assistant_with_tool_calls = msg.get("role").and_then(|v| v.as_str())
            == Some("assistant")
            && msg
                .get("tool_calls")
                .and_then(|v| v.as_array())
                .is_some_and(|a| !a.is_empty());
        if !is_assistant_with_tool_calls {
            continue;
        }

        // Already present and non-empty → leave alone.
        if let Some(existing) = msg.get("reasoning_content").and_then(|v| v.as_str()) {
            if !existing.is_empty() {
                continue;
            }
        }

        let tool_call_ids: Vec<String> = msg
            .get("tool_calls")
            .and_then(|v| v.as_array())
            .map(|tcs| {
                tcs.iter()
                    .filter_map(|tc| tc.get("id").and_then(|v| v.as_str()).map(String::from))
                    .collect()
            })
            .unwrap_or_default();

        let mut recovered: Option<String> = None;
        for id in &tool_call_ids {
            if let Some(r) = sessions.get_reasoning(id) {
                if !r.is_empty() {
                    recovered = Some(r);
                    break;
                }
            }
        }

        match recovered {
            Some(r) => {
                msg["reasoning_content"] = Value::String(r);
            }
            None => {
                log::warn!(
                    "[CodexProxy] reasoning_content missing for assistant tool_calls {:?}; \
                     injecting placeholder to satisfy thinking-model API contract",
                    tool_call_ids
                );
                msg["reasoning_content"] = Value::String(PLACEHOLDER.to_string());
            }
        }
    }
}

/// Empty-function-name guard (issue #206). A nameless `tool_calls` entry —
/// `function.name == ""` — is unusable: strict third-party providers
/// (Xiaomi MiMo, ...) reject the *entire* request with 400
/// "tool_calls[N] is missing a function name". The name goes missing when a
/// provider's streaming response never carried it (non-OpenAI-spec) and the
/// empty name got persisted into history, then replayed. We can't recover
/// the lost name, so we drop the orphaned call and its paired tool result —
/// the conversation degrades gracefully (loses one tool round-trip) rather
/// than dying hard on every subsequent turn.
fn strip_nameless_tool_calls(messages: &mut Vec<Value>) {
    // Pass 1: prune nameless entries from each assistant.tool_calls,
    // remembering the dropped ids so their results can be removed too.
    let mut dropped_ids: HashSet<String> = HashSet::new();
    for msg in messages.iter_mut() {
        if msg.get("role").and_then(|v| v.as_str()) != Some("assistant") {
            continue;
        }
        let Some(tcs) = msg.get("tool_calls").and_then(|v| v.as_array()) else {
            continue;
        };
        let total = tcs.len();
        let mut kept: Vec<Value> = Vec::with_capacity(total);
        for tc in tcs {
            let named = tc
                .get("function")
                .and_then(|f| f.get("name"))
                .and_then(|v| v.as_str())
                .map(|n| !n.trim().is_empty())
                .unwrap_or(false);
            if named {
                kept.push(tc.clone());
            } else if let Some(id) = tc.get("id").and_then(|v| v.as_str()) {
                dropped_ids.insert(id.to_string());
            }
        }
        if kept.len() == total {
            continue; // nothing dropped for this message
        }
        if kept.is_empty() {
            // No surviving calls: strip the field. A text prelude (if any)
            // is preserved; a contentless assistant is removed in pass 2.
            if let Some(obj) = msg.as_object_mut() {
                obj.remove("tool_calls");
            }
        } else {
            msg["tool_calls"] = Value::Array(kept);
        }
    }

    if dropped_ids.is_empty() {
        return;
    }
    log::warn!(
        "[CodexProxy] Dropped {} tool_call(s) with empty function name (plus paired results) — \
         upstream streaming likely omitted the tool name; see issue #206",
        dropped_ids.len()
    );

    // Pass 2: remove now-orphaned tool results, plus any assistant message
    // pass 1 emptied of both tool_calls and text content.
    messages.retain(|msg| match msg.get("role").and_then(|v| v.as_str()) {
        Some("tool") => msg
            .get("tool_call_id")
            .and_then(|v| v.as_str())
            .map(|id| !dropped_ids.contains(id))
            .unwrap_or(true),
        Some("assistant") if msg.get("tool_calls").is_none() => match msg.get("content") {
            Some(Value::String(s)) => !s.is_empty(),
            Some(Value::Array(a)) => !a.is_empty(),
            _ => false,
        },
        _ => true,
    });
}

// ── MiniMax legacy mode: merge system text into the first user message ──
// MiniMax mishandles standalone system roles; we bundle all consecutive
// system content into a "[System Instructions]\n..." prefix on the next
// user message.
fn minimax_merge(messages: Vec<Value>) -> Vec<Value> {
    let mut out: Vec<Value> = Vec::new();
    let mut pending_system = String::new();
    for mut msg in messages {
        let role = msg.get("role").and_then(|v| v.as_str()).unwrap_or("");
        if role == "system" {
            if let Some(s) = msg.get("content").and_then(|v| v.as_str()) {
                if !pending_system.is_empty() {
                    pending_system.push('\n');
                }
                pending_system.push_str(s);
                continue;
            }
        }
        if !pending_system.is_empty() {
            // If the next message is a string-content user, prefix in place.
            let is_string_user =
                role == "user" && msg.get("content").and_then(|v| v.as_str()).is_some();
            if is_string_user {
                let original = msg["content"].as_str().unwrap_or("").to_string();
                msg["content"] = Value::String(format!(
                    "[System Instructions]\n{pending_system}\n\n{original}"
                ));
            } else {
                out.push(json!({
                    "role": "user",
                    "content": format!("[System Instructions]\n{pending_system}"),
                }));
            }
            pending_system.clear();
        }
        out.push(msg);
    }
    if !pending_system.is_empty() {
        out.push(json!({
            "role": "user",
            "content": format!("[System Instructions]\n{pending_system}"),
        }));
    }
    if out.is_empty() {
        out.push(json!({ "role": "user", "content": "Hello" }));
    }
    out
}

// ── Coalesce consecutive same-role plain-text messages ──
// Never merges anything involving tool_calls or role=tool (those are
// structurally distinct slots in Chat Completions).
fn coalesce_consecutive(messages: Vec<Value>) -> Vec<Value> {
    let mut out: Vec<Value> = Vec::with_capacity(messages.len());
    for msg in messages {
        let can_merge = out.last().is_some_and(|last| {
            let last_role = last.get("role").and_then(|v| v.as_str());
            let cur_role = msg.get("role").and_then(|v| v.as_str());
            last_role == cur_role
                && last_role != Some("tool")
                && last.get("tool_calls").is_none()
                && msg.get("tool_calls").is_none()
                && last.get("content").and_then(|v| v.as_str()).is_some()
                && msg.get("content").and_then(|v| v.as_str()).is_some()
        });
        if can_merge {
            let last = out.last_mut().unwrap();
            let last_content = last["content"].as_str().unwrap_or("").to_string();
            let cur_content = msg["content"].as_str().unwrap_or("");
            last["content"] = Value::String(format!("{last_content}\n\n{cur_content}"));
        } else {
            out.push(msg);
        }
    }
    out
}

// ── Reorder: pull every tool message right after its matching assistant ──
// Two-phase: index tool messages by id, then walk skipping tools we'll
// emit alongside their assistant. Orphans on either side stay where
// they were (partial-history inputs / test fixtures rely on this).
fn reorder_tool_messages(messages: Vec<Value>) -> Vec<Value> {
    use std::collections::HashMap;

    let mut tool_by_call_id: HashMap<String, Value> = HashMap::new();
    for m in &messages {
        if m.get("role").and_then(|v| v.as_str()) == Some("tool") {
            if let Some(id) = m.get("tool_call_id").and_then(|v| v.as_str()) {
                tool_by_call_id
                    .entry(id.to_string())
                    .or_insert_with(|| m.clone());
            }
        }
    }

    let mut emitted: HashSet<String> = HashSet::new();
    let mut result: Vec<Value> = Vec::with_capacity(messages.len());
    for m in messages {
        if m.get("role").and_then(|v| v.as_str()) == Some("tool") {
            if let Some(id) = m.get("tool_call_id").and_then(|v| v.as_str()) {
                if emitted.contains(id) {
                    continue; // already pulled forward
                }
            }
        }
        let is_tool_call_assistant = m.get("role").and_then(|v| v.as_str()) == Some("assistant")
            && m.get("tool_calls")
                .and_then(|v| v.as_array())
                .is_some_and(|a| !a.is_empty());

        // Snapshot tool_call ids before moving the message into result.
        let pending_ids: Vec<String> = if is_tool_call_assistant {
            m.get("tool_calls")
                .and_then(|v| v.as_array())
                .map(|tcs| {
                    tcs.iter()
                        .filter_map(|tc| tc.get("id").and_then(|v| v.as_str()).map(String::from))
                        .collect()
                })
                .unwrap_or_default()
        } else {
            Vec::new()
        };

        result.push(m);

        for id in pending_ids {
            if !emitted.contains(&id) {
                if let Some(tool_msg) = tool_by_call_id.get(&id) {
                    result.push(tool_msg.clone());
                    emitted.insert(id);
                }
            }
        }
    }
    result
}

// ── Tool-definition normalizer ──
// Accepts both nested (`{type:"function", function:{...}}`) and flat
// (`{type:"function", name, description, parameters, strict}`) shapes
// and returns the nested Chat Completions form.
fn normalize_function_tool(tool: &Value) -> Value {
    let mut fn_val: Value = match tool.get("function") {
        Some(inner) if inner.is_object() => inner.clone(),
        _ => {
            let mut fn_obj = serde_json::Map::new();
            if let Some(name) = tool.get("name") {
                if !name.is_null() {
                    fn_obj.insert("name".to_string(), name.clone());
                }
            }
            if let Some(desc) = tool.get("description") {
                if !desc.is_null() {
                    fn_obj.insert("description".to_string(), desc.clone());
                }
            }
            if let Some(params) = tool.get("parameters") {
                if !params.is_null() {
                    fn_obj.insert("parameters".to_string(), params.clone());
                }
            }
            if let Some(strict) = tool.get("strict") {
                if !strict.is_null() {
                    fn_obj.insert("strict".to_string(), strict.clone());
                }
            }
            Value::Object(fn_obj)
        }
    };

    // Backfill `required: []` on object schemas that omit it. Strict
    // OpenAI-compatible gateways (vLLM, some enterprise relays) reject a
    // function whose object schema lacks `required` with a 400
    // (`null is not of type "array"`) — Codex's built-ins with all-optional
    // params (list_mcp_resources, read_thread_terminal, ...) ship exactly that
    // shape. Apply only to NON-strict tools: strict mode already mandates every
    // property appear in `required`, so we must not fabricate an empty one
    // there. (cc-switch / Cmochance #417.)
    let is_strict = fn_val
        .get("strict")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    if !is_strict {
        if let Some(params) = fn_val.get_mut("parameters") {
            ensure_object_schema_required(params);
        }
    }

    json!({ "type": "function", "function": fn_val })
}

/// Recursively ensure every JSON-Schema *object* node carries a `required`
/// array. A node counts as an object schema when `type == "object"` or it has
/// a `properties` map. Recurses through `properties`, `items`,
/// `additionalProperties`, `$defs`/`definitions`, and `anyOf`/`oneOf`/`allOf`
/// so nested parameter objects are covered too. Mutates in place; only ever
/// ADDS an empty `required` where absent — never rewrites an existing one, and
/// never touches a non-object schema (a bare `{}` "any" schema is left alone).
fn ensure_object_schema_required(schema: &mut Value) {
    let Some(obj) = schema.as_object_mut() else {
        return;
    };
    let is_object_schema = obj.get("type").and_then(|v| v.as_str()) == Some("object")
        || obj.contains_key("properties");
    if is_object_schema && !obj.contains_key("required") {
        obj.insert("required".to_string(), Value::Array(Vec::new()));
    }
    if let Some(props) = obj.get_mut("properties").and_then(|v| v.as_object_mut()) {
        for v in props.values_mut() {
            ensure_object_schema_required(v);
        }
    }
    for key in ["items", "additionalProperties"] {
        if let Some(v) = obj.get_mut(key) {
            ensure_object_schema_required(v);
        }
    }
    for key in ["$defs", "definitions"] {
        if let Some(defs) = obj.get_mut(key).and_then(|v| v.as_object_mut()) {
            for v in defs.values_mut() {
                ensure_object_schema_required(v);
            }
        }
    }
    for key in ["anyOf", "oneOf", "allOf"] {
        if let Some(arr) = obj.get_mut(key).and_then(|v| v.as_array_mut()) {
            for v in arr.iter_mut() {
                ensure_object_schema_required(v);
            }
        }
    }
}

/// Qualify a flattened namespace tool's function name with its namespace so it
/// matches Codex's own `mcp__<server>__<tool>` convention (join_tool_name +
/// ensure_mcp_prefix in Codex's `core/src/tools/handlers/mcp.rs`, delimiter
/// `__`). Codex's dispatcher resolves a returned function_call by that exact
/// fully-qualified name, so qualifying on the request side needs NO reverse
/// map on the response side. Idempotent: an inner name that already starts
/// with `mcp__` (defensive — inner names are bare on the wire today) or an
/// empty namespace is left untouched.
fn qualify_namespaced_tool_name(fn_tool: &mut Value, namespace: &str) {
    let Some(func) = fn_tool.get_mut("function").and_then(|v| v.as_object_mut()) else {
        return;
    };
    // Own the child name so the immutable borrow ends before we re-insert.
    let child = match func.get("name").and_then(|v| v.as_str()) {
        Some(c) => c.to_string(),
        None => return,
    };
    if child.is_empty() || child.starts_with("mcp__") || namespace.is_empty() {
        return;
    }
    let base = format!("{}__{}", namespace.trim_end_matches('_'), child);
    let qualified = if base.starts_with("mcp__") {
        base
    } else {
        format!("mcp__{base}")
    };
    func.insert("name".to_string(), Value::String(qualified));
}

// ────────────────────────────────────────────────────────────────────
// Tests — direct port of the most load-bearing cases from the
// original responses-to-chat suite, plus session-store-backed cases
// (history replay, reasoning round-trip).
// ────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn store() -> SessionStore {
        SessionStore::new()
    }

    #[test]
    fn pure_string_input_becomes_one_user_message() {
        let body = json!({
            "model": "deepseek-chat",
            "input": "hello",
        });
        let out = responses_to_chat(&body, &store());
        assert_eq!(out["messages"][0]["role"], "user");
        assert_eq!(out["messages"][0]["content"], "hello");
        assert_eq!(out["model"], "deepseek-chat");
        assert_eq!(out["stream"], true);
    }

    #[test]
    fn streaming_request_injects_include_usage() {
        // Streaming (the default) must carry stream_options.include_usage so
        // OpenAI-compat upstreams emit the trailing usage chunk; otherwise
        // Codex sees zero tokens and its context tracking drifts.
        let body = json!({ "model": "deepseek-chat", "input": "hi", "stream": true });
        let out = responses_to_chat(&body, &store());
        assert_eq!(out["stream"], true);
        assert_eq!(out["stream_options"]["include_usage"], true);
    }

    #[test]
    fn non_streaming_request_omits_stream_options() {
        // Non-streaming responses return usage inline; no stream_options needed.
        let body = json!({ "model": "deepseek-chat", "input": "hi", "stream": false });
        let out = responses_to_chat(&body, &store());
        assert_eq!(out["stream"], false);
        assert!(out.get("stream_options").is_none());
    }

    #[test]
    fn include_usage_merges_into_existing_stream_options() {
        // A future client that already sends stream_options keeps its fields;
        // we only add include_usage. Codex doesn't today, but don't clobber.
        let body = json!({
            "model": "deepseek-chat",
            "input": "hi",
            "stream": true,
            "stream_options": { "continuous_usage_stats": true },
        });
        let out = responses_to_chat(&body, &store());
        assert_eq!(out["stream_options"]["include_usage"], true);
        assert_eq!(out["stream_options"]["continuous_usage_stats"], true);
    }

    #[test]
    fn instructions_become_leading_system_message() {
        let body = json!({
            "model": "deepseek-chat",
            "instructions": "you are helpful",
            "input": "hi",
        });
        let out = responses_to_chat(&body, &store());
        assert_eq!(out["messages"][0]["role"], "system");
        assert_eq!(out["messages"][0]["content"], "you are helpful");
        assert_eq!(out["messages"][1]["role"], "user");
    }

    #[test]
    fn consecutive_function_calls_group_into_one_assistant() {
        let body = json!({
            "model": "deepseek-chat",
            "input": [
                { "type": "function_call", "call_id": "c1", "name": "a", "arguments": "{}" },
                { "type": "function_call", "call_id": "c2", "name": "b", "arguments": "{}" },
            ],
        });
        let out = responses_to_chat(&body, &store());
        let msgs = out["messages"].as_array().unwrap();
        // One assistant message groups both tool_calls; the orphan-tool
        // backstop then appends two placeholder tool messages because no
        // function_call_output was sent — see ensure_tool_outputs_paired.
        assert_eq!(msgs.len(), 3);
        assert_eq!(msgs[0]["role"], "assistant");
        assert_eq!(msgs[0]["tool_calls"].as_array().unwrap().len(), 2);
        assert_eq!(msgs[0]["tool_calls"][0]["id"], "c1");
        assert_eq!(msgs[0]["tool_calls"][1]["id"], "c2");
        assert_eq!(msgs[1]["role"], "tool");
        assert_eq!(msgs[2]["role"], "tool");
    }

    #[test]
    fn function_call_output_becomes_tool_message() {
        let body = json!({
            "model": "deepseek-chat",
            "input": [
                { "type": "function_call_output", "call_id": "c1", "output": "result" },
            ],
        });
        let out = responses_to_chat(&body, &store());
        let msgs = out["messages"].as_array().unwrap();
        assert_eq!(msgs.len(), 1);
        assert_eq!(msgs[0]["role"], "tool");
        assert_eq!(msgs[0]["tool_call_id"], "c1");
        assert_eq!(msgs[0]["content"], "result");
    }

    #[test]
    fn local_shell_call_becomes_assistant_tool_call() {
        let body = json!({
            "model": "deepseek-chat",
            "input": [
                { "type": "local_shell_call", "call_id": "c1", "action": { "cmd": "ls" } },
            ],
        });
        let out = responses_to_chat(&body, &store());
        let msgs = out["messages"].as_array().unwrap();
        assert_eq!(msgs[0]["role"], "assistant");
        let tcs = msgs[0]["tool_calls"].as_array().unwrap();
        assert_eq!(tcs[0]["function"]["name"], "local_shell");
        assert_eq!(tcs[0]["function"]["arguments"], "{\"cmd\":\"ls\"}");
    }

    #[test]
    fn interleaved_developer_msg_gets_pulled_past_tool() {
        // The exact misordering that caused issue #38's
        // "insufficient tool messages following tool_calls" error.
        let body = json!({
            "model": "deepseek-chat",
            "input": [
                { "type": "function_call", "call_id": "c1", "name": "sh", "arguments": "{}" },
                { "type": "message", "role": "developer", "content": "side note" },
                { "type": "function_call_output", "call_id": "c1", "output": "ok" },
            ],
        });
        let out = responses_to_chat(&body, &store());
        let roles: Vec<&str> = out["messages"]
            .as_array()
            .unwrap()
            .iter()
            .map(|m| m.get("role").and_then(|v| v.as_str()).unwrap_or(""))
            .collect();
        assert_eq!(roles, vec!["assistant", "tool", "system"]);
    }

    #[test]
    fn generic_custom_tool_call_emits_assistant_tool_calls() {
        let body = json!({
            "model": "deepseek-chat",
            "input": [
                { "type": "custom_tool_call", "call_id": "c1", "name": "browser", "input": "click(1)" },
            ],
        });
        let out = responses_to_chat(&body, &store());
        let tcs = out["messages"][0]["tool_calls"].as_array().unwrap();
        assert_eq!(tcs[0]["function"]["name"], "browser");
        assert_eq!(tcs[0]["function"]["arguments"], "click(1)");
    }

    #[test]
    fn compaction_with_plain_summary_uses_it_verbatim() {
        // Our /v1/responses/compact handler writes the upstream-generated
        // summary into encrypted_content. process_input_items should
        // surface that as a system message body so the model sees the
        // real summary, not a generic placeholder.
        let body = json!({
            "model": "deepseek-chat",
            "input": [
                {
                    "type": "compaction",
                    "encrypted_content": "User asked about Rust borrow checker. We discussed lifetimes and pointed at the Nomicon."
                },
            ],
        });
        let out = responses_to_chat(&body, &store());
        assert_eq!(out["messages"][0]["role"], "system");
        let content = out["messages"][0]["content"].as_str().unwrap();
        assert!(content.contains("Summary of earlier conversation"));
        assert!(content.contains("Rust borrow checker"));
    }

    #[test]
    fn compaction_with_empty_encrypted_content_falls_back_to_placeholder() {
        let body = json!({
            "model": "deepseek-chat",
            "input": [
                { "type": "compaction", "encrypted_content": "" },
            ],
        });
        let out = responses_to_chat(&body, &store());
        let content = out["messages"][0]["content"].as_str().unwrap();
        assert!(content.contains("compacted"));
    }

    #[test]
    fn compaction_with_openai_opaque_blob_falls_back_to_placeholder() {
        // A real OpenAI encrypted blob shouldn't be surfaced as if it
        // were a readable summary. The "gAAAAA" prefix is fernet-style
        // base64 prefix that any encrypted blob will start with.
        let body = json!({
            "model": "deepseek-chat",
            "input": [
                {
                    "type": "compaction",
                    "encrypted_content": "gAAAAABabcdef1234567890opaqueblob..."
                },
            ],
        });
        let out = responses_to_chat(&body, &store());
        let content = out["messages"][0]["content"].as_str().unwrap();
        assert!(content.contains("compacted"));
        assert!(!content.contains("gAAAAA"));
    }

    #[test]
    fn compaction_trigger_sentinel_is_dropped() {
        // remote-compaction-v2 appends a bare `compaction_trigger` item. It
        // carries no content and must leave no message behind — turning it
        // into one would pollute the summarization input.
        let body = json!({
            "model": "deepseek-chat",
            "input": [
                { "type": "message", "role": "user", "content": "real work happened here" },
                { "type": "compaction_trigger" },
            ],
        });
        let out = responses_to_chat(&body, &store());
        let serialized = serde_json::to_string(&out).unwrap();
        // The sentinel produced nothing...
        assert!(!serialized.contains("compaction_trigger"));
        // ...and the real user turn survived.
        assert!(serialized.contains("real work happened here"));
    }

    #[test]
    fn developer_role_collapses_to_system() {
        let body = json!({
            "model": "deepseek-chat",
            "input": [
                { "type": "message", "role": "developer", "content": "note" },
            ],
        });
        let out = responses_to_chat(&body, &store());
        assert_eq!(out["messages"][0]["role"], "system");
        assert_eq!(out["messages"][0]["content"], "note");
    }

    #[test]
    fn tools_filter_drops_non_function_types() {
        let body = json!({
            "model": "deepseek-chat",
            "input": "hi",
            "tools": [
                { "type": "function", "name": "foo", "description": "f", "parameters": {} },
                { "type": "web_search" },
                { "type": "local_shell" },
            ],
        });
        let out = responses_to_chat(&body, &store());
        let tools = out["tools"].as_array().unwrap();
        assert_eq!(tools.len(), 1);
        assert_eq!(tools[0]["function"]["name"], "foo");
    }

    #[test]
    fn mimo_web_search_tool_is_passed_through() {
        // MiMo's Chat API natively accepts {type:"web_search"} (server-side
        // auto search). For mimo-* models we pass it through instead of
        // dropping it, alongside any real function tools — AND set the
        // top-level `webSearchEnabled: true` flag MiMo requires (the tool
        // alone 400s "...webSearchEnabled is false").
        let body = json!({
            "model": "mimo-v2.5-pro",
            "input": "hi",
            "tools": [
                { "type": "function", "name": "foo", "description": "f", "parameters": {} },
                { "type": "web_search", "filters": { "anything": true } },
            ],
        });
        let out = responses_to_chat(&body, &store());
        let tools = out["tools"].as_array().unwrap();
        assert_eq!(tools.len(), 2);
        assert!(tools.iter().any(|t| t["function"]["name"] == "foo"));
        let ws = tools
            .iter()
            .find(|t| t["type"] == "web_search")
            .expect("web_search passed through for mimo");
        // Codex's OpenAI-specific fields are stripped to a bare type.
        assert_eq!(ws.get("filters"), None);
        // MiMo requires the enable flag in the request body alongside the tool.
        assert_eq!(out["webSearchEnabled"], true);
    }

    #[test]
    fn web_search_tool_still_dropped_for_non_native_provider() {
        // A bare {type:"web_search"} 400s a generic Chat upstream, so only
        // known-supporting providers pass it through; the default is drop.
        let body = json!({
            "model": "deepseek-chat",
            "input": "hi",
            "tools": [ { "type": "web_search" } ],
        });
        let out = responses_to_chat(&body, &store());
        assert!(out.get("tools").is_none());
    }

    #[test]
    fn glm_web_search_dropped_function_tools_kept() {
        // GLM-5.2's Chat Completions endpoint rejects any tools[] entry lacking
        // a `function` key, so GLM's non-function web_search tool can't ride
        // alongside Codex's function tools — it 400s the whole request
        // ("missing tools.function parameter"). We drop web_search and keep the
        // function tools, each wrapped as {type:function, function:{...}}.
        let body = json!({
            "model": "glm-4.6",
            "input": "hi",
            "tools": [
                { "type": "function", "name": "shell", "parameters": { "type": "object", "properties": {} } },
                { "type": "web_search" },
            ],
        });
        let out = responses_to_chat(&body, &store());
        let tools = out["tools"].as_array().unwrap();
        assert_eq!(tools.len(), 1, "web_search dropped, function kept");
        assert_eq!(tools[0]["type"], "function");
        assert_eq!(tools[0]["function"]["name"], "shell");
        assert!(
            tools.iter().all(|t| t.get("function").is_some()),
            "every GLM tool must carry a function key"
        );
    }

    #[test]
    fn qwen_web_search_becomes_enable_search_request_param() {
        // Qwen enables search via a top-level request param, not a tool. The
        // web_search tool is consumed into chat_body.enable_search and not
        // forwarded in the tools array.
        let body = json!({
            "model": "qwen3-max",
            "input": "hi",
            "tools": [ { "type": "web_search" } ],
        });
        let out = responses_to_chat(&body, &store());
        assert_eq!(out["enable_search"], true);
        assert!(out.get("tools").is_none());
    }

    #[test]
    fn minimax_merges_system_into_user() {
        let body = json!({
            "model": "minimax-chat",
            "input": [
                { "type": "message", "role": "developer", "content": "system note" },
                { "type": "message", "role": "user", "content": "hello" },
            ],
        });
        let out = responses_to_chat(&body, &store());
        let msgs = out["messages"].as_array().unwrap();
        assert_eq!(msgs[0]["role"], "user");
        let c = msgs[0]["content"].as_str().unwrap();
        assert!(c.contains("[System Instructions]"));
        assert!(c.contains("system note"));
        assert!(c.contains("hello"));
    }

    #[test]
    fn coalesce_merges_consecutive_user_strings() {
        let body = json!({
            "model": "deepseek-chat",
            "input": [
                { "type": "message", "role": "user", "content": "one" },
                { "type": "message", "role": "user", "content": "two" },
            ],
        });
        let out = responses_to_chat(&body, &store());
        let msgs = out["messages"].as_array().unwrap();
        assert_eq!(msgs.len(), 1);
        assert_eq!(msgs[0]["content"], "one\n\ntwo");
    }

    #[test]
    fn normalize_function_tool_handles_flat_shape() {
        let flat = json!({
            "type": "function",
            "name": "foo",
            "description": "d",
            "parameters": { "type": "object" },
        });
        let out = normalize_function_tool(&flat);
        assert_eq!(out["type"], "function");
        assert_eq!(out["function"]["name"], "foo");
        assert_eq!(out["function"]["description"], "d");
    }

    #[test]
    fn function_tool_object_schema_gets_required_backfilled() {
        // Object schema with no `required` → strict gateways 400; we backfill [].
        let body = json!({
            "model": "deepseek-chat",
            "input": "hi",
            "tools": [{
                "type": "function",
                "name": "f",
                "parameters": { "type": "object", "properties": { "x": { "type": "string" } } },
            }],
        });
        let out = responses_to_chat(&body, &store());
        assert_eq!(
            out["tools"][0]["function"]["parameters"]["required"],
            json!([])
        );
    }

    #[test]
    fn strict_function_tool_required_not_fabricated() {
        // strict mode mandates every property in `required`; we must NOT
        // fabricate an empty one (it would silently break strict validation).
        let body = json!({
            "model": "deepseek-chat",
            "input": "hi",
            "tools": [{
                "type": "function",
                "name": "f",
                "strict": true,
                "parameters": { "type": "object", "properties": {} },
            }],
        });
        let out = responses_to_chat(&body, &store());
        assert!(out["tools"][0]["function"]["parameters"]
            .get("required")
            .is_none());
    }

    #[test]
    fn nested_object_schema_gets_required_backfilled() {
        let body = json!({
            "model": "deepseek-chat",
            "input": "hi",
            "tools": [{
                "type": "function",
                "name": "f",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "nested": { "type": "object", "properties": { "y": { "type": "number" } } }
                    },
                    "required": ["nested"],
                },
            }],
        });
        let out = responses_to_chat(&body, &store());
        let params = &out["tools"][0]["function"]["parameters"];
        // existing top-level `required` preserved verbatim
        assert_eq!(params["required"], json!(["nested"]));
        // nested object that omitted `required` gets an empty one
        assert_eq!(params["properties"]["nested"]["required"], json!([]));
    }

    #[test]
    fn empty_any_schema_not_given_required() {
        // `{}` is an "any" schema, not an object schema → leave it untouched.
        let body = json!({
            "model": "deepseek-chat",
            "input": "hi",
            "tools": [{ "type": "function", "name": "f", "parameters": {} }],
        });
        let out = responses_to_chat(&body, &store());
        assert!(out["tools"][0]["function"]["parameters"]
            .get("required")
            .is_none());
    }

    #[test]
    fn namespace_tool_name_qualified_with_mcp_prefix() {
        // Codex sends MCP tools as a namespace of bare-named functions; we
        // flatten AND qualify to `mcp__<server>__<tool>` so they route back.
        let body = json!({
            "model": "deepseek-chat",
            "input": "hi",
            "tools": [{
                "type": "namespace",
                "name": "mcp__memory",
                "description": "memory tools",
                "tools": [
                    { "type": "function", "name": "create_entities", "parameters": { "type": "object" } },
                    { "type": "function", "name": "search", "parameters": { "type": "object" } },
                ],
            }],
        });
        let out = responses_to_chat(&body, &store());
        let tools = out["tools"].as_array().unwrap();
        assert_eq!(tools.len(), 2);
        assert_eq!(tools[0]["function"]["name"], "mcp__memory__create_entities");
        assert_eq!(tools[1]["function"]["name"], "mcp__memory__search");
    }

    #[test]
    fn namespace_without_mcp_prefix_gets_one() {
        // Built-in namespaces not already prefixed get `mcp__` prepended
        // (matches Codex's ensure_mcp_prefix).
        let body = json!({
            "model": "deepseek-chat",
            "input": "hi",
            "tools": [{
                "type": "namespace",
                "name": "memory",
                "tools": [{ "type": "function", "name": "recall" }],
            }],
        });
        let out = responses_to_chat(&body, &store());
        assert_eq!(out["tools"][0]["function"]["name"], "mcp__memory__recall");
    }

    #[test]
    fn namespace_dedup_across_two_namespaces() {
        // Same bare tool name in two namespaces must NOT collide once qualified.
        let body = json!({
            "model": "deepseek-chat",
            "input": "hi",
            "tools": [
                { "type": "namespace", "name": "mcp__a", "tools": [{ "type": "function", "name": "run" }] },
                { "type": "namespace", "name": "mcp__b", "tools": [{ "type": "function", "name": "run" }] },
            ],
        });
        let out = responses_to_chat(&body, &store());
        let tools = out["tools"].as_array().unwrap();
        assert_eq!(tools[0]["function"]["name"], "mcp__a__run");
        assert_eq!(tools[1]["function"]["name"], "mcp__b__run");
    }

    #[test]
    fn unknown_item_type_is_skipped() {
        let body = json!({
            "model": "deepseek-chat",
            "input": [
                { "type": "totally_made_up", "junk": 1 },
                { "type": "message", "role": "user", "content": "real" },
            ],
        });
        let out = responses_to_chat(&body, &store());
        let msgs = out["messages"].as_array().unwrap();
        assert_eq!(msgs.len(), 1);
        assert_eq!(msgs[0]["content"], "real");
    }

    // ── reasoning_content defensive injection (issues #40 / #41 / #42) ──

    #[test]
    fn reasoning_recovered_from_session_store_by_first_call_id() {
        // History replay path: prior turn's assistant came back through
        // previous_response_id but lost reasoning_content. The store still
        // has it under the tool-call id — last-mile guard recovers it.
        let s = store();
        s.store_reasoning("call_abc", "deep thought");
        s.save_history(
            "resp_prev",
            vec![
                json!({ "role": "user", "content": "go" }),
                json!({
                    "role": "assistant",
                    "content": null,
                    "tool_calls": [{
                        "id": "call_abc",
                        "type": "function",
                        "function": { "name": "shell", "arguments": "{}" },
                    }],
                    // NB: reasoning_content omitted to simulate the leak.
                }),
            ],
        );
        let body = json!({
            "model": "deepseek-v4-flash",
            "previous_response_id": "resp_prev",
            "input": [
                { "type": "function_call_output", "call_id": "call_abc", "output": "/home" },
            ],
        });
        let out = responses_to_chat(&body, &s);
        let msgs = out["messages"].as_array().unwrap();
        let assistant = msgs.iter().find(|m| m["role"] == "assistant").unwrap();
        assert_eq!(assistant["reasoning_content"], "deep thought");
    }

    #[test]
    fn reasoning_recovered_from_any_tool_call_id_not_just_first() {
        // First id missing, second id has stored reasoning — should still recover.
        let s = store();
        s.store_reasoning("call_b", "second-id reasoning");
        s.save_history(
            "resp_x",
            vec![json!({
                "role": "assistant",
                "content": null,
                "tool_calls": [
                    { "id": "call_a", "type": "function", "function": { "name": "f1", "arguments": "{}" } },
                    { "id": "call_b", "type": "function", "function": { "name": "f2", "arguments": "{}" } },
                ],
            })],
        );
        let body = json!({
            "model": "mimo-v2.5-pro",
            "previous_response_id": "resp_x",
            "input": [],
        });
        let out = responses_to_chat(&body, &s);
        let assistant = out["messages"]
            .as_array()
            .unwrap()
            .iter()
            .find(|m| m["role"] == "assistant")
            .unwrap();
        assert_eq!(assistant["reasoning_content"], "second-id reasoning");
    }

    #[test]
    fn reasoning_placeholder_when_store_has_nothing() {
        // Worst case: history replay lost reasoning_content AND store
        // has nothing under any tool-call id. We inject a placeholder so
        // the thinking-mode API contract is satisfied — the conversation
        // continues even when our state tracking has a hole.
        let s = store();
        s.save_history(
            "resp_orphan",
            vec![json!({
                "role": "assistant",
                "content": null,
                "tool_calls": [{
                    "id": "call_lost",
                    "type": "function",
                    "function": { "name": "shell", "arguments": "{}" },
                }],
            })],
        );
        let body = json!({
            "model": "mimo-v2.5-pro",
            "previous_response_id": "resp_orphan",
            "input": [],
        });
        let out = responses_to_chat(&body, &s);
        let assistant = out["messages"]
            .as_array()
            .unwrap()
            .iter()
            .find(|m| m["role"] == "assistant")
            .unwrap();
        // Must be a non-empty string (thinking-mode providers reject
        // missing-or-empty reasoning_content).
        let r = assistant["reasoning_content"].as_str().unwrap();
        assert!(!r.is_empty());
    }

    #[test]
    fn reasoning_injection_skips_plain_assistant_messages() {
        // Assistant turns without tool_calls don't need reasoning_content.
        // Injecting one would pollute non-thinking conversations.
        let body = json!({
            "model": "gpt-4o",
            "input": [
                { "type": "message", "role": "assistant", "content": "hi there" },
            ],
        });
        let out = responses_to_chat(&body, &store());
        let assistant = &out["messages"].as_array().unwrap()[0];
        assert_eq!(assistant["role"], "assistant");
        assert!(
            assistant.get("reasoning_content").is_none(),
            "should not inject reasoning_content on plain assistant"
        );
    }

    // ── orphan tool-call backstop ──

    #[test]
    fn orphan_tool_call_gets_placeholder_tool_message() {
        // Codex sent function_call without matching function_call_output
        // (e.g. user interrupted mid-execution).
        let body = json!({
            "model": "deepseek-chat",
            "input": [
                { "type": "message", "role": "user", "content": "ls /tmp" },
                { "type": "function_call", "call_id": "orphan_1", "name": "shell", "arguments": "{}" },
                // NB: no function_call_output for orphan_1
            ],
        });
        let out = responses_to_chat(&body, &store());
        let msgs = out["messages"].as_array().unwrap();
        // user, assistant{tool_calls}, tool{placeholder}
        assert_eq!(msgs.len(), 3);
        assert_eq!(msgs[2]["role"], "tool");
        assert_eq!(msgs[2]["tool_call_id"], "orphan_1");
        assert!(msgs[2]["content"].as_str().unwrap().contains("no result"));
    }

    #[test]
    fn matched_tool_calls_get_no_placeholder() {
        // Healthy pair — no synthesis should happen.
        let body = json!({
            "model": "deepseek-chat",
            "input": [
                { "type": "function_call", "call_id": "ok_1", "name": "shell", "arguments": "{}" },
                { "type": "function_call_output", "call_id": "ok_1", "output": "result" },
            ],
        });
        let out = responses_to_chat(&body, &store());
        let msgs = out["messages"].as_array().unwrap();
        assert_eq!(msgs.len(), 2);
        assert_eq!(msgs[1]["content"], "result");
        // Not the placeholder text
        assert!(!msgs[1]["content"].as_str().unwrap().contains("no result"));
    }

    #[test]
    fn partial_orphan_among_grouped_tool_calls_gets_only_missing_placeholder() {
        // Three tool_calls grouped into one assistant, only two have outputs.
        let body = json!({
            "model": "deepseek-chat",
            "input": [
                { "type": "function_call", "call_id": "c1", "name": "a", "arguments": "{}" },
                { "type": "function_call", "call_id": "c2", "name": "b", "arguments": "{}" },
                { "type": "function_call", "call_id": "c3", "name": "c", "arguments": "{}" },
                { "type": "function_call_output", "call_id": "c1", "output": "r1" },
                { "type": "function_call_output", "call_id": "c3", "output": "r3" },
                // c2 orphaned
            ],
        });
        let out = responses_to_chat(&body, &store());
        let msgs = out["messages"].as_array().unwrap();
        // assistant, tool(c1), tool(c3), placeholder(c2) — order is the
        // assistant's tool_calls order. Placeholder lands after the
        // assistant message before next non-tool segment.
        let tool_ids: Vec<&str> = msgs
            .iter()
            .filter(|m| m["role"] == "tool")
            .map(|m| m["tool_call_id"].as_str().unwrap())
            .collect();
        assert_eq!(tool_ids.len(), 3);
        assert!(tool_ids.contains(&"c1"));
        assert!(tool_ids.contains(&"c2"));
        assert!(tool_ids.contains(&"c3"));
    }

    #[test]
    fn orphan_backstop_skips_when_other_position_already_satisfies() {
        // Tool message exists somewhere in the request — even if not
        // immediately adjacent — so we should not synthesize.
        // (reorder_tool_messages pulls it adjacent anyway; this asserts
        // we never *over*-synthesize.)
        let body = json!({
            "model": "deepseek-chat",
            "input": [
                { "type": "function_call", "call_id": "c1", "name": "a", "arguments": "{}" },
                { "type": "message", "role": "developer", "content": "side note" },
                { "type": "function_call_output", "call_id": "c1", "output": "ok" },
            ],
        });
        let out = responses_to_chat(&body, &store());
        let placeholder_count = out["messages"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|m| {
                m["role"] == "tool"
                    && m["content"]
                        .as_str()
                        .map(|s| s.contains("no result"))
                        .unwrap_or(false)
            })
            .count();
        assert_eq!(placeholder_count, 0);
    }

    #[test]
    fn reasoning_already_present_is_preserved() {
        // If history replay already carries reasoning_content, we must
        // not clobber it with a placeholder.
        let s = store();
        s.save_history(
            "resp_with",
            vec![json!({
                "role": "assistant",
                "content": null,
                "tool_calls": [{ "id": "call_z", "type": "function", "function": { "name": "f", "arguments": "{}" } }],
                "reasoning_content": "original detailed reasoning",
            })],
        );
        let body = json!({
            "model": "mimo-v2.5-pro",
            "previous_response_id": "resp_with",
            "input": [],
        });
        let out = responses_to_chat(&body, &s);
        let assistant = out["messages"]
            .as_array()
            .unwrap()
            .iter()
            .find(|m| m["role"] == "assistant")
            .unwrap();
        assert_eq!(
            assistant["reasoning_content"],
            "original detailed reasoning"
        );
    }

    // ── H5: reasoning.effort pass-through ──
    #[test]
    fn reasoning_effort_passes_through_as_reasoning_effort() {
        let body = json!({
            "model": "gpt-5",
            "input": "hi",
            "reasoning": { "effort": "high", "summary": "auto" },
        });
        let out = responses_to_chat(&body, &store());
        assert_eq!(out["reasoning_effort"], "high");
        // summary is intentionally NOT passed through — we synthesize
        // summary events ourselves in stream_handler.
        assert!(out.get("summary").is_none());
    }

    #[test]
    fn reasoning_effort_xhigh_clamps_to_high_for_legacy_upstreams() {
        // Codex CLI's "extreme reasoning" tier sends `xhigh`, but MiMo /
        // DeepSeek / most non-OpenAI providers reject anything outside
        // {low, medium, high} with a 400 literal_error. We clamp to
        // high so the request reaches upstream at all.
        let body = json!({
            "model": "mimo-v2.5-pro",
            "input": "think hard",
            "reasoning": { "effort": "xhigh" },
        });
        let out = responses_to_chat(&body, &store());
        assert_eq!(out["reasoning_effort"], "high");
    }

    #[test]
    fn reasoning_effort_minimal_clamps_to_low_for_legacy_upstreams() {
        // Symmetric clamp for OpenAI's new sub-low tier.
        let body = json!({
            "model": "mimo-v2.5-pro",
            "input": "quick reply",
            "reasoning": { "effort": "minimal" },
        });
        let out = responses_to_chat(&body, &store());
        assert_eq!(out["reasoning_effort"], "low");
    }

    #[test]
    fn reasoning_effort_unknown_value_passes_through_unchanged() {
        // Future upstream tiers we haven't mapped yet should NOT be
        // silently rewritten to medium — pass them through so the
        // upstream's own validator can decide.
        let body = json!({
            "model": "gpt-5",
            "input": "hi",
            "reasoning": { "effort": "speculative_tier_42" },
        });
        let out = responses_to_chat(&body, &store());
        assert_eq!(out["reasoning_effort"], "speculative_tier_42");
    }

    // ── H6: text.format → response_format ──
    #[test]
    fn text_format_json_schema_passes_through_repackaged() {
        // OpenAI Chat has natively accepted `response_format.type=json_schema`
        // since 2024-08; passing it through is strictly better than
        // dropping (third parties that don't support it 400 with a
        // clear message, vs. silently producing free-form text the
        // user expected to be structured).
        //
        // The repackaging hoists `{name, schema, strict}` from
        // Responses' flat `text.format` into Chat's nested
        // `response_format.json_schema` envelope.
        let body = json!({
            "model": "gpt-5",
            "input": "give me JSON",
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "weather",
                    "strict": true,
                    "schema": { "type": "object" },
                }
            },
        });
        let out = responses_to_chat(&body, &store());
        assert_eq!(out["response_format"]["type"], "json_schema");
        assert_eq!(out["response_format"]["json_schema"]["name"], "weather");
        assert_eq!(out["response_format"]["json_schema"]["strict"], true);
        assert_eq!(
            out["response_format"]["json_schema"]["schema"]["type"],
            "object"
        );
    }

    #[test]
    fn text_format_json_schema_minimal_only_schema_field() {
        // Some Responses requests omit name/strict and only carry schema.
        // The repackaging must not synthesize missing fields — let the
        // upstream tell us if it needs them.
        let body = json!({
            "model": "gpt-5",
            "input": "x",
            "text": {
                "format": {
                    "type": "json_schema",
                    "schema": { "type": "string" },
                }
            },
        });
        let out = responses_to_chat(&body, &store());
        assert_eq!(out["response_format"]["type"], "json_schema");
        assert_eq!(
            out["response_format"]["json_schema"]["schema"]["type"],
            "string"
        );
        assert!(out["response_format"]["json_schema"].get("name").is_none());
        assert!(out["response_format"]["json_schema"]
            .get("strict")
            .is_none());
    }

    #[test]
    fn text_format_json_object_maps_to_response_format() {
        let body = json!({
            "model": "gpt-5",
            "input": "hi",
            "text": { "format": { "type": "json_object" } },
        });
        let out = responses_to_chat(&body, &store());
        assert_eq!(out["response_format"]["type"], "json_object");
    }

    #[test]
    fn text_format_text_type_maps_to_response_format() {
        // The `text` variant is widely supported (and basically a
        // no-op for most upstreams) — keep it.
        let body = json!({
            "model": "gpt-5",
            "input": "hi",
            "text": { "format": { "type": "text" } },
        });
        let out = responses_to_chat(&body, &store());
        assert_eq!(out["response_format"]["type"], "text");
    }

    // ── H7: parallel_tool_calls + M10: misc pass-through ──
    #[test]
    fn parallel_tool_calls_and_misc_fields_pass_through() {
        let body = json!({
            "model": "gpt-5",
            "input": "hi",
            "parallel_tool_calls": false,
            "top_p": 0.9,
            "frequency_penalty": 0.5,
            "presence_penalty": 0.3,
            "seed": 42,
            "user": "u-1",
            "prompt_cache_key": "ck-1",
            "service_tier": "flex",
            "metadata": { "k": "v" },
        });
        let out = responses_to_chat(&body, &store());
        assert_eq!(out["parallel_tool_calls"], false);
        assert_eq!(out["top_p"], 0.9);
        assert_eq!(out["frequency_penalty"], 0.5);
        assert_eq!(out["presence_penalty"], 0.3);
        assert_eq!(out["seed"], 42);
        assert_eq!(out["user"], "u-1");
        assert_eq!(out["prompt_cache_key"], "ck-1");
        assert_eq!(out["service_tier"], "flex");
        assert_eq!(out["metadata"]["k"], "v");
    }

    // ── H8: structured function_call_output content array ──
    #[test]
    fn function_call_output_with_text_part_array_joins_text() {
        let body = json!({
            "model": "deepseek-chat",
            "input": [
                {
                    "type": "function_call",
                    "call_id": "c1",
                    "name": "shell",
                    "arguments": "{}"
                },
                {
                    "type": "function_call_output",
                    "call_id": "c1",
                    "output": [
                        { "type": "output_text", "text": "line one\n" },
                        { "type": "output_text", "text": "line two" }
                    ]
                },
            ],
        });
        let out = responses_to_chat(&body, &store());
        let tool_msg = out["messages"]
            .as_array()
            .unwrap()
            .iter()
            .find(|m| m["role"] == "tool")
            .unwrap();
        assert_eq!(tool_msg["content"], "line one\nline two");
    }

    // ── M14: reasoning.encrypted_content roundtrip on input ──
    #[test]
    fn input_reasoning_item_with_encrypted_content_buffers_for_next_tool_call() {
        let body = json!({
            "model": "deepseek-chat",
            "input": [
                {
                    "type": "reasoning",
                    "encrypted_content": "I should look at the files first.",
                    "summary": []
                },
                {
                    "type": "function_call",
                    "call_id": "c1",
                    "name": "shell",
                    "arguments": "{}"
                },
            ],
        });
        let out = responses_to_chat(&body, &store());
        let assistant = out["messages"]
            .as_array()
            .unwrap()
            .iter()
            .find(|m| m["role"] == "assistant")
            .unwrap();
        assert_eq!(
            assistant["reasoning_content"],
            "I should look at the files first."
        );
    }

    #[test]
    fn input_reasoning_item_summary_array_text_concatenated() {
        let body = json!({
            "model": "deepseek-chat",
            "input": [
                {
                    "type": "reasoning",
                    "summary": [
                        { "type": "summary_text", "text": "Step 1. " },
                        { "type": "summary_text", "text": "Step 2." }
                    ]
                },
                {
                    "type": "function_call",
                    "call_id": "c1",
                    "name": "shell",
                    "arguments": "{}"
                },
            ],
        });
        let out = responses_to_chat(&body, &store());
        let assistant = out["messages"]
            .as_array()
            .unwrap()
            .iter()
            .find(|m| m["role"] == "assistant")
            .unwrap();
        assert_eq!(assistant["reasoning_content"], "Step 1. Step 2.");
    }

    // ── L15-L17: handle web_search_call etc. + context_compaction alias ──
    #[test]
    fn web_search_call_input_item_becomes_system_note() {
        let body = json!({
            "model": "deepseek-chat",
            "input": [
                { "type": "web_search_call", "call_id": "ws_1", "action": { "query": "rust async" } },
            ],
        });
        let out = responses_to_chat(&body, &store());
        let msg = &out["messages"].as_array().unwrap()[0];
        assert_eq!(msg["role"], "system");
        let content = msg["content"].as_str().unwrap();
        assert!(content.contains("web_search"));
        assert!(content.contains("rust async"));
    }

    #[test]
    fn context_compaction_aliases_to_compaction() {
        let body = json!({
            "model": "deepseek-chat",
            "input": [
                {
                    "type": "context_compaction",
                    "encrypted_content": "Summary: user wanted X."
                },
            ],
        });
        let out = responses_to_chat(&body, &store());
        let msg = &out["messages"].as_array().unwrap()[0];
        let content = msg["content"].as_str().unwrap();
        assert!(content.contains("Summary"));
    }

    // ── M12: truncation passthrough ──
    #[test]
    fn truncation_parameter_passes_through() {
        let body = json!({
            "model": "gpt-5",
            "input": "hi",
            "truncation": "auto",
        });
        let out = responses_to_chat(&body, &store());
        assert_eq!(out["truncation"], "auto");
    }

    // ── L6: include array passthrough ──
    #[test]
    fn include_array_passes_through() {
        let body = json!({
            "model": "gpt-5",
            "input": "hi",
            "include": ["reasoning.encrypted_content", "message.output_text.logprobs"],
        });
        let out = responses_to_chat(&body, &store());
        let include = out["include"].as_array().unwrap();
        assert_eq!(include.len(), 2);
    }

    // ── L10: instructions override replaces head system on continuations ──
    #[test]
    fn instructions_replaces_existing_head_system_on_continuation() {
        let s = store();
        // Prior turn left a system message at head of history.
        s.save_history(
            "resp_prev",
            vec![
                json!({ "role": "system", "content": "old instructions" }),
                json!({ "role": "user", "content": "hi" }),
                json!({ "role": "assistant", "content": "hello" }),
            ],
        );
        let body = json!({
            "model": "gpt-5",
            "previous_response_id": "resp_prev",
            "input": "follow up",
            "instructions": "NEW instructions",
        });
        let out = responses_to_chat(&body, &s);
        let msgs = out["messages"].as_array().unwrap();
        // Head must be the NEW instructions, not the old one.
        assert_eq!(msgs[0]["role"], "system");
        assert_eq!(msgs[0]["content"], "NEW instructions");
    }

    // ── #206: empty-function-name guard ──

    #[test]
    fn nameless_tool_call_in_history_is_dropped_with_its_result() {
        // Replayed history carries an assistant tool_call whose name was
        // lost upstream (empty), plus its tool result. Both must be gone
        // so the request doesn't 400 with "missing a function name".
        let s = store();
        s.save_history(
            "resp_bad",
            vec![
                json!({ "role": "user", "content": "do it" }),
                json!({
                    "role": "assistant",
                    "content": null,
                    "tool_calls": [{
                        "id": "call_nameless",
                        "type": "function",
                        "function": { "name": "", "arguments": "{}" },
                    }],
                }),
                json!({ "role": "tool", "tool_call_id": "call_nameless", "content": "stale" }),
            ],
        );
        let body = json!({
            "model": "mimo-v2.5-pro",
            "previous_response_id": "resp_bad",
            "input": "next",
        });
        let out = responses_to_chat(&body, &s);
        let msgs = out["messages"].as_array().unwrap();
        // No tool_calls anywhere, no orphan tool message left behind.
        assert!(msgs.iter().all(|m| m.get("tool_calls").is_none()));
        assert!(msgs.iter().all(|m| m["role"] != "tool"));
        // The user turns survive.
        assert!(msgs.iter().any(|m| m["role"] == "user"));
    }

    #[test]
    fn nameless_tool_call_dropped_but_named_sibling_kept() {
        // Two grouped calls; only the named one (and its result) survive.
        let body = json!({
            "model": "mimo-v2.5-pro",
            "input": [
                { "type": "function_call", "call_id": "good", "name": "shell", "arguments": "{}" },
                { "type": "function_call", "call_id": "bad", "arguments": "{}" },
                { "type": "function_call_output", "call_id": "good", "output": "ok" },
                { "type": "function_call_output", "call_id": "bad", "output": "stale" },
            ],
        });
        let out = responses_to_chat(&body, &store());
        let msgs = out["messages"].as_array().unwrap();
        let assistant = msgs.iter().find(|m| m["role"] == "assistant").unwrap();
        let tcs = assistant["tool_calls"].as_array().unwrap();
        assert_eq!(tcs.len(), 1);
        assert_eq!(tcs[0]["id"], "good");
        let tool_ids: Vec<&str> = msgs
            .iter()
            .filter(|m| m["role"] == "tool")
            .map(|m| m["tool_call_id"].as_str().unwrap())
            .collect();
        assert_eq!(tool_ids, vec!["good"]);
    }

    #[test]
    fn nameless_tool_call_preserves_assistant_text_prelude() {
        // Assistant narrated a plan (text) then made a now-nameless call.
        // Whitespace-only name counts as empty; the text must survive as a
        // plain assistant message.
        let s = store();
        s.save_history(
            "resp_prelude",
            vec![json!({
                "role": "assistant",
                "content": "Let me check the files.",
                "tool_calls": [{
                    "id": "call_x",
                    "type": "function",
                    "function": { "name": "  ", "arguments": "{}" },
                }],
            })],
        );
        let body = json!({
            "model": "mimo-v2.5-pro",
            "previous_response_id": "resp_prelude",
            "input": "go on",
        });
        let out = responses_to_chat(&body, &s);
        let assistant = out["messages"]
            .as_array()
            .unwrap()
            .iter()
            .find(|m| m["role"] == "assistant")
            .unwrap();
        assert!(assistant.get("tool_calls").is_none());
        assert_eq!(assistant["content"], "Let me check the files.");
    }

    #[test]
    fn named_tool_calls_pass_through_untouched() {
        // Regression guard: the #206 strip must never touch healthy calls.
        let body = json!({
            "model": "deepseek-chat",
            "input": [
                { "type": "function_call", "call_id": "c1", "name": "shell", "arguments": "{}" },
                { "type": "function_call_output", "call_id": "c1", "output": "result" },
            ],
        });
        let out = responses_to_chat(&body, &store());
        let msgs = out["messages"].as_array().unwrap();
        assert_eq!(msgs.len(), 2);
        assert_eq!(msgs[0]["tool_calls"][0]["function"]["name"], "shell");
        assert_eq!(msgs[1]["content"], "result");
    }
}