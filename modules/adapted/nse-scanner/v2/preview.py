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


"""Telegram market summary, compact ACTION cards and lifecycle-aware WATCH guidance."""

from collections import Counter
from typing import TYPE_CHECKING

from telegram_dashboard import status_icon, status_label

from .v3_telegram import currency, paginate_cards, text, ticker

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .candidates import Candidate
    from .freshness import FreshnessStatus
    from .portfolio_risk import Allocation

HORIZON_LABELS = {"1M": "1 month", "3M": "3 months", "6M": "6 months", "12M": "12 months"}
ACTION_SECTION_LABELS = {
    "1M": "1M SWING — 2 to 6 weeks",
    "3M": "3M POSITIONAL — 1 to 3 months",
    "6M": "6M TREND — 3 to 6 months",
    "12M": "12M COMPOUNDER — 6 to 12 months",
}
TRIGGER_LABELS = {
    "QUALIFIED_PULLBACK": "QUALIFIED PULLBACK",
    "BREAKOUT": "BREAKOUT",
    "COMPRESSION_RELEASE": "COMPRESSION RELEASE",
    "HULL_CROSSOVER": "HYBRID HULL CROSSOVER",
    "RS_ACCELERATION": "RELATIVE-STRENGTH ACCELERATION",
    "TREND_CONTINUATION": "TREND CONTINUATION",
    "REACCUMULATION": "RE-ACCUMULATION",
    "NO_TRIGGER": "NO CURRENT TRIGGER",
}
TIMING_ICON = {
    "EARLY": "🟠",
    "READY": "🟢",
    "HOLD_TREND": "🔵",
    "PULLBACK_REENTRY": "🟣",
    "EXTENDED": "🔴",
    "WEAK": "⚫",
}


def _price(value: float) -> str:
    return currency(value)


def _status(freshness: FreshnessStatus | None) -> str:
    if freshness is None:
        return "Fresh"
    return "Warning — latest data needs review" if freshness.degraded else "Fresh"


def _reason_lines(candidate: Candidate) -> list[str]:
    readable = []
    for reason in candidate.reasons_for:
        text = reason.replace("_", " ").strip().capitalize()
        if text and text not in readable:
            readable.append(text)
    return readable[:5]


def _chunk_cards(cards: list[str], header: str, limit: int = 3800) -> list[str]:
    if not cards:
        return []
    messages, current = [], header
    for card in cards:
        candidate = f"{current}\n\n{card}" if current else card
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                messages.append(current)
            current = f"{header}\n\n{card}"
    if current:
        messages.append(current)
    total = len(messages)
    if total == 1:
        return messages
    return [message.replace(header, f"{header} — {index}/{total}", 1) for index, message in enumerate(messages, 1)]


