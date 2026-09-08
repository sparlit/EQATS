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


"""Tests for the forensic veto agent.

The LLM and search tool are stubbed throughout, so these cover the code around
the agent — verdict parsing, enforcement of the closed reason list, the prompt
handed to the model, and the fail-open path — without any API calls.
"""

from datetime import date
from unittest.mock import patch

import pytest
from app.agents import veto
from app.agents.veto import KILL_REASONS, VetoVerdict, run_veto
from app.core.config import settings
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

TODAY = date(2026, 8, 16)


class StubAgent:
    """Returns a canned verdict and records what it was asked."""

    def __init__(self, verdict: VetoVerdict, messages: list | None = None):
        self._verdict = verdict
        self._messages = messages or []
        self.payload = None
        self.config = None

    def invoke(self, payload, config=None):
        self.payload = payload
        self.config = config
        return {"structured_response": self._verdict, "messages": self._messages}


class ExplodingAgent:
    def __init__(self, exc: Exception):
        self._exc = exc

    def invoke(self, payload, config=None):
        raise self._exc


def verdict(**overrides) -> VetoVerdict:
    base = {
        "verdict": "KILL",
        "reason": "SUPPLY_OVERHANG",
        "cited_fact": "Promoters sold 1.77% on 14 Aug 2026",
        "source_url": "https://example.com/bulk-deals",
        "checked": "results date, promoter deals, SEBI, QIP, pending events",
    }
    return VetoVerdict(**{**base, **overrides})


def call(agent, **overrides):
    kwargs = {
        "ticker": "MENONBE.NS",
        "company_name": "Menon Bearings Ltd",
        "sector": "Auto Components",
        "current_price": 229.68,
        "day_change_pct": 3.6,
        "as_of": TODAY,
    }
    kwargs.update(overrides)
    with patch.object(veto, "_agent", lambda: agent):
        return run_veto(**kwargs)


@pytest.fixture(autouse=True)
def reset_agent_singleton():
    veto._AGENT = None
    yield
    veto._AGENT = None


# ── verdicts ─────────────────────────────────────────────────────────────────


def test_kill_passes_every_field_through():
    """Exact equality on purpose: a key added or dropped here changes what the
    decision record stores, and main.py reads this dict by name."""
    r = call(StubAgent(verdict()))
    assert r == {
        "verdict": "KILL",
        "reason": "SUPPLY_OVERHANG",
        "cited_fact": "Promoters sold 1.77% on 14 Aug 2026",
        "source_url": "https://example.com/bulk-deals",
        "checked": "results date, promoter deals, SEBI, QIP, pending events",
        "transcript": "",
        "model": settings.llm_model_veto,
    }


def test_pass_nulls_the_kill_fields_but_keeps_checked():
    """A PASS must not carry a stray reason or fact from the model."""
    r = call(StubAgent(verdict(verdict="PASS", checked="searched five categories")))
    assert r["verdict"] == "PASS"
    assert r["reason"] is None
    assert r["cited_fact"] is None
    assert r["source_url"] is None
    assert r["checked"] == "searched five categories"


def test_verdict_is_case_insensitive():
    assert call(StubAgent(verdict(verdict="kill")))["verdict"] == "KILL"


# ── the closed reason list is enforced in code, not just the prompt ──────────


@pytest.mark.parametrize(
    "bad_reason",
    ["MARKET_WEAKNESS", "OVEREXTENDED", "sentiment", "", "supply_overhang"],
)
def test_kill_with_a_reason_outside_the_list_becomes_a_pass(bad_reason):
    """The model cannot invent a kill reason — including by changing its case."""
    r = call(StubAgent(verdict(reason=bad_reason)))
    assert r["verdict"] == "PASS"
    assert r["reason"] is None


def test_kill_without_a_reason_becomes_a_pass():
    r = call(StubAgent(verdict(reason=None)))
    assert r["verdict"] == "PASS"


@pytest.mark.parametrize("reason", KILL_REASONS)
def test_every_documented_reason_is_accepted(reason):
    r = call(StubAgent(verdict(reason=reason)))
    assert r["verdict"] == "KILL"
    assert r["reason"] == reason


# ── fail open ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("recursion limit reached"),
        AttributeError("'Settings' object has no attribute 'antropic_api_key'"),
        TimeoutError("tavily timed out"),
    ],
)
def test_any_failure_passes_rather_than_blocking(exc):
    """An outage must degrade to the deterministic system, never halt trading."""
    r = call(ExplodingAgent(exc))
    assert r["verdict"] == "PASS"
    assert r["reason"] is None


def test_the_failure_is_recorded_in_checked():
    """Fail-open makes a broken veto look identical to a lenient one, so the
    error has to survive into the record or the outage is invisible."""
    r = call(ExplodingAgent(RuntimeError("boom")))
    assert r["checked"].startswith("error:")
    assert "boom" in r["checked"]


# ── what the model is asked ──────────────────────────────────────────────────


def test_prompt_carries_the_details_the_verdict_depends_on():
    agent = StubAgent(verdict())
    call(agent)
    prompt = agent.payload["messages"][0].content

    assert "16 August 2026" in prompt  # recency judgements hinge on this
    assert "Menon Bearings Ltd" in prompt
    assert "MENONBE" in prompt
    assert ".NS" not in prompt
    assert "Auto Components" in prompt
    assert "229.68" in prompt
    assert "3.6" in prompt


