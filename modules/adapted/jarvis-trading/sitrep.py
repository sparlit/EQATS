"""
AI Global Situation Report — fuses live global macro (indices/commodities/FX/
crypto), geocoded news hotspots and the latest headlines into a structured
per-region market SITREP with an India-impact read. The "exact position of the
global market" panel on the dashboard.
"""
from __future__ import annotations

import json
import re

from loguru import logger

_SYS = (
    "You are AXIOM's global macro strategist for an NSE swing trader. Given live "
    "market data and headlines, produce a terse situation report. Rules: cite the "
    "actual numbers given, never invent data, be decisive, no filler."
)
_JSON = re.compile(r"\{.*\}", re.DOTALL)

_REGIONS = ["United States", "Europe", "Asia", "India", "Commodities", "Crypto"]


def _fmt_quotes(rows: list[dict]) -> str:
    return ", ".join(f"{r['label']} {r['pct']:+.2f}%" for r in rows if r.get("pct") is not None)


def build_sitrep() -> dict:
    from ai.brain import _call_groq
    from data.global_macro import fetch_global_macro
    from data.news_feed import fetch_market_news
    from data.world_news import geocode_news

    macro = fetch_global_macro()
    if not macro.get("available"):
        return {"available": False, "note": "Global market feed unavailable."}

    try:
        news = fetch_market_news(24)
    except Exception:
        news = []
    try:
        hotspots = geocode_news().get("points", [])[:8]
    except Exception:
        hotspots = []

    facts = (
        f"RISK COMPOSITE: {macro['risk_tone']} {macro['risk_score']}/100.\n"
        f"INDICES: {_fmt_quotes(macro['indices'])}.\n"
        f"COMMODITIES: {_fmt_quotes(macro['commodities'])}.\n"
        f"FX: {_fmt_quotes(macro['fx'])}.\n"
        f"CRYPTO: {_fmt_quotes(macro['crypto'])}.\n"
        f"NEWS HOTSPOTS: {', '.join(p['place'] + ' (' + str(p['count']) + ')' for p in hotspots) or 'none'}.\n"
        "TOP HEADLINES:\n" + "\n".join(f"- [{n['source']}] {n['title'][:110]}" for n in news[:16])
    )
    user = (
        "Produce the SITREP as ONLY a JSON object:\n"
        '{"overall": "<2-sentence global read citing numbers>", '
        '"regions": [{"region": "<one of: United States, Europe, Asia, India, Commodities, Crypto>", '
        '"stance": "risk-on"|"risk-off"|"mixed", "note": "<1 sentence citing data/headline>"}], '
        '"india_impact": "<1-2 sentences: what this means for NSE traders today>"}\n'
        "Cover all six regions.\n\nDATA:\n" + facts
    )
    raw = _call_groq(_SYS, user, max_tokens=1400)
    m = _JSON.search(raw or "")
    try:
        out = json.loads(m.group(0)) if m else {}
    except Exception as exc:
        logger.warning("SITREP parse failed: {}", exc)
        out = {}
    if not out.get("regions"):
        return {"available": False, "note": "AI SITREP unavailable — try again shortly."}

    # keep only known regions, in canonical order
    by_name = {r.get("region"): r for r in out["regions"] if isinstance(r, dict)}
    regions = [by_name[n] for n in _REGIONS if n in by_name] or out["regions"][:6]
    return {
        "available": True,
        "overall": str(out.get("overall", ""))[:500],
        "regions": regions,
        "india_impact": str(out.get("india_impact", ""))[:400],
        "risk_score": macro["risk_score"],
        "risk_tone": macro["risk_tone"],
    }
