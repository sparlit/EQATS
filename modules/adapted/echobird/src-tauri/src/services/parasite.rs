// Parasite — wrap an installed AI agent CLI (currently just Claude Code) as a
// drop-in alternative to EchoBird's own agent_loop. Each user turn spawns the
// agent's CLI as a one-shot subprocess, captures its output, and emits events
// to the Mother Agent UI in the same shape as agent_event.
//
// Why this exists: Claude Code already ships a mature memory system, a
// curated tool set, and provider integration. Rather than reimplement those
// in EchoBird, we "parasite" — borrow the installed binary + its config
// without modifying it. The user taps Connect in Mother Agent; we run
// `claude -p` in its natural environment and stream the result back into our
// chat UI.
//
// Scope deliberately narrowed to Claude Code only: earlier scaffolding for
// Hermes Agent and OpenClaw was dropped to concentrate polish on the one
// agent we actively support. The `AGENTS` array stays as a single-entry
// table so adding another agent later is just adding an entry — but every
// field is required (no Option soup) since multi-agent flexibility is no
// longer the goal.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::process::Stdio;
use std::sync::Arc;
use tauri::{AppHandle, Emitter};
use tokio::io::AsyncReadExt;
use tokio::process::Command;
use tokio::sync::Mutex;
use tokio_util::sync::CancellationToken;

// ── Frontend Events ──

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum ParasiteEvent {
    #[serde(rename = "text_delta")]
    TextDelta { text: String },
    #[serde(rename = "done")]
    Done {},
    #[serde(rename = "error")]
    Error { message: String },
    #[serde(rename = "state")]
    StateChange { state: String },
}

// ── Agent Catalog ──

#[derive(Debug, Clone, Copy)]
pub struct ParasiteAgent {
    pub id: &'static str,
    pub name: &'static str,
    pub command: &'static str,
    /// Args for a fresh conversation (excluding the session arg and the user message).
    pub args_template: &'static [&'static str],
    /// Args when resuming a stored session. `{sessionId}` is substituted at build time.
    pub resume_args_template: &'static [&'static str],
    /// CLI flag for the session id (e.g. `--session-id`).
    pub session_arg: &'static str,
    /// Args to verify the binary is installed (e.g. `--version`).
    pub detect_args: &'static [&'static str],
}

const AGENTS: &[ParasiteAgent] = &[ParasiteAgent {
    id: "claudecode",
    name: "Claude Code",
    command: "claude",
    args_template: &[
        "-p",
        "--dangerously-skip-permissions",
        "--output-format",
        "json",
    ],
    resume_args_template: &[
        "-p",
        "--dangerously-skip-permissions",
        "--output-format",
        "json",
        "--resume",
        "{sessionId}",
    ],
    session_arg: "--session-id",
    detect_args: &["--version"],
}];

pub fn lookup_agent(id: &str) -> Option<ParasiteAgent> {
    AGENTS.iter().find(|a| a.id == id).copied()
}

// ── Session State ──

pub struct ParasiteSession {
    pub session_id: Option<String>,
    pub running: bool,
    pub cancel: CancellationToken,
}

impl ParasiteSession {
    pub fn new() -> Self {
        Self {
            session_id: None,
            running: false,
            cancel: CancellationToken::new(),
        }
    }

    pub fn prepare(&mut self) {
        if self.cancel.is_cancelled() {
            self.cancel = CancellationToken::new();
        }
        self.running = true;
    }

    pub fn abort(&mut self) {
        self.cancel.cancel();
        self.running = false;
    }
}

impl Default for ParasiteSession {
    fn default() -> Self {
        Self::new()
    }
}

/// Keyed by agent_id so each parasitable agent keeps its own session ID state
/// (e.g. Claude Code remembers its --resume target).
pub type SharedParasiteSessions = Arc<Mutex<HashMap<String, ParasiteSession>>>;

pub fn create_parasite_sessions() -> SharedParasiteSessions {
    Arc::new(Mutex::new(HashMap::new()))
}

// ── Detection ──

/// Probe each known agent by running `<command> --version` and return the IDs
/// of those that respond successfully. Hides Windows console popups via
/// CREATE_NO_WINDOW so the user never sees a flicker.
pub async fn detect_installed() -> Vec<String> {
    let mut installed = Vec::new();
    for agent in AGENTS {
        if probe(agent).await {
            installed.push(agent.id.to_string());
        }
    }
    installed
}

