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


"""Daily scanner diagnostics, funnel analytics and admin reporting."""

import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .candidates import Candidate

_SCORE_BUCKETS = ("90-100", "80-89", "70-79", "60-69", "<60")


@dataclass(frozen=True)
class ScannerDiagnostics:
    trade_date: str
    benchmark_source: str
    benchmark_reason: str
    benchmark_sessions: int
    universe_loaded: int
    history_eligible: int
    quality_qualified: int
    action_count: int
    watch_count: int
    reject_count: int
    horizon_distribution: dict[str, int]
    trigger_distribution: dict[str, int]
    trade_plan_distribution: dict[str, int]
    score_distribution: dict[str, int]
    rejection_reasons: dict[str, int]
    component_averages: dict[str, float]
    action_average_score: float
    action_average_rr_t1: float
    watch_average_score: float
    watch_average_trade_plan_score: float

    def to_dict(self) -> dict:
        return asdict(self)


def _score_bucket(score: float) -> str:
    if score >= 90:
        return "90-100"
    if score >= 80:
        return "80-89"
    if score >= 70:
        return "70-79"
    if score >= 60:
        return "60-69"
    return "<60"


def build_scanner_diagnostics(
    candidates: list[Candidate],
    *,
    trade_date: str,
    benchmark_source: str,
    benchmark_sessions: int,
) -> ScannerDiagnostics:
    actions = [row for row in candidates if row.classification == "ACTION"]
    watches = [row for row in candidates if row.classification == "WATCH"]
    rejects = [row for row in candidates if row.classification == "REJECT"]

    horizon_distribution: Counter[str] = Counter()
    trigger_distribution: Counter[str] = Counter()
    trade_plan_distribution: Counter[str] = Counter()
    score_distribution: Counter[str] = Counter(dict.fromkeys(_SCORE_BUCKETS, 0))
    rejection_reasons: Counter[str] = Counter()
    component_values: dict[str, list[float]] = defaultdict(list)

    history_eligible = 0
    quality_qualified = 0
    for candidate in candidates:
        if any(
            "insufficient_history" not in score.get("hard_blocks", ()) for score in candidate.horizon_scores.values()
        ):
            history_eligible += 1
        if candidate.eligible_horizons:
            quality_qualified += 1
        for horizon in candidate.eligible_horizons:
            horizon_distribution[horizon] += 1
        if candidate.entry_trigger and candidate.entry_trigger != "NO_TRIGGER":
            trigger_distribution[candidate.entry_trigger] += 1
        trade_plan_distribution[candidate.trade_plan_state] += 1
        score_distribution[_score_bucket(candidate.score)] += 1
        if candidate.classification == "REJECT":
            rejection_reasons.update(candidate.reasons_against)
        for score in candidate.horizon_scores.values():
            if score.get("state") in {"QUALIFIED", "WATCH"}:
                for component, points in score.get("component_scores", {}).items():
                    component_values[component].append(float(points))

    component_averages = {
        component: round(mean(values), 2) for component, values in sorted(component_values.items()) if values
    }
    benchmark_reason = (
        "Official NIFTY index history unavailable; equal-weight NSE universe used"
        if benchmark_source != "OFFICIAL_INDEX_HISTORY"
        else "Official index history used"
    )
    return ScannerDiagnostics(
        trade_date=trade_date,
        benchmark_source=benchmark_source,
        benchmark_reason=benchmark_reason,
        benchmark_sessions=benchmark_sessions,
        universe_loaded=len(candidates),
        history_eligible=history_eligible,
        quality_qualified=quality_qualified,
        action_count=len(actions),
        watch_count=len(watches),
        reject_count=len(rejects),
        horizon_distribution=dict(sorted(horizon_distribution.items())),
        trigger_distribution=dict(trigger_distribution.most_common()),
        trade_plan_distribution=dict(trade_plan_distribution.most_common()),
        score_distribution={key: score_distribution[key] for key in _SCORE_BUCKETS},
        rejection_reasons=dict(rejection_reasons.most_common(20)),
        component_averages=component_averages,
        action_average_score=round(mean([row.score for row in actions]), 2) if actions else 0.0,
        action_average_rr_t1=round(mean([row.reward_risk_t1 for row in actions]), 2) if actions else 0.0,
        watch_average_score=round(mean([row.score for row in watches]), 2) if watches else 0.0,
        watch_average_trade_plan_score=round(mean([row.trade_plan_score for row in watches]), 2) if watches else 0.0,
    )


def render_admin_diagnostics(report: ScannerDiagnostics) -> str:
    top_reason = next(iter(report.rejection_reasons), "None")
    lines = [
        "📊 MIS ADMIN DIAGNOSTICS",
        f"Trade Date: {report.trade_date}",
        "",
        f"Universe Loaded: {report.universe_loaded}",
        f"History Eligible: {report.history_eligible}",
        f"Quality Qualified: {report.quality_qualified}",
        f"ACTION: {report.action_count}",
        f"WATCH: {report.watch_count}",
        f"REJECT: {report.reject_count}",
        "",
        f"Benchmark: {report.benchmark_source}",
        f"Benchmark Sessions: {report.benchmark_sessions}",
        f"Reason: {report.benchmark_reason}",
        "",
        f"Top Rejection: {top_reason}",
        f"Average ACTION Score: {report.action_average_score:.2f}",
        f"Average ACTION RR(T1): {report.action_average_rr_t1:.2f}R",
        f"Average WATCH Score: {report.watch_average_score:.2f}",
    ]
    return "\n".join(lines)


def save_scanner_diagnostics(
    report: ScannerDiagnostics,
    output_dir: str | Path = "output",
) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / "v2_candidate_diagnostics.json"
    text_path = target / "v2_candidate_diagnostics.txt"
    json_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    text_path.write_text(render_admin_diagnostics(report), encoding="utf-8")
    return json_path, text_path
