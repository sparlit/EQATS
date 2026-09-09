from __future__ import annotations

import datetime
import json
import re

import pytz

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)


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


"""
AI news-sentiment — scores the live headline feed bullish/bearish for Indian
equities (via Groq) into a market meter + per-stock tags. Turns the news column
into signal. Reuses data.news_feed + ai.brain.
"""

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
        return {
            "available": False,
            "headlines": [],
            "by_symbol": {},
            "market": {"score": 0, "label": "No data", "bull": 0, "bear": 0, "neutral": 0},
        }

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
        tickers = [str(t).upper().replace(".NS", "") for t in o.get("t", []) if t]
        headlines.append({"title": it.get("title", ""), "sentiment": s, "tickers": tickers})
        for sym in tickers:
            if sym not in by_symbol:
                by_symbol[sym] = {"bull": 0, "bear": 0, "neutral": 0, "headlines": []}
            by_symbol[sym][s] += 1
            by_symbol[sym]["headlines"].append(it.get("title", ""))

    total = counts["bull"] + counts["bear"] + counts["neutral"]
    score = round((counts["bull"] - counts["bear"]) / total * 100, 1) if total else 0
    label = "Bullish" if score > 20 else "Bearish" if score < -20 else "Neutral"

    return {
        "available": True,
        "headlines": headlines,
        "by_symbol": by_symbol,
        "market": {"score": score, "label": label, **counts},
    }
