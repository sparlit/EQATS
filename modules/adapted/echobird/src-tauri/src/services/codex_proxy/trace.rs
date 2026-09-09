// Opt-in, redacted request tracer for the Bridge path.
//
// Why this exists — the double deception makes failures invisible:
//
//   1. Model-id deception: Codex only ever sees the spoofed display name
//      (e.g. "gpt-5.5"). The real upstream model id (deepseek-v4-pro,
//      glm-5.2, …) exists only transiently between us and the upstream
//      (server.rs reads it from the relay file per request). Codex's own
//      session logs can't tell anyone which real model/endpoint was used.
//
//   2. Protocol deception: Codex only ever saw the Responses side; the
//      upstream only ever saw the Chat side. When a third-party upstream
//      rejects what we generated (tool_calls without tool_result, empty
//      function name, …) the offending Chat payload existed ONLY inside
//      this process — neither end can show it.
//
// So the request that actually failed lives nowhere but here, and used to
// be recoverable only by hand-rolling a temporary probe and reshipping.
// This tracer captures the boundaries to a per-request folder so triage
// becomes "set ECHOBIRD_CODEX_TRACE=1, reproduce, send the dump".
//
// OFF by default. Secrets (the upstream Authorization bearer / any
// api-key-shaped field) are redacted before anything touches disk.

use serde_json::{json, Value};
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::OnceLock;
use std::time::{SystemTime, UNIX_EPOCH};

/// Env var that turns tracing on. Read once (see `enabled`).
const TRACE_ENV: &str = "ECHOBIRD_CODEX_TRACE";

/// Per-process counter so two requests in the same millisecond get
/// distinct folders. Wraps the timestamp in the directory name.
static SEQ: AtomicU64 = AtomicU64::new(0);

/// True when the env var is set to a truthy value. Cached: toggling
/// requires a restart, matching our other `ECHOBIRD_*` env conventions,
/// and keeping the hot path free of a per-request env read.
pub fn enabled() -> bool {
    static ON: OnceLock<bool> = OnceLock::new();
    *ON.get_or_init(|| is_truthy(std::env::var(TRACE_ENV).ok().as_deref()))
}

fn is_truthy(v: Option<&str>) -> bool {
    matches!(
        v.map(|s| s.trim().to_ascii_lowercase()).as_deref(),
        Some("1") | Some("true") | Some("on") | Some("yes")
    )
}

fn trace_root() -> Option<PathBuf> {
    super::config_manager::default_relay_dir().map(|d| d.join("codex-trace"))
}

/// A handle to one request's trace folder. When tracing is off (the
/// default) `dir` is `None` and every method is a no-op — callers don't
/// need to branch on `enabled()`.
pub struct RequestTrace {
    dir: Option<PathBuf>,
}

impl RequestTrace {
    /// Allocate a per-request folder under `~/.echobird/codex-trace/`.
    /// Returns a no-op handle when tracing is disabled or the folder
    /// can't be created (never fails the request).
    pub fn start(label: &str) -> Self {
        if !enabled() {
            return Self { dir: None };
        }
        let dir = trace_root()
            .map(|root| {
                let n = SEQ.fetch_add(1, Ordering::Relaxed);
                let ts = SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .map(|d| d.as_millis())
                    .unwrap_or(0);
                root.join(format!("{ts}-{n:04}-{label}"))
            })
            .filter(|d| std::fs::create_dir_all(d).is_ok());
        Self { dir }
    }

    /// True when this request is being traced. Callers guard expensive
    /// captures (cloning a large request body) behind this so the hot
    /// path pays nothing when tracing is off.
    pub fn enabled(&self) -> bool {
        self.dir.is_some()
    }

    /// Write a redacted JSON file `<name>.json` into the trace folder.
    pub fn write_json(&self, name: &str, value: &Value) {
        if let Some(dir) = &self.dir {
            let redacted = redact(value);
            if let Ok(pretty) = serde_json::to_string_pretty(&redacted) {
                let _ = std::fs::write(dir.join(format!("{name}.json")), pretty);
            }
        }
    }

