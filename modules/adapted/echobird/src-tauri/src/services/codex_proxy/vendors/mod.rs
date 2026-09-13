// Per-vendor adapters for third-party Chat-Completions upstreams.
//
// Codex talks the OpenAI Responses API; we translate to Chat Completions
// for non-OpenAI providers (see protocol_converter.rs). Most provider
// quirks are universal, but a few need per-vendor shaping. The first such
// quirk modeled here is the built-in `web_search` tool: Codex sends a
// Responses `{type:"web_search"}` tool, but every vendor exposes search
// differently —
//
//   • MiMo  — bare `{type:"web_search"}` tool PLUS a `webSearchEnabled:true`
//             request flag (the tool alone 400s "...webSearchEnabled is
//             false"); server-side auto, results returned as `annotations`
//             (forwarded by the stream translator).
//             mimo.mi.com/docs/.../tool-calling/web-search
//   • GLM   — nested `{type:"web_search","web_search":{enable,...}}` tool,
//             results cited inline in message content.
//             docs.bigmodel.cn/cn/guide/tools/web-search
//   • Qwen  — a top-level request param `enable_search:true` (NOT a tool);
//             sources are not returned in OpenAI-compat mode.
//             alibabacloud.com/help/en/model-studio/web-search
//   • other — no native Chat web search → drop the tool (default).
//
// `adapter_for(model_id)` routes by model-id substring (the REAL upstream
// model id, already substituted before translation — see server.rs). Add a
// vendor by adding a module here + a branch in `adapter_for`.

mod glm;
mod mimo;
mod qwen;

use serde_json::Value;

/// How a vendor exposes Codex's built-in `web_search` tool on its Chat
/// Completions endpoint.
pub enum WebSearchSupport {
    /// No native Chat web search — drop the tool entirely. A bare
    /// `{type:"web_search"}` 400s a provider that doesn't recognize it.
    Drop,
    /// Enable search via top-level request-body params merged into the Chat
    /// request (e.g. Qwen's `enable_search: true`); the `web_search` tool
    /// itself is not forwarded.
    RequestParams(Vec<(String, Value)>),
    /// Emit the tool into the Chat `tools` array AND set top-level request
    /// params. MiMo needs both: the `{type:"web_search"}` tool PLUS a
    /// `webSearchEnabled: true` flag — sending the tool without the flag 400s
    /// ("web search tool found in the request body, but webSearchEnabled is
    /// false").
    ToolWithParams(Value, Vec<(String, Value)>),
}

/// Per-vendor request shaping for a third-party Chat upstream. The default
/// impl is the generic OpenAI-compatible behavior; vendors override only
/// what they need.
pub trait VendorAdapter {
    /// What to do with Codex's built-in `web_search` tool. Default: drop.
    fn web_search(&self) -> WebSearchSupport {
        WebSearchSupport::Drop
    }
}

/// The generic adapter — plain OpenAI-compatible Chat, no special shaping.
struct Generic;
impl VendorAdapter for Generic {}

/// Pick the adapter for an upstream model id (case-insensitive substring
/// match on the REAL provider model id, not Codex's display name).
pub fn adapter_for(model_id: &str) -> Box<dyn VendorAdapter> {
    let m = model_id.to_ascii_lowercase();
    if m.contains("mimo") {
        Box::new(mimo::Mimo)
    } else if m.contains("glm") || m.contains("zhipu") || m.contains("z.ai") {
        Box::new(glm::Glm)
    } else if m.contains("qwen")
        || m.contains("dashscope")
        || m.contains("bailian")
        || m.contains("tongyi")
    {
        Box::new(qwen::Qwen)
    } else {
        Box::new(Generic)
    }
}