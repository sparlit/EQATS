"""
AXIOM AI Brain — powered by Groq.
Get your free API key at: https://console.groq.com

Model is overridable via the GROQ_MODEL env var, so deprecations (e.g. Groq
retiring older models) are a config change, not a code edit. Default is the
current Llama 3.3 70B; Groq's recommended lighter model is "openai/gpt-oss-20b".
"""
from __future__ import annotations

import os
from typing import Any

import requests
from dotenv import load_dotenv
load_dotenv()
from loguru import logger

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")


def _payload_extras(max_tokens: int) -> dict:
    """Model-specific request tweaks. gpt-oss models are reasoning models on
    Groq: thinking consumes the completion budget, so cap reasoning effort low
    and give the budget headroom — otherwise small-token JSON calls come back
    empty/truncated."""
    if "gpt-oss" in GROQ_MODEL:
        return {"reasoning_effort": "low", "max_tokens": max(max_tokens, 700)}
    return {"max_tokens": max_tokens}

_AXIOM_SYSTEM = (
    "You are AXIOM — Advanced eXpert Intelligence for Operations in Market. "
    "You analyse NSE markets with institutional precision. "
    "Tone: direct, analytical, no fluff. Think like a hedge fund PM."
)


def call_groq_stream(system: str, user: str, max_tokens: int = 900):
    """Yield Groq response tokens as they arrive (Server-Sent Events)."""
    import json as _json
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        yield ""
        return
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.4, "stream": True, **_payload_extras(max_tokens),
    }
    try:
        with requests.post(GROQ_API_URL, headers=headers, json=payload, stream=True, timeout=60) as r:
            if r.status_code != 200:
                logger.error("Groq stream error {}: {}", r.status_code, r.text[:160])
                yield ""
                return
            for raw in r.iter_lines():
                if not raw or not raw.startswith(b"data: "):
                    continue
                data = raw[6:]
                if data == b"[DONE]":
                    break
                try:
                    delta = _json.loads(data)["choices"][0]["delta"].get("content", "")
                    if delta:
                        yield delta
                except Exception:
                    continue
    except Exception as exc:
        logger.exception("Groq stream failed: {}", exc)
        yield ""


def _call_groq(system: str, user: str, max_tokens: int = 1024) -> str:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        logger.error("GROQ_API_KEY not set in .env — visit console.groq.com to get a free key")
        return ""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.4,
        **_payload_extras(max_tokens),
    }
    try:
        response = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=45)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"].strip()
        logger.error("Groq API error {}: {}", response.status_code, response.text[:200])
        return ""
    except requests.exceptions.Timeout:
        logger.error("Groq API timed out after 45s")
        return ""
    except Exception as exc:
        logger.exception("Groq API call failed: {}", exc)
        return ""


_BRIEFING_SYSTEM = (
    "You are AXIOM, Chief Market Strategist for Neura Capital — an institutional "
    "desk trading NSE equities (swing + intraday). You write the morning pre-market "
    "briefing read by portfolio managers and traders. Your standard is a Goldman/Morgan "
    "Stanley morning note: dense, quantitative, cross-asset, and decisive. "
    "Rules: (1) Cite actual numbers from the data — index levels, % moves, yields, pivots. "
    "(2) Connect overnight global flow to expected NSE open and intraday bias. "
    "(3) NEVER fabricate FII/DII figures or economic-calendar events if not in the data — "
    "instead write 'confirm manually'. (4) Be direct and actionable. No hedging, no filler."
)


def generate_market_briefing(context: dict[str, Any]) -> str:
    """Generate an institutional-grade cross-asset pre-market briefing."""
    user = (
        "Write the INSTITUTIONAL MORNING BRIEFING for an NSE swing/intraday desk using "
        "the cross-asset data below. Be quantitative — quote real levels and % moves.\n\n"
        f"=== MARKET DATA ===\n{context}\n\n"
        "=== REQUIRED STRUCTURE ===\n\n"
        "**1. EXECUTIVE SUMMARY** — 3 sentences: overnight tape, the single most important "
        "driver, and the net read for Nifty's open (gap up/down/flat + bias).\n\n"
        "**2. GLOBAL & OVERNIGHT TAPE**\n"
        "   • US Close: S&P/Dow/Nasdaq/Russell with % moves; what led/lagged; VIX level & direction.\n"
        "   • US Futures: current direction = the freshest read on risk appetite.\n"
        "   • Asia-Pacific (trading now): Nikkei/Hang Seng/Shanghai/Kospi — the live morning cue.\n"
        "   • Europe (prior close): FTSE/DAX/CAC tone.\n"
        "   • Net global risk tone (RISK-ON/OFF/MIXED) and WHY.\n\n"
        "**3. RATES, DOLLAR & FX** — US 10Y/2Y yields (level + move), Dollar Index, USD/INR. "
        "Explain the read-through for FII flows and rate-sensitive sectors (IT, Banks, Realty).\n\n"
        "**4. COMMODITIES & CRYPTO** — Brent/WTI (Energy, OMCs, paint/aviation margins), Gold/Silver "
        "(risk hedge), Copper (global growth), Bitcoin (risk sentiment). Tie each to NSE sectors.\n\n"
        "**5. NIFTY 50 — TECHNICAL MAP** — Spot vs EMA20/50/200; RSI & ADX (trend strength); "
        "52w context. State KEY LEVELS explicitly using the pivot data: Resistance R1/R2, "
        "Support S1/S2, and the day's pivot. Give the intraday bias and the level that flips it.\n\n"
        "**6. BANK NIFTY — TECHNICAL MAP** — Same treatment; note if it confirms or diverges from Nifty.\n\n"
        "**7. SECTOR ROTATION** — Top 3 strong vs bottom 3 weak sectors with % moves. Where is money "
        "rotating? Which sector setups deserve focus today.\n\n"
        "**8. INSTITUTIONAL FLOWS (FII/DII)** — Use the real NSE figures in fii_dii (₹ crore). "
        "Quote FII net and DII net for the date shown, state who was net buyer vs seller, and "
        "interpret: are domestics absorbing foreign selling? Tie to USD/INR + yields. "
        "If fii_dii.available is False, state 'FII/DII: confirm manually pre-open' and infer "
        "likely positioning from USD/INR + yields + global tone.\n\n"
        "**9. KEY RISK EVENTS** — Only list events present in the data; otherwise write "
        "'Check economic calendar manually (RBI, US data, earnings, expiry).'\n\n"
        "**10. AXIOM VERDICT** — Net bias (BULLISH/BEARISH/NEUTRAL), conviction (1-10), the ONE "
        "trade-defining level to watch, and position-sizing posture (full/half/cash) per regime.\n\n"
        "Tone: institutional, dense, decisive. Use the real numbers."
    )
    result = _call_groq(_BRIEFING_SYSTEM, user, max_tokens=2200)
    if not result:
        return (
            f"MARKET BRIEFING — {context.get('date', 'Today')}\n\n"
            f"Global risk tone: {context.get('global_risk_tone', 'N/A')}\n\n"
            "AI briefing unavailable. Add GROQ_API_KEY to .env (free at console.groq.com)."
        )
    return result


