// Codex model-catalog generation — per-vendor capability templates, embedded
// at compile time via `include_str!` and matched to the selected provider by
// its base_url domain.
//
// Why this exists: when Codex talks to a third-party Responses endpoint
// directly, `apply_codex` writes
// the provider's REAL base_url + REAL model id into `~/.codex/config.toml`.
// For those direct connections Codex needs a model catalog
// (`model_catalog_json = "<path>"` → a JSON file declaring the model's context
// window, reasoning levels, tool capabilities, and base prompt); without it
// Codex doesn't know the model — it mis-sizes the context window and can't
// register the model's tools.
//
// The bundled assets are NOT model lists. Each is a **capability template** for
// one vendor — the fields that are model-agnostic (base_instructions prompt
// framework, apply_patch_tool_type, web_search_tool_type, supported_reasoning
// levels, truncation_policy, input_modalities, …). `build_catalog` stamps the
// selected model's identity onto that template (slug / display_name /
// context_window / priority) and emits a single-entry `{"models":[...]}`.
// Unknown model versions remain usable with conservative text-only defaults;
// image input is enabled only for model IDs documented by the vendor. Matching
// is domain-only, never by model brand (a reseller may not implement the same
// capabilities).
//
// Vendors we do NOT bundle keep the current behavior: no `model_catalog_json`
// line, Codex talks to the upstream directly with the real id (its own default
// catalog applies). If a vendor's model doesn't support the Responses protocol
// at all, it cannot be used by Codex through EchoBird.

use serde_json::{json, Value};
use std::path::PathBuf;
use url::Url;

/// DeepSeek's Codex capability template. `base_instructions` /
/// `model_messages.instructions_template` carry the full model-agnostic Codex
/// agent prompt framework + `apply_patch_tool_type: "freeform"` (extracted
/// verbatim from DeepSeek's official setup script). Model identity and the
/// selected model's image capability are stamped by `build_catalog`.
pub const DEEPSEEK_TEMPLATE: &str = include_str!("../../assets/codex-catalogs/deepseek.json");

/// MiniMax Codex capability template (adaptive thinking, 1M window, text +
/// image). `base_instructions` uses a `{model}` placeholder filled with the
/// selected display name.
pub const MINIMAX_TEMPLATE: &str = include_str!("../../assets/codex-catalogs/minimax.json");

/// Xiaomi MiMo Codex capability template (1M window, NO web_search tool —
/// MiMo rejects it with a hard 400). Model identity and the selected model's
/// image capability are stamped by `build_catalog`.
pub const MIMO_TEMPLATE: &str = include_str!("../../assets/codex-catalogs/mimo.json");

/// Match a provider base_url to the bundled capability template that applies.
/// Domain-only, never by model brand. Returns the template JSON string, or
/// `None` for vendors we don't bundle (keep the existing no-catalog path).
pub fn url_matches_domain(base_url: &str, domain: &str) -> bool {
    let Some(host) = Url::parse(base_url).ok().and_then(|url| {
        url.host_str()
            .map(|host| host.trim_end_matches('.').to_ascii_lowercase())
    }) else {
        return false;
    };
    let domain = domain.trim_end_matches('.').to_ascii_lowercase();
    host == domain || host.ends_with(&format!(".{domain}"))
}

pub fn template_for_url(base_url: &str) -> Option<&'static str> {
    if url_matches_domain(base_url, "deepseek.com") {
        Some(DEEPSEEK_TEMPLATE)
    } else if url_matches_domain(base_url, "minimax.cn")
        || url_matches_domain(base_url, "minimaxi.com")
        || url_matches_domain(base_url, "minimax.io")
    {
        Some(MINIMAX_TEMPLATE)
    } else if url_matches_domain(base_url, "xiaomimimo.com") {
        Some(MIMO_TEMPLATE)
    } else {
        None
    }
}

/// Build a single-entry model catalog for the SELECTED model from a vendor
/// capability template. The template's model-agnostic fields (base_instructions
/// framework, tool types, reasoning levels, truncation policy) are preserved;
/// the model identity (slug / display_name / description / context_window /
/// priority) is stamped from the caller. Unknown model versions need no asset
/// update for text use; capabilities that are unsafe to guess are opt-in.
pub fn build_catalog(
    template: &Value,
    model_id: &str,
    display_name: &str,
    context_window: u64,
) -> Value {
    let mut entry = template.clone();
    entry["slug"] = json!(model_id);
    entry["display_name"] = json!(display_name);
    entry["description"] = json!(format!("{display_name} via EchoBird"));
    entry["context_window"] = json!(context_window);
    entry["max_context_window"] = json!(context_window);
    entry["priority"] = json!(0);

    // The vendor catalogs are model-specific here: DeepSeek Flash and MiMo
    // v2.5 accept images, while DeepSeek V4 Pro and MiMo v2.5 Pro are text
    // only. Keep the bundled templates conservative and opt in only the
    // model IDs documented by the vendors.
    let supports_image = matches!(model_id, "deepseek-flash" | "mimo-v2.5");
    if model_id.starts_with("deepseek-") || model_id.starts_with("mimo-") {
        entry["input_modalities"] = if supports_image {
            json!(["text", "image"])
        } else {
            json!(["text"])
        };
        entry["supports_image_detail_original"] = json!(supports_image);
    }
    if model_id.starts_with("deepseek-") {
        entry["supports_search_tool"] = json!(model_id == "deepseek-flash");
    }
    // MiniMax's base_instructions carries a `{model}` placeholder; substitute
    // the selected display name so the prompt names the actual model. Vendors
    // whose prompt is model-agnostic (DeepSeek) are unaffected.
    if let Some(bi) = entry["base_instructions"].as_str() {
        if bi.contains("{model}") {
            entry["base_instructions"] = json!(bi.replace("{model}", display_name));
        }
    }
    json!({ "models": [entry] })
}

