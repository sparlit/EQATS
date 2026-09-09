// Codex model-catalog generation — per-vendor capability templates, embedded
// at compile time via `include_str!` and matched to the selected provider by
// its base_url domain.
//
// Why this exists: when Codex talks to a third-party Responses endpoint
// directly (EchoBird's "Responses passthrough" toggle), `apply_codex` writes
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
// context_window / priority) and emits a single-entry `{"models":[...]}`. So
// switching to `deepseek-v5-flash` or `mimo-v2.6` "just works" with zero
// maintenance — we never enumerate a vendor's model versions. Matching is
// domain-only, never by model brand (a reseller may not implement the same
// capabilities — same rule cc-switch v3.19.1 uses).
//
// Vendors we do NOT bundle keep the current behavior: no `model_catalog_json`
// line, Codex talks to the upstream directly with the real id (its own default
// catalog applies). If a vendor's model doesn't support the Responses protocol
// at all, the user simply leaves the Responses toggle OFF and traffic goes
// through our proxy (bridge translation) — no catalog is involved either way.

use serde_json::{json, Value};
use std::path::PathBuf;

/// DeepSeek's Codex capability template. `base_instructions` /
/// `model_messages.instructions_template` carry the full model-agnostic Codex
/// agent prompt framework + `apply_patch_tool_type: "freeform"` (extracted
/// verbatim from DeepSeek's official setup script). No model identity fields.
pub const DEEPSEEK_TEMPLATE: &str = include_str!("../../assets/codex-catalogs/deepseek.json");

/// MiniMax Codex capability template (adaptive thinking, 1M window, text +
/// image). `base_instructions` uses a `{model}` placeholder filled with the
/// selected display name.
pub const MINIMAX_TEMPLATE: &str = include_str!("../../assets/codex-catalogs/minimax.json");

/// Xiaomi MiMo Codex capability template (1M window, text + image, NO
/// web_search tool — MiMo rejects it with a hard 400). Mirrors the catalog
/// cc-switch generates for MiMo.
pub const MIMO_TEMPLATE: &str = include_str!("../../assets/codex-catalogs/mimo.json");

/// Match a provider base_url to the bundled capability template that applies.
/// Domain-only, never by model brand. Returns the template JSON string, or
/// `None` for vendors we don't bundle (keep the existing no-catalog path).
pub fn template_for_url(base_url: &str) -> Option<&'static str> {
    if base_url.contains("deepseek.com") {
        Some(DEEPSEEK_TEMPLATE)
    } else if base_url.contains("minimaxi.com") || base_url.contains("minimax.io") {
        Some(MINIMAX_TEMPLATE)
    } else if base_url.contains("xiaomimimo.com") {
        Some(MIMO_TEMPLATE)
    } else {
        None
    }
}

/// Build a single-entry model catalog for the SELECTED model from a vendor
/// capability template. The template's model-agnostic fields (base_instructions
/// framework, tool types, reasoning levels, truncation policy) are preserved;
/// the model identity (slug / display_name / description / context_window /
/// priority) is stamped from the caller. This is the key maintenance-saving
/// step: we never enumerate a vendor's model versions, so a new `v6` or `v7`
/// needs no bundled-asset change.
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
/// temp dirs — same override the relay/canonical config code uses.
pub fn models_json_path() -> PathBuf {
    let codex_dir = crate::services::codex_proxy::default_codex_dir()
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
    }

    #[test]
    fn template_for_url_matches_minimax_domains() {
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
    fn deepseek_and_mimo_templates_advertise_image_input() {
        // Both vendors ship vision-capable models now; the capability template
        // declares image input at the VENDOR level on purpose so Codex permits
        // attachments in the composer for every model of the family — we never
        // differentiate per model (that list would churn with each release).
        for template in [DEEPSEEK_TEMPLATE, MIMO_TEMPLATE] {
            let v: Value = serde_json::from_str(template).unwrap();
            let modalities = v
                .get("input_modalities")
                .and_then(|x| x.as_array())
                .expect("template must declare input_modalities");
            assert!(
                modalities.iter().any(|m| m.as_str() == Some("image")),
                "template must advertise image input"
            );
            assert_eq!(
                v.get("supports_image_detail_original")
                    .and_then(|x| x.as_bool()),
                Some(true),
                "template must allow original-resolution image detail"
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