async fn probe(agent: &ParasiteAgent) -> bool {
    let mut cmd = Command::new(agent.command);
    cmd.args(agent.detect_args);
    cmd.stdout(Stdio::null()).stderr(Stdio::null());
    apply_no_window(&mut cmd);

    match tokio::time::timeout(std::time::Duration::from_secs(5), cmd.status()).await {
        Ok(Ok(status)) => status.success(),
        _ => false,
    }
}

#[cfg(target_os = "windows")]
fn apply_no_window(cmd: &mut Command) {
    // tokio::process::Command exposes creation_flags as an inherent method on
    // Windows targets; no extension-trait import needed.
    const CREATE_NO_WINDOW: u32 = 0x08000000;
    cmd.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(not(target_os = "windows"))]
fn apply_no_window(_cmd: &mut Command) {}

// ── Sending a Message ──

/// Build the full arg list for a turn. Substitutes `{sessionId}` in
/// `resume_args_template` when continuing an existing session; otherwise
/// builds from `args_template` and generates a fresh UUID for `--session-id`
/// so the next turn can `--resume` it. Appends the user message as the
/// trailing positional arg.
///
/// The wrapped agent is invoked WITHOUT a `--model` flag — by design,
/// Mother Agent's Connect mode lets the wrapped agent use whatever model
/// is in its own config (set via App Desktop or the agent's own setup).
fn build_args(
    agent: &ParasiteAgent,
    message: &str,
    existing_session_id: Option<&str>,
) -> (Vec<String>, Option<String>) {
    let mut args: Vec<String>;
    let effective_session: Option<String>;

    match existing_session_id {
        Some(sid) => {
            args = agent
                .resume_args_template
                .iter()
                .map(|a| a.replace("{sessionId}", sid))
                .collect();
            effective_session = Some(sid.to_string());
        }
        None => {
            args = agent.args_template.iter().map(|s| s.to_string()).collect();
            let new_id = uuid::Uuid::new_v4().to_string();
            args.push(agent.session_arg.to_string());
            args.push(new_id.clone());
            effective_session = Some(new_id);
        }
    }

    args.push(message.to_string());
    (args, effective_session)
}