    /// Write a raw text file `<name>` (e.g. an upstream error body).
    /// Upstream error bodies are usually JSON envelopes, so we parse and
    /// field-redact them (same denylist as the JSON boundaries) before
    /// falling back to the inline-token scrubber for non-JSON text — a
    /// verbose relay that echoes the caller's credential back in its
    /// error body must not land it on disk unredacted.
    pub fn write_text(&self, name: &str, text: &str) {
        if let Some(dir) = &self.dir {
            let _ = std::fs::write(dir.join(name), redact_text(text));
        }
    }

    /// One-line outcome summary: which real model, which endpoint, what
    /// happened. The model-id deception means this attribution exists
    /// nowhere else.
    pub fn write_summary(
        &self,
        real_model: Option<&str>,
        upstream_url: &str,
        status: Option<u16>,
        outcome: &str,
        stream: bool,
    ) {
        // No-op when tracing is off (like write_json/write_text); the json!
        // is built only when enabled so the disabled hot path stays
        // allocation-free.
        if self.enabled() {
            self.write_json(
                "summary",
                &json!({
                    "real_model": real_model,
                    "upstream_url": upstream_url,
                    "status": status,
                    "outcome": outcome,
                    "stream": stream,
                }),
            );
        }
    }
}

// ---------------------------------------------------------------------------
// Redaction — the security-critical part. Better to over-redact a benign
// field than to ever let a key reach disk.
// ---------------------------------------------------------------------------

/// Recursively replace secret-bearing fields with "[REDACTED]" and scrub
/// inline `sk-`/`sk_` tokens out of free-text strings.
fn redact(value: &Value) -> Value {
    match value {
        Value::Object(map) => {
            let mut out = serde_json::Map::with_capacity(map.len());
            for (k, v) in map {
                if is_secret_key(k) {
                    out.insert(k.clone(), Value::String("[REDACTED]".into()));
                } else {
                    out.insert(k.clone(), redact(v));
                }
            }
            Value::Object(out)
        }
        Value::Array(arr) => Value::Array(arr.iter().map(redact).collect()),
        Value::String(s) => Value::String(scrub_string(s).unwrap_or_else(|| s.clone())),
        other => other.clone(),
    }
}

/// Field names whose VALUE is a credential. Separators are normalized
/// ('-' -> '_') so "x-api-key", "api-key", "x-goog-api-key" all share one
/// form. Over-redaction is acceptable here — masking a benign field costs
/// a little diagnostic signal; leaking a key is unacceptable. Deliberately
/// does NOT match `prompt_cache_key` / `idempotency_key` (not secrets,
/// diagnostically useful).
fn is_secret_key(key: &str) -> bool {
    let k = key.to_ascii_lowercase().replace('-', "_");
    matches!(
        k.as_str(),
        "authorization"
            | "proxy_authorization"
            | "authentication"
            | "www_authenticate"
            | "proxy_authenticate"
            | "cookie"
            | "set_cookie"
            | "api_key"
            | "apikey"
            | "x_api_key"
            | "openai_api_key"
            | "anthropic_api_key"
            | "x_goog_api_key"
            | "access_token"
            | "refresh_token"
            | "id_token"
            | "session_token"
            | "auth_token"
            | "bearer_token"
            | "token"
            | "secret"
            | "client_secret"
            | "password"
            | "passwd"
            | "bearer"
    ) || k.contains("api_key")
        || k.contains("apikey")
        || k.contains("secret")
        || k.contains("access_token")
        || k.ends_with("_token")
}

