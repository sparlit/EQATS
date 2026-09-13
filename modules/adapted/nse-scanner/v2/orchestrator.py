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


"""End-to-end daily orchestration for NSE Scanner V2."""

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from typing import TYPE_CHECKING

import pandas as pd

from .candidate_diagnostics import build_scanner_diagnostics, render_admin_diagnostics, save_scanner_diagnostics
from .candidates import evaluate_candidate, rank_candidates, watch_candidates
from .daily_portfolio import process_portfolio_day
from .database import V2Database
from .eligibility import EligibilityResult, evaluate_eligibility
from .freshness import FreshnessStatus, assess_freshness
from .indicators import atr
from .lifecycle import TradeState, new_position, transition
from .portfolio_message import render_portfolio_message
from .portfolio_performance import build_portfolio_snapshot
from .portfolio_risk import PortfolioConfig, allocate_long_position
from .portfolio_store import PortfolioStore
from .portfolio_summary_message import render_portfolio_summary
from .preview import render_candidate_messages
from .progression import next_holding_stage
from .snapshots import build_market_snapshot
from .telegram_delivery import DeliveryResult, send_admin_messages, send_messages, topic_id
from .tradeability import evaluate_tradeability
from .tradeability import summarize as summarize_tradeability

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class DailyRunResult:
    trade_date: str
    regime: str
    benchmark_source: str
    freshness: FreshnessStatus
    evaluated: int
    selected: int
    created_positions: int
    portfolio_positions: int
    candidate_message: str
    portfolio_message: str
    portfolio_summary_message: str
    delivery: DeliveryResult
    portfolio_snapshot: dict
    watch_count: int = 0
    candidate_message_count: int = 0
    diagnostics: dict | None = None
    admin_message: str = ""
    diagnostics_json_path: str = ""
    diagnostics_text_path: str = ""
    admin_delivery: DeliveryResult = DeliveryResult(False, 0, "not_attempted")
    eligibility_funnel: dict | None = None
    dashboard_candidates: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        return asdict(self)


def _equal_weight_benchmark(prices: pd.DataFrame) -> pd.DataFrame:
    frame = prices[["symbol", "trade_date", "close"]].copy()
    frame["return"] = frame.groupby("symbol")["close"].pct_change()
    daily = frame.groupby("trade_date", as_index=False)["return"].mean().fillna(0.0)
    daily["close"] = (1.0 + daily["return"]).cumprod() * 1000.0
    return daily[["trade_date", "close"]]


def _existing_keys(store: PortfolioStore) -> set[tuple[str, str]]:
    return {(position.symbol, position.horizon) for position in store.open_positions()}


def _warning_header(freshness: FreshnessStatus, benchmark_source: str) -> str:
    warnings = list(freshness.reasons)
    if benchmark_source != "OFFICIAL_INDEX_HISTORY":
        warnings.append(
            "equal_weight_fallback: Benchmark source is the equal-weight NSE universe because official index history is unavailable"
        )
    return "" if not warnings else "DATA NOTE: " + "; ".join(warnings) + "\n\n"