/// Absolute path to the catalog file Codex reads. Uses forward slashes on
/// every platform so the value stays valid inside config.toml's basic strings
/// on Windows (backslashes would need TOML escaping). Honors
/// `ECHOBIRD_CODEX_CONFIG_DIR` via `default_codex_dir` so tests can point at
/// temp dirs — the same override the Codex runtime migration uses.
pub fn models_json_path() -> PathBuf {
    let codex_dir = crate::services::codex_runtime::default_codex_dir()
        .unwrap_or_else(|| dirs::home_dir().unwrap_or_default().join(".codex"));
    let raw = codex_dir.join("models.json");
    PathBuf::from(raw.to_string_lossy().replace('\\', "/"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn template_for_url_matches_deepseek_domain() {
        assert_eq!(
            template_for_url("https://api.deepseek.com/v1"),
            Some(DEEPSEEK_TEMPLATE)
        );
        assert_eq!(
            template_for_url("https://api.deepseek.com"),
            Some(DEEPSEEK_TEMPLATE)
        );
        assert_eq!(template_for_url("https://notdeepseek.com/v1"), None);
    }

    #[test]
    fn template_for_url_matches_minimax_domains() {
        assert_eq!(
            template_for_url("https://api.minimax.cn/v1"),
            Some(MINIMAX_TEMPLATE)
        );
        assert_eq!(
            template_for_url("https://api.minimaxi.com/v1"),
            Some(MINIMAX_TEMPLATE)
        );
        assert_eq!(
            template_for_url("https://api.minimax.io/v1"),
            Some(MINIMAX_TEMPLATE)
        );
    }

    #[test]
    fn template_for_url_matches_mimo_domains() {
        assert_eq!(
            template_for_url("https://api.xiaomimimo.com/v1"),
            Some(MIMO_TEMPLATE)
        );
        // Token-plan regional endpoints share the same domain.
        assert_eq!(
            template_for_url("https://token-plan-cn.xiaomimimo.com/v1"),
            Some(MIMO_TEMPLATE)
        );
        assert_eq!(template_for_url("https://notxiaomimimo.com/v1"), None);
    }

    #[test]
    fn template_for_url_returns_none_for_unbundled_vendors() {
        assert_eq!(
            template_for_url("https://ark.cn-beijing.volces.com/api/coding/v1"),
            None
        );
        assert_eq!(template_for_url("https://api.openai.com/v1"), None);
        assert_eq!(template_for_url("https://api.moonshot.cn/v1"), None);
    }

    #[test]
    fn bundled_templates_parse() {
        for template in [DEEPSEEK_TEMPLATE, MINIMAX_TEMPLATE, MIMO_TEMPLATE] {
            let v: Value = serde_json::from_str(template).expect("bundled template must parse");
            assert!(
                v.get("base_instructions")
                    .and_then(|x| x.as_str())
                    .is_some(),
                "template must carry base_instructions"
            );
            assert!(
                v.get("models").is_none(),
                "template must NOT be a model list — identity is stamped at build time"
            );
        }
    }

    #[test]
    fn deepseek_template_keeps_freeform_patch_framework() {
        let v: Value = serde_json::from_str(DEEPSEEK_TEMPLATE).unwrap();
        assert_eq!(
            v.get("apply_patch_tool_type").and_then(|x| x.as_str()),
            Some("freeform")
        );
        let instr = v
            .get("base_instructions")
            .and_then(|x| x.as_str())
            .unwrap_or("");
        assert!(
            instr.len() > 1000,
            "base_instructions framework must ship verbatim"
        );
    }

    #[test]
    fn deepseek_and_mimo_templates_default_to_text_only() {
        // Unknown/new model IDs must not advertise image input until the
        // vendor documents it. `build_catalog` opts known vision models in.
        for template in [DEEPSEEK_TEMPLATE, MIMO_TEMPLATE] {
            let v: Value = serde_json::from_str(template).unwrap();
            let modalities = v
                .get("input_modalities")
                .and_then(|x| x.as_array())
                .expect("template must declare input_modalities");
            assert_eq!(modalities.len(), 1);
            assert_eq!(modalities[0].as_str(), Some("text"));
            assert_eq!(
                v.get("supports_image_detail_original")
                    .and_then(|x| x.as_bool()),
                Some(false)
            );
        }
    }

    #[test]
    fn vendor_model_capabilities_match_official_catalogs() {
        for (template, model_id, supports_image, supports_search) in [
            (DEEPSEEK_TEMPLATE, "deepseek-flash", true, true),
            (DEEPSEEK_TEMPLATE, "deepseek-v4-pro", false, false),
            (MIMO_TEMPLATE, "mimo-v2.5", true, false),
            (MIMO_TEMPLATE, "mimo-v2.5-pro", false, false),
        ] {
            let template: Value = serde_json::from_str(template).unwrap();
            let catalog = build_catalog(&template, model_id, model_id, 1_048_576);
            let entry = &catalog["models"][0];
            let modalities = entry["input_modalities"].as_array().unwrap();
            assert_eq!(
                modalities
                    .iter()
                    .any(|value| value.as_str() == Some("image")),
                supports_image,
                "wrong image capability for {model_id}"
            );
            assert_eq!(
                entry["supports_image_detail_original"].as_bool(),
                Some(supports_image),
                "wrong original-image capability for {model_id}"
            );
            assert_eq!(
                entry["supports_search_tool"].as_bool(),
                Some(supports_search),
                "wrong search capability for {model_id}"
            );
        }
    }

    #[test]
    fn build_catalog_stamps_selected_model_identity() {
        // A new model version (v5) the bundled template has never heard of
        // must produce a catalog containing ONLY that model — no stale vendor
        // list, no accumulation.
        let tpl: Value = serde_json::from_str(DEEPSEEK_TEMPLATE).unwrap();
        let catalog = build_catalog(&tpl, "deepseek-v5-flash", "DeepSeek-V5-Flash", 1_048_576);
        let models = catalog.get("models").and_then(|m| m.as_array()).unwrap();
        assert_eq!(
            models.len(),
            1,
            "catalog must contain exactly the selected model"
        );
        let entry = &models[0];
        assert_eq!(
            entry.get("slug").and_then(|x| x.as_str()),
            Some("deepseek-v5-flash")
        );
        assert_eq!(
            entry.get("display_name").and_then(|x| x.as_str()),
            Some("DeepSeek-V5-Flash")
        );
        assert_eq!(
            entry.get("context_window").and_then(|x| x.as_u64()),
            Some(1_048_576)
        );
        // Capability framework survives the stamp.
        assert_eq!(
            entry.get("apply_patch_tool_type").and_then(|x| x.as_str()),
            Some("freeform")
        );
    }

    #[test]
    fn build_catalog_stamps_mimo_new_version() {
        // Same zero-maintenance promise as DeepSeek: mimo-v2.6 must produce a
        // catalog containing ONLY that model — the {date}/{week} placeholders
        // stay verbatim (Codex fills them at runtime), no {model} substitution
        // needed, no stale mimo-v2.5 / v2.5-pro entries.
        let tpl: Value = serde_json::from_str(MIMO_TEMPLATE).unwrap();
        let catalog = build_catalog(&tpl, "mimo-v2.6", "mimo-v2.6", 1_048_576);
        let models = catalog.get("models").and_then(|m| m.as_array()).unwrap();
        assert_eq!(models.len(), 1);
        let entry = &models[0];
        assert_eq!(
            entry.get("slug").and_then(|x| x.as_str()),
            Some("mimo-v2.6")
        );
        assert_eq!(
            entry.get("display_name").and_then(|x| x.as_str()),
            Some("mimo-v2.6")
        );
        assert_eq!(
            entry.get("context_window").and_then(|x| x.as_u64()),
            Some(1_048_576)
        );
        // Capability block (incl. no web_search for MiMo) survives.
        assert_eq!(
            entry.get("supports_search_tool").and_then(|x| x.as_bool()),
            Some(false)
        );
    }

    #[test]
    fn build_catalog_substitutes_model_placeholder() {
        let tpl: Value = serde_json::from_str(MINIMAX_TEMPLATE).unwrap();
        let catalog = build_catalog(&tpl, "MiniMax-M5", "MiniMax-M5", 1_000_000);
        let entry = &catalog["models"][0];
        let bi = entry
            .get("base_instructions")
            .and_then(|x| x.as_str())
            .unwrap_or("");
        assert!(
            bi.contains("MiniMax-M5") && !bi.contains("{model}"),
            "placeholder must be substituted: {bi}"
        );
    }

    #[test]
    fn build_catalog_applies_context_window_registry() {
        let tpl: Value = serde_json::from_str(DEEPSEEK_TEMPLATE).unwrap();
        let catalog = build_catalog(&tpl, "mini-model", "Mini Model", 204_800);
        assert_eq!(
            catalog["models"][0]["context_window"].as_u64(),
            Some(204_800)
        );
        assert_eq!(
            catalog["models"][0]["max_context_window"].as_u64(),
            Some(204_800)
        );
    }

    #[test]
    fn models_json_path_is_absolute_and_forward_slashed() {
        let p = models_json_path();
        assert!(p.is_absolute());
        let s = p.to_string_lossy();
        assert!(
            !s.contains('\\'),
            "Windows backslash must be forward-slashed: {s}"
        );
        assert!(
            s.ends_with("/models.json"),
            "must end with /models.json: {s}"
        );
    }
}