def test_search_loop_is_bounded():
    agent = StubAgent(verdict())
    call(agent)
    assert agent.config["recursion_limit"] == veto.RECURSION_LIMIT
    assert veto.RECURSION_LIMIT > veto.MAX_SEARCHES  # room for the verdict turn


# ── construction ─────────────────────────────────────────────────────────────


def test_agent_is_built_once_and_reused():
    """Rebuilding per candidate would recreate the client and tool each time."""
    calls = []

    def fake_build():
        calls.append(1)
        return StubAgent(verdict())

    with patch.object(veto, "_build_agent", fake_build):
        veto._agent()
        veto._agent()
        veto._agent()

    assert len(calls) == 1


def test_system_prompt_is_marked_for_caching():
    """The prompt is resent on every loop iteration; without the breakpoint
    each search re-pays for the full prefix."""
    with (
        patch.object(veto, "ChatAnthropic"),
        patch.object(veto, "TavilySearch"),
        patch.object(veto, "create_agent") as fake_create,
    ):
        veto._build_agent()

    system = fake_create.call_args.kwargs["system_prompt"]
    block = system.content[0]
    assert block["cache_control"] == {"type": "ephemeral"}
    assert block["text"] == veto.SYSTEM_PROMPT


def test_message_history_is_cached_too():
    """Caching the system block alone covers ~900 tokens; the tool results that
    pile up across the ReAct loop are where the cost actually is."""
    with (
        patch.object(veto, "ChatAnthropic") as fake_llm,
        patch.object(veto, "TavilySearch"),
        patch.object(veto, "create_agent"),
    ):
        veto._build_agent()

    kwargs = fake_llm.call_args.kwargs
    assert kwargs["model_kwargs"]["cache_control"] == {"type": "ephemeral"}


def test_no_sampling_parameters_are_sent():
    """Current models reject temperature/top_p/top_k with a 400."""
    with (
        patch.object(veto, "ChatAnthropic") as fake_llm,
        patch.object(veto, "TavilySearch"),
        patch.object(veto, "create_agent"),
    ):
        veto._build_agent()

    kwargs = fake_llm.call_args.kwargs
    assert not {"temperature", "top_p", "top_k"} & kwargs.keys()


def test_prompt_names_every_kill_reason():
    """A reason the prompt never mentions can only ever be rejected in code."""
    for reason in KILL_REASONS:
        assert reason in veto.SYSTEM_PROMPT


# ── the transcript ───────────────────────────────────────────────────────────
#
# Kept so the planned post-mortem analyst can show the agent its own prior
# reasoning next to the outcome. `checked` is the agent's one-line self-report
# of its diligence, which is the least trustworthy field when diagnosing a miss.


def investigation() -> list:
    """A realistic one-search exchange."""
    return [
        HumanMessage(content="Candidate: Menon Bearings (MENONBE), Auto Components"),
        AIMessage(
            content=[
                {"type": "thinking", "thinking": "Check the results calendar first."},
                {
                    "type": "tool_use",
                    "id": "t1",
                    "name": "tavily_search",
                    "input": {"query": "Menon Bearings Q1 results date"},
                },
            ]
        ),
        ToolMessage(content="Results were declared on 12 Aug 2026.", tool_call_id="t1"),
        AIMessage(content="Results are already out. No disqualifying fact."),
    ]


def test_transcript_captures_the_searches_and_the_reasoning():
    r = call(StubAgent(verdict(verdict="PASS"), investigation()))
    t = r["transcript"]

    assert "Menon Bearings Q1 results date" in t  # the query it actually ran
    assert "Check the results calendar first" in t  # why it ran it
    assert "Results were declared on 12 Aug 2026" in t  # what came back
    assert "No disqualifying fact" in t  # what it concluded


def test_transcript_distinguishes_searching_from_not_searching():
    """The whole point: a PASS that checked the calendar and a PASS that never
    looked are the same verdict with the same `checked` line."""
    searched = call(StubAgent(verdict(verdict="PASS"), investigation()))["transcript"]
    never = call(StubAgent(verdict(verdict="PASS"), []))["transcript"]

    assert "[search]" in searched
    assert "[search]" not in never


def test_long_tool_results_are_truncated():
    """An unabridged search dump per query would dominate the row."""
    messages = [ToolMessage(content="x" * 9000, tool_call_id="t1")]

    t = call(StubAgent(verdict(), messages))["transcript"]

    assert "x" * veto.MAX_TOOL_CHARS in t
    assert len(t) < veto.MAX_TOOL_CHARS + 100


def test_the_whole_transcript_is_capped():
    """Bounds a runaway loop, so row size is set here rather than by the agent."""
    messages = [ToolMessage(content="y" * veto.MAX_TOOL_CHARS, tool_call_id=f"t{i}") for i in range(50)]

    t = call(StubAgent(verdict(), messages))["transcript"]

    assert len(t) == veto.MAX_TRANSCRIPT_CHARS


def test_transcript_is_none_when_the_agent_errors():
    """invoke() never returned, so there are no messages to render."""
    assert call(ExplodingAgent(RuntimeError("boom")))["transcript"] is None


@pytest.mark.parametrize(
    "agent",
    [
        StubAgent(verdict()),
        StubAgent(verdict(verdict="PASS")),
        ExplodingAgent(RuntimeError("boom")),
    ],
    ids=["kill", "pass", "error"],
)
def test_the_model_is_recorded_on_every_path(agent):
    """Verdicts from different models are different populations. Without this
    stamped on each row, switching models silently mixes them."""
    assert call(agent)["model"] == settings.llm_model_veto
