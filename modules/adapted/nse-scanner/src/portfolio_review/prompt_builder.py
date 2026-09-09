from __future__ import annotations

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


"""Create deterministic, evidence-bound prompts for portfolio reviews."""


import json
from datetime import date
from typing import Any

PROMPT_VERSION = "portfolio_review_v1"


def build_review_prompt(evidence: dict[str, Any], review_period: str) -> str:
    symbol = str(evidence.get("symbol", "")).upper()
    schema_outline = {
        "symbol": symbol,
        "review_date": date.today().isoformat(),
        "review_period": review_period,
        "technical_status": "BULLISH|NEUTRAL|WEAK|BROKEN",
        "fundamental_status": "HEALTHY|STABLE|WATCH|CONCERN|NOT_REVIEWED",
        "management_status": "POSITIVE|STABLE|WATCH|CONCERN|UNKNOWN",
        "risk_status": "LOW|MEDIUM|HIGH|UNKNOWN",
        "suggested_action": "HOLD|WATCH|REVIEW|REDUCE|TECHNICAL_EXIT|INSUFFICIENT_DATA",
        "material_change": False,
        "confidence_score": 0,
        "summary": "string",
        "key_positives": [],
        "key_concerns": [],
        "evidence_status": evidence.get("evidence_status", "FAILED"),
        "data_limitations": evidence.get("data_limitations", []),
    }

    return f"""You are reviewing an existing NSE portfolio position.

Use only the supplied evidence. Do not use memory, unstated assumptions, or invented data.
Do not invent ROCE, EPS growth, debt, cash flow, promoter holding, promoter pledge,
valuation, management quality, news, or corporate events.

Mandatory restrictions:
1. When verified fundamental evidence is absent, set fundamental_status to NOT_REVIEWED.
2. When verified management evidence is absent, set management_status to UNKNOWN.
3. A technical-only review cannot claim that fundamentals are healthy or stable.
4. Do not issue an unconditional buy or sell instruction.
5. Return one JSON object only. Do not add Markdown or commentary.
6. Use exactly the controlled values shown in the output contract.

OUTPUT CONTRACT:
{json.dumps(schema_outline, indent=2, ensure_ascii=False)}

SUPPLIED EVIDENCE:
{json.dumps(evidence, indent=2, ensure_ascii=False, default=str)}
"""