/// Run a single turn against a parasited agent and stream the result to the
/// frontend via `parasite_event`. Cancellable via `session.cancel`.
pub async fn send_message(
    app: AppHandle,
    sessions: SharedParasiteSessions,
    agent_id: String,
    message: String,
) -> Result<(), String> {
    let agent =
        lookup_agent(&agent_id).ok_or_else(|| format!("Unknown parasite agent: {}", agent_id))?;

    // Snapshot/prepare session state (drop lock before spawn).
    let (existing_session_id, cancel_token) = {
        let mut map = sessions.lock().await;
        let sess = map.entry(agent_id.clone()).or_default();
        sess.prepare();
        (sess.session_id.clone(), sess.cancel.clone())
    };

    let _ = app.emit(
        "parasite_event",
        ParasiteEvent::StateChange {
            state: "processing".into(),
        },
    );

    let (args, effective_session_id) = build_args(&agent, &message, existing_session_id.as_deref());

    log::info!(
        "[Parasite] spawn {} {:?}",
        agent.command,
        args.iter()
            .map(|a| safe_truncate(a, 80))
            .collect::<Vec<_>>()
    );

    let mut cmd = Command::new(agent.command);
    cmd.args(&args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    apply_no_window(&mut cmd);

    let mut child = match cmd.spawn() {
        Ok(c) => c,
        Err(e) => {
            let msg = format!("Failed to spawn {}: {}", agent.command, e);
            log::error!("[Parasite] {}", msg);
            finish_session(&sessions, &agent_id, None).await;
            let _ = app.emit("parasite_event", ParasiteEvent::Error { message: msg });
            let _ = app.emit("parasite_event", ParasiteEvent::Done {});
            return Ok(());
        }
    };

    let mut stdout = child.stdout.take();
    let mut stderr = child.stderr.take();

    let outcome = tokio::select! {
        biased;
        _ = cancel_token.cancelled() => {
            log::info!("[Parasite] cancelled — killing subprocess");
            let _ = child.kill().await;
            ParasiteOutcome::Cancelled
        }
        result = async {
            let mut stdout_buf = String::new();
            let mut stderr_buf = String::new();
            if let Some(ref mut so) = stdout {
                let _ = so.read_to_string(&mut stdout_buf).await;
            }
            if let Some(ref mut se) = stderr {
                let _ = se.read_to_string(&mut stderr_buf).await;
            }
            let status = child.wait().await.map_err(|e| format!("wait error: {}", e))?;
            Ok::<_, String>((status, stdout_buf, stderr_buf))
        } => {
            match result {
                Ok((status, out, err)) => ParasiteOutcome::Completed { status, stdout: out, stderr: err },
                Err(e) => ParasiteOutcome::SpawnError(e),
            }
        }
    };

    match outcome {
        ParasiteOutcome::Cancelled => {
            finish_session(&sessions, &agent_id, effective_session_id).await;
            let _ = app.emit(
                "parasite_event",
                ParasiteEvent::Error {
                    message: "error.userCancelled".into(),
                },
            );
        }
        ParasiteOutcome::SpawnError(e) => {
            finish_session(&sessions, &agent_id, None).await;
            let _ = app.emit("parasite_event", ParasiteEvent::Error { message: e });
        }
        ParasiteOutcome::Completed {
            status,
            stdout,
            stderr,
        } => {
            if !status.success() {
                let msg = if !stderr.trim().is_empty() {
                    safe_truncate(stderr.trim(), 500).to_string()
                } else if !stdout.trim().is_empty() {
                    safe_truncate(stdout.trim(), 500).to_string()
                } else {
                    format!("{} exited with status {}", agent.command, status)
                };
                finish_session(&sessions, &agent_id, effective_session_id).await;
                let _ = app.emit("parasite_event", ParasiteEvent::Error { message: msg });
            } else {
                let parsed = parse_claude_json(&stdout);
                let final_session_id = parsed.session_id.or(effective_session_id);
                // Always remember session_id even on error — the wrapped
                // agent's conversation state is still valid; the next turn
                // (after the user fixes auth, switches model, etc.) should
                // resume rather than start fresh.
                finish_session(&sessions, &agent_id, final_session_id).await;
                if parsed.is_error {
                    // Wrapped agent returned a "successful" envelope that
                    // wraps an actual failure (Claude Code's 403 etc.) —
                    // surface it as a red error bubble instead of pretending
                    // it's a normal assistant reply.
                    let message = if parsed.text.is_empty() {
                        format!("{} returned an error with no message", agent.name)
                    } else {
                        parsed.text
                    };
                    let _ = app.emit("parasite_event", ParasiteEvent::Error { message });
                } else if !parsed.text.is_empty() {
                    let _ = app.emit(
                        "parasite_event",
                        ParasiteEvent::TextDelta { text: parsed.text },
                    );
                }
            }
        }
    }

    let _ = app.emit("parasite_event", ParasiteEvent::Done {});
    let _ = app.emit(
        "parasite_event",
        ParasiteEvent::StateChange {
            state: "idle".into(),
        },
    );
    Ok(())
}

enum ParasiteOutcome {
    Cancelled,
    SpawnError(String),
    Completed {
        status: std::process::ExitStatus,
        stdout: String,
        stderr: String,
    },
}

async fn finish_session(
    sessions: &SharedParasiteSessions,
    agent_id: &str,
    session_id: Option<String>,
) {
    let mut map = sessions.lock().await;
    if let Some(sess) = map.get_mut(agent_id) {
        sess.running = false;
        if session_id.is_some() {
            sess.session_id = session_id;
        }
    }
}

// ── Output Parsing ──

/// Result of parsing Claude Code's stdout: visible text, optional session id
/// for resume continuity, and whether the agent itself reported the response
/// is an error (distinct from a non-zero exit — process exits 0 but reports a
/// wrapped failure via the JSON envelope).
struct ParsedOutput {
    text: String,
    session_id: Option<String>,
    is_error: bool,
}

/// Claude Code with `--output-format json` emits a single JSON object on
/// completion. The envelope is `{"type":"result", "subtype":"success",
/// "is_error": bool, "result": "...", "session_id": "...", ...}`. Crucially,
/// `subtype` is always `"success"` even for HTTP errors — the truthful
/// failure indicator is `is_error: true` (often accompanied by
/// `api_error_status: 403/429/...`). See
/// memory/reference_claude_code_json_envelope_quirk.md.
fn parse_claude_json(stdout: &str) -> ParsedOutput {
    let trimmed = stdout.trim();
    if let Ok(v) = serde_json::from_str::<serde_json::Value>(trimmed) {
        let text = v
            .get("result")
            .and_then(|x| x.as_str())
            .unwrap_or(trimmed)
            .to_string();
        let session_id = v
            .get("session_id")
            .and_then(|x| x.as_str())
            .map(|s| s.to_string());
        let is_error = v.get("is_error").and_then(|x| x.as_bool()).unwrap_or(false);
        return ParsedOutput {
            text,
            session_id,
            is_error,
        };
    }
    ParsedOutput {
        text: trimmed.to_string(),
        session_id: None,
        is_error: false,
    }
}

// ── Helpers ──

fn safe_truncate(s: &str, max_chars: usize) -> &str {
    if s.chars().count() <= max_chars {
        return s;
    }
    let mut end = 0;
    for (i, _) in s.char_indices().take(max_chars) {
        end = i;
    }
    &s[..end]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn claude_args_new_session_generates_session_id() {
        let agent = lookup_agent("claudecode").unwrap();
        let (args, sid) = build_args(&agent, "ping", None);
        assert!(sid.is_some(), "fresh session must get a generated id");
        let sid = sid.unwrap();
        assert!(args.contains(&"--session-id".to_string()));
        assert!(args.contains(&sid));
        assert_eq!(args.last().map(|s| s.as_str()), Some("ping"));
    }

    #[test]
    fn claude_args_resume_uses_existing_session_id() {
        let agent = lookup_agent("claudecode").unwrap();
        let (args, sid) = build_args(&agent, "follow up", Some("sess-abc"));
        assert_eq!(sid.as_deref(), Some("sess-abc"));
        assert!(args.contains(&"--resume".to_string()));
        assert!(args.contains(&"sess-abc".to_string()));
        assert!(!args.iter().any(|a| a.contains("{sessionId}")));
        assert_eq!(args.last().map(|s| s.as_str()), Some("follow up"));
    }

    #[test]
    fn claude_args_never_passes_model_flag() {
        // Connect mode intentionally lets Claude Code use its own configured
        // model — no per-turn override — so --model should never appear.
        let agent = lookup_agent("claudecode").unwrap();
        let (args, _) = build_args(&agent, "hi", None);
        assert!(!args.contains(&"--model".to_string()));
    }

    #[test]
    fn parse_claude_json_extracts_result_and_session() {
        let raw = r#"{"type":"result","subtype":"success","result":"hello","session_id":"sess-x"}"#;
        let parsed = parse_claude_json(raw);
        assert_eq!(parsed.text, "hello");
        assert_eq!(parsed.session_id.as_deref(), Some("sess-x"));
        assert!(!parsed.is_error);
    }

    #[test]
    fn parse_claude_json_falls_back_on_non_json() {
        let parsed = parse_claude_json("not json at all");
        assert_eq!(parsed.text, "not json at all");
        assert!(parsed.session_id.is_none());
        assert!(!parsed.is_error);
    }

    #[test]
    fn parse_claude_json_flags_is_error_even_when_subtype_is_success() {
        // Claude Code's quirky envelope: subtype="success" means "successfully
        // wrapped a result" but is_error=true means the wrapped result is an
        // upstream failure (e.g. 403 from Anthropic). Both flags can coexist.
        let raw = r#"{"type":"result","subtype":"success","is_error":true,"api_error_status":403,"result":"Your organization has disabled Claude subscription access","session_id":"sess-y"}"#;
        let parsed = parse_claude_json(raw);
        assert!(parsed.is_error);
        assert_eq!(
            parsed.text,
            "Your organization has disabled Claude subscription access"
        );
        assert_eq!(parsed.session_id.as_deref(), Some("sess-y"));
    }

    #[test]
    fn lookup_agent_unknown_returns_none() {
        assert!(lookup_agent("hermes").is_none());
        assert!(lookup_agent("openclaw").is_none());
        assert!(lookup_agent("").is_none());
    }
}