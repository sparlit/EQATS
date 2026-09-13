use super::{VendorAdapter, WebSearchSupport};

/// Zhipu GLM (`glm-*` / zhipu / z.ai).
///
/// Web search is DROPPED for GLM. GLM documents a nested chat web-search tool
/// `{type:"web_search","web_search":{enable,search_engine}}`
/// (https://docs.bigmodel.cn/cn/guide/tools/web-search), but GLM-5.2's Chat
/// Completions endpoint strictly validates that EVERY `tools[]` entry carries a
/// `function` key. Mixing that non-function web-search tool with Codex's
/// function tools makes GLM reject the whole request with
/// "missing `tools.function` parameter", breaking Codex + GLM entirely.
///
/// GLM web search was never confirmed working through this path, so we drop it:
/// the function tools (Codex's actual capabilities) pass through cleanly and the
/// model still answers — just without server-side search. Revisit only if a
/// tools-array-compatible GLM search format is verified against the live API.
pub struct Glm;

impl VendorAdapter for Glm {
    fn web_search(&self) -> WebSearchSupport {
        WebSearchSupport::Drop
    }
}