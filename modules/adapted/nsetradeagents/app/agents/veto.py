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


import json
from datetime import date

import structlog
from app.core.config import settings
from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_tavily import TavilySearch
from pydantic import BaseModel, Field

logger = structlog.get_logger()

KILL_REASONS = (
    "EARNINGS_IMMINENT",
    "ADVERSE_NEWS",
    "SUPPLY_OVERHANG",
    "NEWS_ALREADY_PRICED",
    "PENDING_EVENT",
)

# LangGraph counts supersteps, not tool calls: roughly two per search (a model
# turn and a tool turn), plus a final turn to produce the verdict. Hitting the
# limit raises, which fails open to PASS — so the prompt caps searches too, and
# this is only a backstop.
MAX_SEARCHES = 8
RECURSION_LIMIT = MAX_SEARCHES * 2 + 4

# Search results are bulky and mostly boilerplate; what the agent made of them
# is the part worth keeping. The overall cap bounds a runaway loop.
MAX_TOOL_CHARS = 1500
MAX_TRANSCRIPT_CHARS = 20000


def _render(messages: list) -> str:
    """Flatten the agent's messages into readable text for later review."""
    parts: list[str] = []

    for m in messages:
        kind = m.__class__.__name__

        if kind == "HumanMessage":
            parts.append(f"[prompt]\n{m.content}")

        elif kind == "AIMessage":
            if isinstance(m.content, str):
                if m.content.strip():
                    parts.append(f"[assistant]\n{m.content}")
            else:
                for block in m.content:
                    btype = block.get("type")
                    if btype == "thinking":
                        parts.append(f"[thinking]\n{block.get('thinking', '')}")
                    elif btype == "text":
                        parts.append(f"[assistant]\n{block.get('text', '')}")
                    elif btype == "tool_use":
                        parts.append(f"[search] {json.dumps(block.get('input', {}))}")

        elif kind == "ToolMessage":
            parts.append(f"[results]\n{str(m.content)[:MAX_TOOL_CHARS]}")

    return "\n\n".join(parts)[:MAX_TRANSCRIPT_CHARS]


class VetoVerdict(BaseModel):
    verdict: str = Field(description="KILL or PASS")
    reason: str | None = Field(description=f"One of {', '.join(KILL_REASONS)}. Null when PASS.")
    cited_fact: str | None = Field(
        default=None,
        description="The specific, checkable fact behind a KILL - a date, a filing, a named event. Null when PASS",
    )
    source_url: str | None = Field(
        default=None,
        description="The page the cited fact came from. Null when PASS.",
    )
    checked: str = Field(description="One line listing what was actually searched and found, for both KILL and PASS")


SYSTEM_PROMPT = """You are the final check before an automated system buys an Indian
smallcap or midcap stock for a 1-4 week hold.

A deterministic screener has already decided this setup looks good on price and volume.
Your job is NOT to agree with it. Your job is to find the specific thing that kills it.

Search for evidence, then answer: is there a concrete, checkable reason not to buy today?

You may only KILL for one of these five reasons:

- EARNINGS_IMMINENT: Results or a board meeting within about 3 trading days. Holding a
momentum trade through results is a coin flip.
- ADVERSE_NEWS: SEBI/ED/tax action, auditor resignation or qualified accounts, fraud
allegation or short-seller report, guidance cut, large order or client lost, CEO/CFO
departure, credit downgrade, plant accident or recall.
- SUPPLY_OVERHANG: Promoter selling or increased pledging, a large block or bulk deal,
an announced QIP, OFS or preferential allotment. Someone is selling into the buy.
- NEWS_ALREADY_PRICED: The price jump being bought was itself the reaction to news that is
now public and absorbed. The move has already happened.
- PENDING_EVENT: An unscheduled binary event is close — an awaited court verdict, a
regulatory decision, a board meeting on a fundraise.

Anything else is a PASS. In particular, do NOT kill for:
- general market or sector weakness (already scored separately)
- the stock having risen a lot (already scored separately)
- vague sentiment, opinion pieces, or analyst price-target changes
- old news that is more than about a month old and already reflected

HOW TO SEARCH
Search deliberately, not once, but budget yourself: make at most 8 searches in
total, then decide with what you have. Running out of searches without a verdict
is worse than a well-reasoned PASS. Cover the reasons above with separate queries, and adapt
to the sector - pharma needs USFDA and ANDA news, banks need NPAs and RBI actions, metals
and energy need commodity prices, IT needs client wins and guidance.

RULES
- Every KILL must cite a fact someone could verify in a month: a date, a filing, a named
event. "Sentiment is weak" is not a fact. "Q2 results on 14 Aug" is.
- If you cannot find a specific fact, PASS. A PASS is the correct default.
- Always fill `checked` with what you actually looked at, for both verdicts.
- Today's date matters for judging whether news is recent. It is given in the message.
"""


