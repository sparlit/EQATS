# -*- coding: utf-8 -*-
"""Vision fallback for BSE result numbers: when OCR fails on a scanned filing, render its P&L pages and
ask the Anthropic vision API to read them. This is what makes "every declared result eventually has
values" work UNATTENDED in CI — GitHub Actions has no Claude, so the grind calls the API directly.

Requires ANTHROPIC_API_KEY in the environment (a repo secret in CI). Cost is a few cents per company
(Haiku 4.5 vision). Returns None when the key is absent, so the grind degrades gracefully to OCR-only.

Public: vision_extract(name, pngs) -> {"jun2026":{"rev","pat"},"jun2025":{"rev","pat"},"ok","basis"} | None
"""
import os, base64, json

_MODEL = os.environ.get("BSE_VISION_MODEL", "claude-haiku-4-5")   # vision-capable, cheap
_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "ok": {"type": "boolean"},
        "basis": {"type": "string", "enum": ["C", "S"]},
        "jun2026": {"type": "object", "additionalProperties": False,
                    "properties": {"rev": {"type": ["number", "null"]}, "pat": {"type": ["number", "null"]}},
                    "required": ["rev", "pat"]},
        "jun2025": {"type": "object", "additionalProperties": False,
                    "properties": {"rev": {"type": ["number", "null"]}, "pat": {"type": ["number", "null"]}},
                    "required": ["rev", "pat"]},
    },
    "required": ["ok", "basis", "jun2026", "jun2025"],
}
_PROMPT = (
    "These images are a BSE-listed company's own quarterly result filing (scanned — OCR fails, so READ "
    "the image). Company: %s.\nExtract, in ₹ CRORE, for the quarter ended 30 June 2026 (Q1 FY27) and the "
    "year-ago quarter ended 30 June 2025:\n- Revenue from Operations (use Total Income only if 'from "
    "operations' isn't shown)\n- Profit After Tax / Profit for the period.\nMind the unit note: 'in Lakhs' "
    "→ divide by 100; 'in Thousands' → /1e5; absolute ₹ → /1e7; 'in Crores' → keep. Prefer CONSOLIDATED if "
    "both shown. If the images are a different company or you can't find the P&L, set ok=false and null the "
    "figures. Return ONLY the JSON object."
)

def _client():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
        return anthropic.Anthropic()
    except Exception:
        return None

def vision_extract(name, pngs):
    """pngs: list of PNG byte strings (P&L pages). Returns the parsed dict, or None if unavailable/failed."""
    cli = _client()
    if not cli or not pngs:
        return None
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
               "data": base64.standard_b64encode(p).decode()}} for p in pngs[:5]]
    content.append({"type": "text", "text": _PROMPT % name})
    try:
        resp = cli.messages.create(
            model=_MODEL, max_tokens=1024,
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
            messages=[{"role": "user", "content": content}],
        )
        txt = next((b.text for b in resp.content if b.type == "text"), None)
        return json.loads(txt) if txt else None
    except Exception as ex:
        print("    vision-api err:", str(ex)[:80])
        return None