def generate_screener_commentary(candidates: list[dict[str, Any]]) -> str:
    """Generate analyst commentary for the top screener candidates."""
    if not candidates:
        return "No screener candidates to analyse."
    user = (
        f"Analyse these NSE screener candidates and write 2-3 sentences per stock.\n"
        f"For each: entry level, setup strength, key risk.\n"
        f"Candidates: {candidates[:10]}\n"
        "Format: SYMBOL — commentary. Grade A setups first."
    )
    result = _call_groq(_AXIOM_SYSTEM, user, max_tokens=600)
    if not result:
        return "\n".join(
            [f"{c.get('symbol', '?')}: Score {c.get('score', '?')}" for c in candidates[:5]]
        )
    return result


def generate_trade_journal_summary(trades: list[dict[str, Any]]) -> str:
    """Generate a performance review from recent trade history."""
    if not trades:
        return "No trades in journal."
    user = (
        f"Review these {len(trades)} trades as a hedge fund risk manager.\n"
        "Identify:\n"
        "1. Win rate by setup type\n"
        "2. Best performing day of week\n"
        "3. Avg R:R planned vs achieved\n"
        "4. Top behavioural pattern hurting performance\n"
        "5. One specific improvement for next week\n"
        f"Trades: {trades[:30]}\n"
        "Be direct. No generic advice."
    )
    result = _call_groq(_AXIOM_SYSTEM, user, max_tokens=500)
    if not result:
        pnl = sum(t.get("pnl", 0) for t in trades)
        return f"Total trades: {len(trades)} | Total P&L: ₹{pnl:,.0f}"
    return result


def generate_task_list(context: dict[str, Any]) -> str:
    """Generate a pre/post-market task checklist based on current context."""
    user = (
        f"Generate a personalised NSE trading task checklist based on this context:\n"
        f"{context}\n\n"
        "Include PRE-MARKET (8:45 AM) and POST-MARKET (3:35 PM) sections.\n"
        "Be specific to open positions, watchlist, and regime. Max 10 items total."
    )
    result = _call_groq(_AXIOM_SYSTEM, user, max_tokens=400)
    if not result:
        return (
            "PRE-MARKET\n"
            "☐ Review global cues\n"
            "☐ Check open position gaps\n"
            "☐ Verify watchlist levels\n\n"
            "POST-MARKET\n"
            "☐ Log all trades\n"
            "☐ Review execution quality\n"
            "☐ Update watchlist"
        )
    return result


def generate_stock_analysis(symbol: str, data: dict[str, Any]) -> str:
    """Generate a full 8-section stock analysis in CLAUDE.md format."""
    user = (
        f"Perform a complete 8-section technical analysis for {symbol}.\n"
        f"Data: {data}\n\n"
        "Use the standard format:\n"
        "1. MARKET REGIME\n2. SECTOR RS\n3. TECHNICAL STRUCTURE\n"
        "4. INDICATOR CONFLUENCE\n5. SETUP QUALITY\n6. SCENARIOS\n"
        "7. RISK PLAN\n8. PSYCHOLOGICAL CHECK\n9. FINAL VERDICT\n"
        "Include specific price levels, R:R, and position size using 2% capital rule."
    )
    result = _call_groq(_AXIOM_SYSTEM, user, max_tokens=1200)
    if not result:
        return f"AXIOM analysis for {symbol} unavailable. Check GROQ_API_KEY in .env."
    return result


def generate_commentary(text: str) -> str:
    """Generate a short commentary on any provided text or data."""
    result = _call_groq(_AXIOM_SYSTEM, text, max_tokens=300)
    return result or "Commentary unavailable."