_AGENT = None


def _agent():
    """Build the agent once, on first use.

    Deferred rather than built at import time so a missing API key doesn't
    break every import of this module, including in tests.
    """
    global _AGENT
    if _AGENT is None:
        _AGENT = _build_agent()
    return _AGENT


def _build_agent():
    llm = ChatAnthropic(
        # No temperature: current models reject sampling parameters.
        # max_tokens caps thinking *and* the response together, so leave headroom.
        model=settings.llm_model_veto,
        max_tokens=8000,
        api_key=settings.anthropic_api_key,
        # Caches the growing message history, not just the system prompt: each
        # turn's accumulated tool results are read back at ~0.1x on the next.
        model_kwargs={"cache_control": {"type": "ephemeral"}},
    )
    search = TavilySearch(
        max_results=4,
        search_depth="advanced",
        topic="news",
        tavily_api_key=settings.tavily_api_key,
    )
    _SYSTEM = SystemMessage(
        content=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    )
    return create_agent(llm, [search], system_prompt=_SYSTEM, response_format=VetoVerdict)


def run_veto(
    ticker: str,
    company_name: str,
    sector: str,
    current_price: float,
    day_change_pct: float,
    as_of: date,
) -> dict:
    """Look for a specific reason not to buy a candidate that already passed scoring.

    Returns {verdict, reason, cited_fact, source_url, checked}. Fails open: any
    error returns PASS, because the deterministic pipeline is the validated
    system and an outage must not stop it trading."""
    logger.info("veto_start", ticker=ticker)
    symbol = ticker.replace(".NS", "")

    prompt = f"""Today is {as_of:%d %B %Y}.

Candidate: {company_name} ({symbol}), {sector} sector, NSE.
Price Rs.{current_price}, up {day_change_pct}% today.

The screener picked this for a volume-backed move. Find the specific thing that kills this setup."""

    try:
        result = _agent().invoke(
            {"messages": [HumanMessage(content=prompt)]},
            config={"recursion_limit": RECURSION_LIMIT},
        )
        v: VetoVerdict = result["structured_response"]
        verdict = v.verdict.upper()

        transcript = _render(result.get("messages") or [])

        if verdict != "KILL" or v.reason not in KILL_REASONS:
            return {
                "verdict": "PASS",
                "reason": None,
                "cited_fact": None,
                "source_url": None,
                "checked": v.checked,
                "transcript": transcript,
                "model": settings.llm_model_veto,
            }
        logger.info("veto_kill", ticker=ticker, reason=v.reason, fact=v.cited_fact)
        return {
            "verdict": "KILL",
            "reason": v.reason,
            "cited_fact": v.cited_fact,
            "source_url": v.source_url,
            "checked": v.checked,
            "transcript": transcript,
            "model": settings.llm_model_veto,
        }

    except Exception as e:
        logger.exception("veto_failed", ticker=ticker, error=str(e))
        return {
            "verdict": "PASS",
            "reason": None,
            "cited_fact": None,
            "source_url": None,
            "checked": f"error: {e}",
            "transcript": None,
            "model": settings.llm_model_veto,
        }
