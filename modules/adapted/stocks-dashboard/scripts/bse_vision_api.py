import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


# -*- coding: utf-8 -*-
"""Vision fallback for BSE result numbers: when OCR fails on a scanned filing, render its P&L pages and
ask the Anthropic vision API to read them. This is what makes "every declared result eventually has
values" work UNATTENDED in CI — GitHub Actions has no Claude, so the grind calls the API directly.

Requires ANTHROPIC_API_KEY in the environment (a repo secret in CI). Cost is a few cents per company
(Haiku 4.5 vision). Returns None when the key is absent, so the grind degrades gracefully to OCR-only.

Public: vision_extract(name, pngs) -> {"jun2026":{"rev","pat"},"jun2025":{"rev","pat"},"ok","basis"} | None
"""
import base64
import json
import os

_MODEL = os.environ.get("BSE_VISION_MODEL", "claude-haiku-4-5")  # vision-capable, cheap
_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "ok": {"type": "boolean"},
        "basis": {"type": "string", "enum": ["C", "S"]},
        "jun2026": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"rev": {"type": ["number", "null"]}, "pat": {"type": ["number", "null"]}},
            "required": ["rev", "pat"],
        },
        "jun2025": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"rev": {"type": ["number", "null"]}, "pat": {"type": ["number", "null"]}},
            "required": ["rev", "pat"],
        },
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
    content = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": base64.standard_b64encode(p).decode()},
        }
        for p in pngs[:5]
    ]
    content.append({"type": "text", "text": _PROMPT % name})
    try:
        resp = cli.messages.create(
            model=_MODEL,
            max_tokens=1024,
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
            messages=[{"role": "user", "content": content}],
        )
        txt = next((b.text for b in resp.content if b.type == "text"), None)
        return json.loads(txt) if txt else None
    except Exception as ex:
        print("    vision-api err:", str(ex)[:80])
        return None


# --- HISTORICAL reader: read EVERY period column the P&L prints (one filing → several quarters via
#     its comparatives), values AS PRINTED + the statement unit so the caller converts deterministically.
#     Used by backfill_bse_fund_history.py to deepen bse_fundamentals.json toward 2020. ----------------
_SCHEMA_PERIODS = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "ok": {"type": "boolean"},
        "basis": {"type": "string", "enum": ["C", "S"]},
        "unit": {"type": "string", "enum": ["crore", "lakh", "million", "thousand", "absolute"]},
        "periods": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "end": {"type": "string"},  # period-end, YYYY-MM-DD
                    "kind": {"type": "string", "enum": ["Q", "Y"]},  # quarter column vs full-year column
                    "rev": {"type": ["number", "null"]},
                    "pat": {"type": ["number", "null"]},
                },
                "required": ["end", "kind", "rev", "pat"],
            },
        },
    },
    "required": ["ok", "basis", "unit", "periods"],
}
_PROMPT_PERIODS = (
    "These images are a BSE-listed company's own result filing (often SCANNED — OCR fails, so READ the "
    "image). Company: %s.\nThe profit-and-loss statement shows SEVERAL period columns (quarter-ended "
    "and/or year-ended). For EVERY column, return one object with:\n- end: the column's period-end date "
    "as YYYY-MM-DD\n- kind: 'Q' if it is a quarter column, 'Y' if it is a full-year / 'year ended' column\n"
    "- rev: Revenue from Operations (use Total Income only if a 'from operations' line isn't shown)\n"
    "- pat: Profit After Tax / Profit for the period (AFTER tax, before other comprehensive income).\n"
    "Report rev and pat EXACTLY AS PRINTED (do NOT convert units; a value in brackets is negative), and "
    "set `unit` to the statement's unit note: 'in Lakhs'→lakh, 'in Millions'→million, 'in Thousands'→"
    "thousand, 'in Crores'→crore, plain rupees→absolute.\nbasis='C' if these are Consolidated results, "
    "else 'S'. If the images are a different company or you can't find the P&L, set ok=false and periods=[]. "
    "Return ONLY the JSON object."
)


def vision_extract_periods(name, pngs):
    """Read every period the P&L prints. Returns {ok, basis, unit, periods:[{end,kind,rev,pat}]} or None."""
    cli = _client()
    if not cli or not pngs:
        return None
    content = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": base64.standard_b64encode(p).decode()},
        }
        for p in pngs[:5]
    ]
    content.append({"type": "text", "text": _PROMPT_PERIODS % name})
    try:
        resp = cli.messages.create(
            model=_MODEL,
            max_tokens=1536,
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA_PERIODS}},
            messages=[{"role": "user", "content": content}],
        )
        txt = next((b.text for b in resp.content if b.type == "text"), None)
        return json.loads(txt) if txt else None
    except Exception as ex:
        print("    vision-periods err:", str(ex)[:80])
        return None