def _rank_badge(rank: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")


def _timing(candidate: Candidate) -> str:
    return candidate.timing_state or str(candidate.metrics.get("timing_state", "WEAK"))


def _action_card(candidate: Candidate, rank: int, allocations: dict[tuple[str, str], Allocation] | None) -> str:
    del allocations
    trigger = TRIGGER_LABELS.get(candidate.entry_trigger, candidate.entry_trigger.replace("_", " ").upper())
    _timing(candidate)
    route = candidate.entry_route or "FRESH ENTRY"
    htf = candidate.htf_state or "NEUTRAL"
    entry_high = candidate.entry * 1.004
    try:
        cmp_value = float(candidate.metrics.get("close") or candidate.entry)
    except (TypeError, ValueError):
        cmp_value = candidate.entry
    lines = [
        "━━━━━━━━━━━━━━",
        f"{status_icon('READY')} {ticker(candidate.symbol)} • <b>{status_label('READY')} • {candidate.score:.0f}/100</b>",
        f"CMP: {_price(cmp_value)}",
        f"Evidence: {text(candidate.primary_horizon)} {text(trigger.title())} • Weekly HTF {text(htf)}",
        f"Entry: {_price(candidate.entry)}–{_price(entry_high)}",
        f"SL {_price(candidate.stop)} | T1 {_price(candidate.target1)} | T2 {_price(candidate.target2)}",
        f"Context: Route {text(route)} • Risk {candidate.risk_percent:.2f}% • Valid {candidate.valid_for_sessions} sessions",
    ]
    reasons = _reason_lines(candidate)
    if reasons:
        lines.append("")
        lines.extend(f"✅ {text(reason)}" for reason in reasons[:3])
    lines.extend(["Next: The simulated portfolio adds this only after trigger confirmation."])
    return "\n".join(lines)


def _action_messages(action_rows: list[Candidate], allocations: dict[tuple[str, str], Allocation] | None) -> list[str]:
    if not action_rows:
        return []
    cards = [_action_card(candidate, rank, allocations) for rank, candidate in enumerate(action_rows, 1)]
    return paginate_cards(
        "📊 <b>NSE V3 — DAILY WATCHLIST</b>\n<b>ENTRY PLANS • SIMULATED ONLY</b>",
        cards,
        "⚠️ Watchlist output — not an automatic buy order.",
    )


def _watch_reason(candidate: Candidate) -> str:
    timing = _timing(candidate)
    if timing == "EXTENDED":
        return "Strong trend, entry location extended — do not chase"
    if timing == "EARLY":
        return "Early setup — higher timeframe still developing"
    if timing == "PULLBACK_REENTRY":
        return "Pullback / re-entry opportunity developing"
    if candidate.trade_plan_state in {"WAIT", "RISKY"}:
        return f"Trade plan {candidate.trade_plan_state.lower()}"
    if candidate.entry_trigger == "NO_TRIGGER":
        return "No actionable trigger"
    if candidate.pullback_state == "DEEP_PULLBACK":
        return "Deep pullback — confirmation pending"
    return "Qualified quality — waiting for entry"


def _watch_entry_guidance(candidate: Candidate) -> tuple[float, float, float, str] | None:
    metrics = candidate.metrics or {}
    try:
        hull55 = float(metrics.get("hull55", 0.0) or 0.0)
        hma21 = float(metrics.get("hma21", 0.0) or 0.0)
        hma51 = float(metrics.get("hma51", 0.0) or 0.0)
        atr14 = float(metrics.get("atr14", 0.0) or 0.0)
    except (TypeError, ValueError):
        hull55 = hma21 = hma51 = atr14 = 0.0
    if atr14 > 0:
        if candidate.primary_horizon in {"1M", "3M"}:
            supports = [value for value in (hull55, hma21) if value > 0]
            allowance = {"1M": 0.20, "3M": 0.30}[candidate.primary_horizon]
            basis = "Hull55/HMA21 retest"
        else:
            supports = [value for value in (hull55, hma51) if value > 0]
            allowance = {"6M": 0.40, "12M": 0.50}.get(candidate.primary_horizon, 0.35)
            basis = "Hull55/HMA51 structural retest"
        if supports:
            support = max(supports)
            low = max(0.01, support - allowance * atr14)
            high = support + 0.15 * atr14
            return round((low + high) / 2.0, 2), round(low, 2), round(high, 2), basis
    if candidate.entry > 0:
        return candidate.entry, candidate.entry, candidate.entry, "existing trigger reference"
    return None


def _watch_card(candidate: Candidate, rank: int) -> str:
    timing = _timing(candidate)
    state = {
        "READY": "READY",
        "PULLBACK_REENTRY": "CONFIRMING",
        "EARLY": "EARLY",
        "HOLD_TREND": "CONFIRMING",
        "EXTENDED": "EXTENDED",
        "WEAK": "WEAK",
    }.get(timing, "WAIT")
    lines = [
        "━━━━━━━━━━━━━━",
        f"{status_icon(state)} {ticker(candidate.symbol)} • <b>{status_label(state)} • {candidate.score:.0f}/100</b>",
    ]
    guidance = _watch_entry_guidance(candidate)
    if guidance:
        _preferred, low, high, _basis = guidance
        if low == high:
            lines.append(f"Planned entry: {_price(low)} • confirmation required")
        else:
            lines.append(f"Planned entry: {_price(low)}–{_price(high)}")
    else:
        lines.append("Planned entry: Awaiting a valid structure")
    lines.extend([f"Why it is here: {text(_watch_reason(candidate))}", "Next: Wait for a confirmed end-of-day signal."])
    return "\n".join(lines)


def render_candidate_messages(
    actions: Iterable[Candidate],
    watches: Iterable[Candidate],
    regime: str,
    trade_date: str,
    *,
    freshness: FreshnessStatus | None = None,
    evaluated: int | None = None,
    benchmark_source: str = "",
    allocations: dict[tuple[str, str], Allocation] | None = None,
    tradable: int | None = None,
    quality_qualified: int | None = None,
) -> list[str]:
    action_rows = sorted(actions, key=lambda row: (-row.score, -row.trade_plan_score, row.symbol))
    watch_rows = sorted(watches, key=lambda row: (-row.score, row.symbol))
    all_rows = action_rows + watch_rows
    timing_counts = Counter(_timing(row) for row in all_rows)
    benchmark = (
        "Official NIFTY index history"
        if benchmark_source == "OFFICIAL_INDEX_HISTORY"
        else "Equal-weight NSE universe (official index history unavailable)"
    )
    summary = [
        "📊 <b>NSE V3 — DAILY WATCHLIST</b>",
        "<b>SIMULATED WATCHLIST • NO LIVE ORDERS</b>",
        f"<b>Data:</b> {text(trade_date)} EOD",
        f"<b>Market regime:</b> {text(regime.upper())}",
        f"Data Status: {_status(freshness)}",
        f"Benchmark: {benchmark}",
        "",
        "Scanner Funnel",
        f"Universe Loaded: {evaluated if evaluated is not None else '-'}",
        f"Tradable/Evaluated: {tradable if tradable is not None else (evaluated if evaluated is not None else '-')}",
        f"Quality Qualified: {quality_qualified if quality_qualified is not None else len(all_rows)}",
        f"Fresh Actionable: {len(action_rows)}",
        f"Focus Watchlist: {len(watch_rows)}",
        "",
        "Opportunity stages",
        f"🔵 Early watchlist: {timing_counts.get('EARLY', 0)} | 🟢 Watch for entry: {timing_counts.get('READY', 0)}",
        f"🟡 Wait for confirmation: {timing_counts.get('PULLBACK_REENTRY', 0)} | 🟠 Wait for pullback: {timing_counts.get('EXTENDED', 0)}",
        f"⚪ No action yet: {timing_counts.get('WEAK', 0)}",
    ]
    if not action_rows:
        summary.extend(
            [
                "",
                "No new candidates qualified today.",
                "",
                "<b>Reason</b>",
                "• No candidate crossed the qualification threshold",
                "• Existing leaders remain under lifecycle monitoring",
            ]
        )
    messages = ["\n".join(summary)]
    messages.extend(_action_messages(action_rows, allocations))
    if watch_rows:
        cards = [_watch_card(candidate, rank) for rank, candidate in enumerate(watch_rows, 1)]
        legend = "🟢 Watch for entry • 🟡 Wait for confirmation • 🔵 Early watchlist • 🟠 Wait for pullback • ⚪ No action yet\nScreening watchlist—not an active buy signal."
        messages.extend(
            paginate_cards(
                f"👀 <b>V3 WATCHLIST SETUPS</b>\n{text(trade_date)} EOD • {len(watch_rows)} stocks",
                cards,
                legend,
            )
        )
    return messages


def render_candidate_preview(
    grouped: dict[str, list[Candidate]],
    regime: str,
    trade_date: str,
    *,
    freshness: FreshnessStatus | None = None,
    evaluated: int | None = None,
    max_candidates: int = 5,
    allocations: dict[tuple[str, str], Allocation] | None = None,
) -> str:
    rows = [candidate for candidates in grouped.values() for candidate in candidates]
    messages = render_candidate_messages(
        rows[:max_candidates], [], regime, trade_date, freshness=freshness, evaluated=evaluated, allocations=allocations
    )
    text = "\n\n".join(messages)
    if rows:
        first = rows[0]
        allocation = (allocations or {}).get((first.symbol, first.horizon))
        allocation_text = ""
        if allocation:
            allocation_text = f"\nProposed Quantity: {allocation.quantity} | Capital: {_price(allocation.entry_notional)} | Initial Risk: {_price(allocation.initial_risk)}"
        text = (
            "📊 KJ NSE SCANNER V2\n" + text + f"\n\nEntry Trigger: {_price(first.entry)}\n"
            "Hybrid Hull (fixed):\n"
            f"Daily: {'Bullish' if first.metrics.get('daily_bullish') else 'Not aligned'}\n"
            f"Weekly: {'Bullish' if first.metrics.get('weekly_bullish') else 'Not aligned'}" + allocation_text
        )
    return text
