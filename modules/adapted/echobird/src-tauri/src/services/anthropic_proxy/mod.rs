// Anthropic Messages API proxy for Claude Desktop AND Claude Code 3P mode.
//
// Claude Desktop's `inferenceGatewayBaseUrl` (and Claude Code's
// `ANTHROPIC_BASE_URL`) point at this proxy (127.0.0.1:CODEX_PROXY_PORT,
// shared with the Codex /v1/responses handler — same axum app, different
// routes). Every incoming POST is rewritten with the relay's real model id
// and forwarded to the user-selected upstream provider's /v1/messages.
//
// Two routes, two relay files, so the two Claude apps stay independent:
//   • POST /v1/messages            → ~/.echobird/claudedesktop.json
//   • POST /claudecode/v1/messages → ~/.echobird/claudecode.json
//
// Unlike codex_proxy, this is NOT a protocol translator — both sides
// speak the same Anthropic Messages API. The only transformation is
// model-id substitution: Claude Desktop hard-codes "claude-sonnet-4-*"
// / "claude-opus-*" / "claude-haiku-4-*" as the request model field,
// but strict upstreams (Xiaomi MiMo, etc.) reject those names and
// require their own real id (e.g. "mimo-v2.5-pro"). Smart upstreams
// (DeepSeek /anthropic, GLM /anthropic) auto-route claude-* to their
// own model so the rewrite is a no-op for them.
//
// Relay file: ~/.echobird/claudedesktop.json, written by
// tool_config_manager::apply_claudedesktop on every model switch. The
// proxy reads it fresh on every request so model switches need no
// proxy restart.

pub use messages_handler::{handle_messages, handle_messages_claudecode};

mod messages_handler;