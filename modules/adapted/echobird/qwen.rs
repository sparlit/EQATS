use serde_json::Value;

use super::{VendorAdapter, WebSearchSupport};

/// Alibaba Qwen / DashScope / Bailian / Tongyi (`qwen-*`). Enables search
/// via a top-level request param `enable_search: true` rather than a tool;
/// in OpenAI-compat mode the citation sources are NOT returned, but the
/// model still uses the search results.
/// https://www.alibabacloud.com/help/en/model-studio/web-search
pub struct Qwen;

impl VendorAdapter for Qwen {
    fn web_search(&self) -> WebSearchSupport {
        WebSearchSupport::RequestParams(vec![("enable_search".to_string(), Value::Bool(true))])
    }
}