/// Redact a text blob destined for a `.txt` trace file. Upstream error
/// bodies are usually JSON envelopes, so parse-and-field-redact them (an
/// echoed `api_key`/`authorization` value then gets the denylist
/// treatment); fall back to the inline scrubber for genuinely non-JSON
/// text. This closes the gap where write_text used to run only the
/// best-effort scrubber on attacker/upstream-controlled bytes.
fn redact_text(text: &str) -> String {
    match serde_json::from_str::<Value>(text) {
        Ok(v) => serde_json::to_string_pretty(&redact(&v))
            .unwrap_or_else(|_| scrub_string(text).unwrap_or_else(|| text.to_string())),
        Err(_) => scrub_string(text).unwrap_or_else(|| text.to_string()),
    }
}

/// Known credential prefixes that may appear in FREE TEXT (chat content,
/// tool args, non-JSON error bodies). The field-name denylist handles the
/// JSON case; this catches keys embedded in raw text where there is no
/// field name to key on.
const KEY_PREFIXES: &[&str] = &[
    "sk-",
    "sk_",
    "pk-",
    "rk-",
    "AIza",
    "ghp_",
    "gho_",
    "ghs_",
    "ghu_",
    "github_pat_",
    "xoxb-",
    "xoxp-",
    "xapp-",
    "AKIA",
    "ASIA",
];

/// Minimum length of a prefix+run to treat as a key (avoids masking short
/// benign strings that merely start with a prefix, e.g. "sk-test").
const MIN_KEY_RUN: usize = 16;