def run_daily(
    db_path: str | Path,
    as_of: date | str | None = None,
    top_n: int = 10,
    minimum_score: float = 70.0,
    send_telegram: bool = False,
    send_admin_telegram: bool | None = None,
    portfolio_config: PortfolioConfig = PortfolioConfig(),
    diagnostics_output_dir: str | Path = "output",
    strict_v3_eligibility: bool = True,
) -> DailyRunResult:
    run_date = pd.Timestamp(as_of or date.today()).date()
    database = V2Database(db_path)
    database.ensure_v3_schema()
    prices = database.load_prices(end_date=run_date.isoformat(), min_sessions=260)
    if prices.empty:
        msg = "No usable V2 price history"
        raise RuntimeError(msg)
    indices = database.load_indices(end_date=run_date.isoformat())
    freshness = assess_freshness(prices, indices, run_date)

    benchmark_source = "OFFICIAL_INDEX_HISTORY"
    benchmark = pd.DataFrame()
    if not indices.empty:
        normalized = indices["index_name"].astype(str).str.upper()
        preferred = indices[normalized.isin(["NIFTY 500", "NIFTY 50"])]
        if not preferred.empty and preferred.groupby("index_name")["trade_date"].nunique().max() >= 200:
            preferred_names = preferred["index_name"].astype(str).str.upper()
            chosen = "NIFTY 500" if (preferred_names == "NIFTY 500").any() else "NIFTY 50"
            benchmark = preferred[preferred_names == chosen].copy()
    if benchmark.empty:
        benchmark = _equal_weight_benchmark(prices)
        benchmark_source = "EQUAL_WEIGHT_UNIVERSE_FALLBACK"

    snapshot = build_market_snapshot(prices, benchmark)
    regime = snapshot["regime"]
    benchmark = benchmark.sort_values("trade_date").reset_index(drop=True)
    benchmark_close = benchmark["close"].reset_index(drop=True)
    store = PortfolioStore(db_path)
    store.initialize()
    master = database.load_symbol_master(run_date.isoformat())
    metadata = {str(row["symbol"]): row.to_dict() for _, row in master.iterrows()} if not master.empty else {}
    restricted = database.load_restricted_symbols(run_date.isoformat())
    lifecycle_registry = database.load_lifecycle_registry()
    session_calendar = tuple(sorted(pd.to_datetime(prices["trade_date"]).dt.date.astype(str).unique()))
    fundamental_gates = database.load_fundamental_gates(run_date.isoformat())
    eligibility_results = {}
    tradeability_results = {}
    candidates = []
    for symbol, frame in prices.groupby("symbol"):
        symbol = str(symbol)
        tradeability = evaluate_tradeability(
            symbol,
            frame,
            market_date=run_date.isoformat(),
            master_row=metadata.get(symbol),
            restricted_reason=restricted.get(symbol),
            lifecycle_event=lifecycle_registry.get(symbol),
            session_calendar=session_calendar,
            require_metadata=bool(metadata),
        )
        tradeability_results[symbol] = tradeability
        if not tradeability.eligible or tradeability.entry_blocked:
            eligibility_results[symbol] = EligibilityResult(
                symbol,
                False,
                tradeability.reason_code if not tradeability.eligible else "MATERIAL_CORPORATE_ACTION_REVIEW",
                tradeability.stage,
                tradeability.detail,
                "TRADEABLE_CURRENT_SECURITY",
                metrics={
                    "successor_symbol": tradeability.successor_symbol or "",
                    "symbol_last_date": tradeability.symbol_last_date or "",
                    "staleness_sessions": tradeability.staleness_sessions or 0,
                },
            )
            continue
        eligibility = evaluate_eligibility(
            symbol,
            frame,
            metadata=metadata.get(symbol),
            restricted_reason=restricted.get(symbol),
            as_of_date=run_date.isoformat(),
            require_market_cap=strict_v3_eligibility,
            require_promoter_holding=strict_v3_eligibility,
            require_corporate_action_safety=strict_v3_eligibility,
        )
        eligibility_results[symbol] = eligibility
        if not eligibility.eligible:
            continue
        previous = store.opportunity_state(symbol)
        candidates.append(
            evaluate_candidate(
                symbol,
                frame,
                regime,
                stale_data=freshness.prices_stale,
                minimum_score=minimum_score,
                benchmark_close=benchmark_close,
                previous_stage=previous["progression_stage"] if previous else None,
                previously_exited=bool(previous["previously_exited"]) if previous else False,
                action_permitted=benchmark_source == "OFFICIAL_INDEX_HISTORY" and not freshness.degraded,
            )
        )
    database.save_eligibility_audit(run_date.isoformat(), eligibility_results)
    rejection_counts = Counter(result.reason_code for result in eligibility_results.values() if not result.eligible)
    eligibility_funnel = {
        "mode": "V3_STRICT" if strict_v3_eligibility else "V2_COMPATIBLE",
        "universe": len(eligibility_results),
        "eligible": sum(result.eligible for result in eligibility_results.values()),
        "rejected": sum(not result.eligible for result in eligibility_results.values()),
        "rejection_reasons": dict(sorted(rejection_counts.items())),
        "tradeability": summarize_tradeability(tradeability_results),
    }

    ranked = rank_candidates(candidates, top_n=None)
    selected = [candidate for rows in ranked.values() for candidate in rows]
    selected.sort(key=lambda candidate: (-candidate.score, -candidate.trade_plan_score, candidate.symbol))
    if top_n is not None and top_n > 0:
        selected = selected[:top_n]
    watches = watch_candidates(candidates)[:12]
    quality_qualified = sum(1 for candidate in candidates if candidate.metrics.get("focus_horizons"))

    diagnostics = build_scanner_diagnostics(
        candidates,
        trade_date=run_date.isoformat(),
        benchmark_source=benchmark_source,
        benchmark_sessions=int(benchmark["trade_date"].nunique()),
    )
    diagnostics_json, diagnostics_text = save_scanner_diagnostics(diagnostics, output_dir=diagnostics_output_dir)
    funnel_lines = [
        f"ELIGIBILITY FUNNEL — {eligibility_funnel['mode']}",
        f"Universe: {eligibility_funnel['universe']}",
        f"Eligible: {eligibility_funnel['eligible']}",
        f"Rejected: {eligibility_funnel['rejected']}",
    ]
    funnel_lines.extend(f"{reason}: {count}" for reason, count in rejection_counts.most_common())
    admin_message = "\n".join(funnel_lines) + "\n\n" + render_admin_diagnostics(diagnostics)

    persisted_candidates = sorted(
        [candidate for candidate in candidates if candidate.opportunity_classification != "UNQUALIFIED"],
        key=lambda candidate: (-candidate.score, -candidate.trade_plan_score, candidate.symbol),
    )
    for rank, candidate in enumerate(persisted_candidates, start=1):
        store.remember_opportunity(candidate, scanner_rank=rank)
    existing = _existing_keys(store)
    created, allocations = 0, {}
    committed = store.open_positions()
    committed_capital = sum(p.quantity * p.entry for p in committed)
    committed_risk = sum(p.quantity * (p.entry - p.initial_stop) for p in committed)
    for candidate in selected:
        store.remember_candidate(candidate.symbol, candidate.horizon, candidate.trade_date, candidate.score)
        key = (candidate.symbol, candidate.horizon)
        if key in existing:
            continue
        allocation = allocate_long_position(
            candidate.entry,
            candidate.stop,
            committed_capital=committed_capital,
            committed_risk=committed_risk,
            committed_positions=len(committed),
            config=portfolio_config,
        )
        if allocation.quantity <= 0:
            continue
        allocations[key] = allocation
        position = new_position(
            candidate.symbol,
            "SWING_1_3M",
            candidate.trade_date,
            candidate.entry,
            candidate.stop,
            candidate.target1,
            candidate.target2,
            quantity=allocation.quantity,
        )
        store.save_position(position, "CREATE")
        existing.add(key)
        committed.append(position)
        committed_capital += allocation.entry_notional
        committed_risk += allocation.initial_risk
        created += 1

    latest_bars = {}
    for symbol, frame in prices.groupby("symbol"):
        ordered = frame.sort_values("trade_date")
        bar = ordered.iloc[-1].to_dict()
        bar["atr14"] = float(atr(ordered, 14).iloc[-1])
        latest_bars[str(symbol)] = bar
    candidate_by_symbol = {candidate.symbol: candidate for candidate in candidates}
    qualification = {
        symbol: candidate.classification in {"ACTION", "WATCH"} for symbol, candidate in candidate_by_symbol.items()
    }
    invalidated = {
        position.symbol
        for position in store.open_positions()
        if position.symbol in candidate_by_symbol
        and not bool(candidate_by_symbol[position.symbol].metrics.get("weekly_bullish"))
        and position.state in {TradeState.WATCH, TradeState.READY}
    }
    process_portfolio_day(
        store,
        run_date.isoformat(),
        latest_bars,
        qualification_by_symbol=qualification,
        invalidated_symbols=invalidated,
    )
    for position in store.open_positions():
        candidate = candidate_by_symbol.get(position.symbol)
        if candidate is None or position.state not in {TradeState.OPEN, TradeState.PARTIAL, TradeState.TRAILING}:
            continue
        sessions = max(0, len(pd.bdate_range(position.created_date, run_date.isoformat())) - 1)
        decision = next_holding_stage(
            position.progression_stage,
            {key: value["state"] for key, value in candidate.horizon_scores.items()},
            sessions,
            trend_intact=bool(candidate.metrics.get("weekly_bullish")),
            fundamentals_passed=fundamental_gates.get(position.symbol),
        )
        if decision.changed:
            promoted = transition(
                position,
                "PROMOTE",
                run_date.isoformat(),
                price=latest_bars[position.symbol]["close"],
                reason=decision.stage.value,
            )
            store.save_position(promoted, "PROMOTE", previous_state=position.state, price=promoted.last_price)
    portfolio_positions = store.open_positions()
    report_positions = store.positions_for_daily_report(run_date.isoformat())
    previous_snapshot = store.latest_portfolio_snapshot()
    all_positions = store.all_positions()
    portfolio_snapshot = build_portfolio_snapshot(all_positions, run_date.isoformat(), portfolio_config.capital_base)
    store.save_portfolio_snapshot(portfolio_snapshot)
    portfolio_summary_message = render_portfolio_summary(
        portfolio_snapshot,
        float(previous_snapshot["total_pnl"])
        if previous_snapshot and previous_snapshot["portfolio_date"] != run_date.isoformat()
        else None,
        all_positions,
    )

    candidate_messages = render_candidate_messages(
        selected,
        watches,
        regime,
        run_date.isoformat(),
        freshness=freshness,
        evaluated=int(prices["symbol"].nunique()),
        tradable=len(candidates),
        quality_qualified=quality_qualified,
        benchmark_source=benchmark_source,
        allocations=allocations,
    )
    candidate_message = "\n\n".join(candidate_messages)
    portfolio_message = _warning_header(freshness, benchmark_source) + render_portfolio_message(
        report_positions, run_date.isoformat()
    )
    candidate_delivery = send_messages(
        candidate_messages,
        enabled=send_telegram,
        message_thread_id=topic_id("DAILY") or topic_id("CANDIDATES"),
        message_type="fresh_candidates",
        scan_date=run_date.isoformat(),
    )
    portfolio_delivery = send_messages(
        [portfolio_message],
        enabled=send_telegram,
        message_thread_id=topic_id("PORTFOLIO"),
        message_type="lifecycle",
        scan_date=run_date.isoformat(),
    )
    summary_delivery = send_messages(
        [portfolio_summary_message],
        enabled=send_telegram,
        message_thread_id=topic_id("PORTFOLIO"),
        message_type="portfolio_pnl",
        scan_date=run_date.isoformat(),
    )
    delivery = DeliveryResult(
        sent=candidate_delivery.sent or portfolio_delivery.sent or summary_delivery.sent,
        message_count=candidate_delivery.message_count
        + portfolio_delivery.message_count
        + summary_delivery.message_count,
        reason="sent"
        if candidate_delivery.sent or portfolio_delivery.sent or summary_delivery.sent
        else candidate_delivery.reason,
    )
    admin_enabled = send_telegram if send_admin_telegram is None else send_admin_telegram
    admin_delivery = send_admin_messages([admin_message], enabled=admin_enabled)
    dashboard_candidates = {candidate.symbol: candidate.to_dict() for candidate in [*selected, *watches]}

    return DailyRunResult(
        trade_date=run_date.isoformat(),
        regime=regime,
        benchmark_source=benchmark_source,
        freshness=freshness,
        evaluated=len(candidates),
        selected=len(selected),
        created_positions=created,
        portfolio_positions=len(portfolio_positions),
        candidate_message=candidate_message,
        portfolio_message=portfolio_message,
        portfolio_summary_message=portfolio_summary_message,
        delivery=delivery,
        portfolio_snapshot=portfolio_snapshot.to_dict(),
        watch_count=len(watches),
        candidate_message_count=len(candidate_messages),
        diagnostics=diagnostics.to_dict(),
        admin_message=admin_message,
        diagnostics_json_path=str(diagnostics_json),
        diagnostics_text_path=str(diagnostics_text),
        admin_delivery=admin_delivery,
        eligibility_funnel=eligibility_funnel,
        dashboard_candidates=tuple(dashboard_candidates.values()),
    )
