"""
AI news-sentiment — scores the live headline feed bullish/bearish for Indian
equities (via Groq) into a market meter + per-stock tags. Turns the news column
into signal. Reuses data.news_feed + ai.brain.
"""
from __future__ import annotations

import json
import re

from loguru import logger

_SYS = (
    "You are a markets sentiment classifier for NSE / Indian equities. For each "
    "numbered headline judge its likely short-term impact on the relevant stock or "
    "the broader Indian market: bullish, bearish, or neutral. Be strict — routine/"
    "factual headlines are neutral."
)
_JSON = re.compile(r"\[.*\]", re.DOTALL)


def analyze_news_sentiment(limit: int = 40) -> dict:
    from ai.brain import _call_groq
    from data.news_feed import fetch_market_news

    try:
        items = fetch_market_news()[:limit]
    except Exception as exc:
        logger.warning("sentiment news fetch failed: {}", exc)
        items = []
    if not items:
        return {"available": False, "headlines": [], "by_symbol": {},
                "market": {"score": 0, "label": "No data", "bull": 0, "bear": 0, "neutral": 0}}

    numbered = "\n".join(f"{i}. {it.get('title', '')}" for i, it in enumerate(items))
    user = (
        "Classify each headline. Output ONLY a JSON array — one object per headline:\n"
        '{"i": <index>, "s": "bull"|"bear"|"neutral", "t": [NSE stock symbols mentioned, '
        "uppercase, no .NS suffix; [] if none]}\n\nHeadlines:\n" + numbered
    )
    raw = _call_groq(_SYS, user, max_tokens=1600).strip()
    m = _JSON.search(raw)
    try:
        arr = json.loads(m.group(0)) if m else []
    except Exception as exc:
        logger.warning("sentiment parse failed: {}", exc)
        arr = []

    by_i = {int(o.get("i", -1)): o for o in arr if isinstance(o, dict)}
    headlines, counts = [], {"bull": 0, "bear": 0, "neutral": 0}
    by_symbol: dict[str, dict] = {}
    for i, it in enumerate(items):
        o = by_i.get(i, {})
        s = o.get("s") if o.get("s") in ("bull", "bear", "neutral") else "neutral"
        counts[s] += 1
        tickers = [str(t).upper().replace(".NS", "") for t in (o.get("t") or []) if t]
        headlines.append({"title": it.get("title", ""), "link": it.get("link", ""),
                          "source": it.get("source", ""), "published_str": it.get("published_str", ""),
                          "sentiment": s, "tickers": tickers})
        for tk in tickers:
            slot = by_symbol.setdefault(tk, {"bull": 0, "bear": 0, "neutral": 0})
            slot[s] += 1

    total = max(len(items), 1)
    score = round((counts["bull"] - counts["bear"]) / total * 100)
    label = "Bullish" if score >= 15 else "Bearish" if score <= -15 else "Neutral"
    sym_out = {k: {"score": v["bull"] - v["bear"], "n": v["bull"] + v["bear"] + v["neutral"],
                   "label": "bull" if v["bull"] > v["bear"] else "bear" if v["bear"] > v["bull"] else "neutral"}
               for k, v in by_symbol.items()}
    return {"available": True, "headlines": headlines, "by_symbol": sym_out,
            "market": {"score": score, "label": label, **counts}}