/// Defense-in-depth for keys that leak into free text. Scans char by char
/// and masks the contiguous credential run wherever a known prefix
/// appears — regardless of the surrounding delimiter (space, tab,
/// newline, JSON quote). The previous space-split heuristic missed all of
/// those, including `"api_key":"sk-..."` inside JSON.
fn scrub_string(s: &str) -> Option<String> {
    if !KEY_PREFIXES.iter().any(|p| s.contains(p)) {
        return None;
    }
    let mut out = String::with_capacity(s.len());
    let mut rest = s;
    let mut changed = false;
    while !rest.is_empty() {
        if KEY_PREFIXES.iter().any(|p| rest.starts_with(p)) {
            // Length (in bytes) of the leading run of credential chars.
            let run_len = rest
                .char_indices()
                .take_while(|&(_, c)| c.is_ascii_alphanumeric() || c == '-' || c == '_')
                .map(|(idx, c)| idx + c.len_utf8())
                .last()
                .unwrap_or(0);
            if run_len >= MIN_KEY_RUN {
                out.push_str("[REDACTED]");
                rest = &rest[run_len..];
                changed = true;
                continue;
            }
        }
        let c = rest.chars().next().unwrap();
        out.push(c);
        rest = &rest[c.len_utf8()..];
    }
    changed.then_some(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn redacts_authorization_and_api_key_fields() {
        let input = json!({
            "headers": { "Authorization": "Bearer sk-secret1234567890abc", "x-api-key": "abc123" },
            "api_key": "sk-topsecret1234567890",
            "model": "deepseek-v4-pro",
            "nested": { "apiKey": "leakvalue" },
            "list": [ { "client_secret": "zzz" } ]
        });
        let out = redact(&input);
        let s = serde_json::to_string(&out).unwrap();
        // No secret value survives anywhere in the serialized output.
        assert!(!s.contains("sk-secret1234567890abc"));
        assert!(!s.contains("sk-topsecret1234567890"));
        assert!(!s.contains("abc123"));
        assert!(!s.contains("leakvalue"));
        assert!(!s.contains("zzz"));
        // Non-secret fields are preserved for diagnosis.
        assert!(s.contains("deepseek-v4-pro"));
        assert_eq!(out["api_key"], json!("[REDACTED]"));
        assert_eq!(out["nested"]["apiKey"], json!("[REDACTED]"));
        assert_eq!(out["list"][0]["client_secret"], json!("[REDACTED]"));
    }

    #[test]
    fn preserves_non_secret_key_named_fields() {
        // "key" appearing in a non-credential field name must survive —
        // these carry real routing/caching signal we need in a trace.
        let input = json!({
            "prompt_cache_key": "user-session-42",
            "idempotency_key": "req-7",
            "model": "glm-5.2",
        });
        let out = redact(&input);
        assert_eq!(out["prompt_cache_key"], json!("user-session-42"));
        assert_eq!(out["idempotency_key"], json!("req-7"));
        assert_eq!(out["model"], json!("glm-5.2"));
    }

    #[test]
    fn scrubs_inline_sk_token_in_free_text() {
        let input = json!({ "content": "my key is sk-abcdefghijklmnopqrstuvwxyz0123 thanks" });
        let out = redact(&input);
        let content = out["content"].as_str().unwrap();
        assert!(!content.contains("sk-abcdefghijklmnopqrstuvwxyz0123"));
        assert!(content.contains("[REDACTED]"));
        // Surrounding words are untouched.
        assert!(content.contains("my key is"));
        assert!(content.contains("thanks"));
    }

    #[test]
    fn write_text_json_body_field_redacts_echoed_key() {
        // A verbose relay that echoes the caller's key in a JSON error
        // body must not land it on disk — the .txt path now JSON-redacts.
        let body = r#"{"error":{"message":"bad key","provided_key":"sk-or-v1-abcdefghijklmnopqrstuvwxyz"}}"#;
        let out = redact_text(body);
        assert!(!out.contains("sk-or-v1-abcdefghijklmnopqrstuvwxyz"));
        assert!(out.contains("[REDACTED]"));
        assert!(out.contains("bad key")); // non-secret message survives
    }

    #[test]
    fn redact_text_nonjson_scrubs_known_prefixes() {
        // Non-JSON multiline body, keys delimited by newline/tab/space.
        let body =
            "Invalid:\nsk-abcdefghijklmnopqrstuvwxyz0123\trejected AIzaSyD0123456789012345678901234567 end";
        let out = redact_text(body);
        assert!(!out.contains("sk-abcdefghijklmnopqrstuvwxyz0123"));
        assert!(!out.contains("AIzaSyD0123456789012345678901234567"));
        assert!(out.contains("[REDACTED]"));
        assert!(out.contains("rejected") && out.contains("end"));
    }

    #[test]
    fn scrub_string_catches_keys_across_delimiters() {
        // newline / tab delimited (the old space-splitter missed these)
        assert!(scrub_string("a\nsk-abcdefghijklmnopqrstuvwxyz0123\nb")
            .unwrap()
            .contains("[REDACTED]"));
        assert!(scrub_string("x\tsk_abcdefghijklmnopqrstuvwxyz0123\ty")
            .unwrap()
            .contains("[REDACTED]"));
        // embedded in JSON quotes
        let q = scrub_string(r#"{"api_key":"sk-abcdefghijklmnopqrstuvwxyz0123"}"#).unwrap();
        assert!(!q.contains("sk-abcdefghijklmnopqrstuvwxyz0123"));
        // short benign string that merely starts with a prefix is untouched
        assert!(scrub_string("sk-ab").is_none());
    }

    #[test]
    fn is_secret_key_broadened_families_match_and_preserve() {
        for k in [
            "Authentication",
            "Proxy-Authorization",
            "Cookie",
            "Set-Cookie",
            "x-goog-api-key",
            "x-portkey-api-key",
            "api_secret",
            "x-secret",
            "session_token",
            "auth_token",
            "token",
            "bearer",
        ] {
            assert!(is_secret_key(k), "expected secret: {k}");
        }
        for k in [
            "prompt_cache_key",
            "idempotency_key",
            "model",
            "client_id",
            "user",
        ] {
            assert!(!is_secret_key(k), "expected NOT secret: {k}");
        }
    }

    #[test]
    fn enabled_matches_only_truthy_values() {
        assert!(is_truthy(Some("1")));
        assert!(is_truthy(Some("true")));
        assert!(is_truthy(Some("ON")));
        assert!(is_truthy(Some(" yes ")));
        assert!(!is_truthy(Some("0")));
        assert!(!is_truthy(Some("false")));
        assert!(!is_truthy(Some("")));
        assert!(!is_truthy(None));
    }
}