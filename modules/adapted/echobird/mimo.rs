use serde_json::{json, Value};

use super::{VendorAdapter, WebSearchSupport};

/// Xiaomi MiMo (`mimo-*`). Its Chat Completions endpoint accepts a bare
/// `{type:"web_search"}` tool, runs the search server-side, and returns
/// results as `annotations` url_citations — which the stream translator
/// already forwards as Responses `output_text.annotations`. It ALSO requires
/// a top-level `webSearchEnabled: true` flag: the tool alone 400s
/// "web search tool found in the request body, but webSearchEnabled is false".
/// https://mimo.mi.com/docs/en-US/quick-start/usage-guide/tool-calling/web-search
pub struct Mimo;

impl VendorAdapter for Mimo {
    fn web_search(&self) -> WebSearchSupport {
        // Bare tool type (strip Codex's OpenAI-specific fields MiMo doesn't
        // expect; it applies its own defaults) PLUS the `webSearchEnabled`
        // flag MiMo requires alongside the tool.
        WebSearchSupport::ToolWithParams(
            json!({ "type": "web_search" }),
            vec![("webSearchEnabled".to_string(), Value::Bool(true))],
        )
    }
}
