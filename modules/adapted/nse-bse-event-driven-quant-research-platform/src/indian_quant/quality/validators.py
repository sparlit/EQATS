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


"""Data quality engine: validators, anomaly checks, completeness, reports."""


import itertools
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

    from indian_quant.instruments.calendar import NSECalendar
    from indian_quant.schemas import CorporateAction, MarketBar


@dataclass
class QualityIssue:
    severity: str  # "error" | "warning"
    code: str
    detail: str


@dataclass
class QualityReport:
    dataset: str
    n_rows: int = 0
    n_errors: int = 0
    n_warnings: int = 0
    issues: list[QualityIssue] = field(default_factory=list)

    def add(self, issue: QualityIssue) -> None:
        self.issues.append(issue)
        if issue.severity == "error":
            self.n_errors += 1
        else:
            self.n_warnings += 1

    @property
    def passed(self) -> bool:
        return self.n_errors == 0

    def to_dict(self) -> dict:
        return {
            "dataset": self.dataset,
            "n_rows": self.n_rows,
            "n_errors": self.n_errors,
            "n_warnings": self.n_warnings,
            "issues": [{"severity": i.severity, "code": i.code, "detail": i.detail} for i in self.issues],
        }


def validate_ohlc(bars: list[MarketBar], report: QualityReport) -> None:
    for bar in bars:
        if bar.high < max(bar.open, bar.close):
            report.add(QualityIssue("error", "OHLC_HIGH", f"{bar.instrument_id}@{bar.timestamp}"))
        if bar.low > min(bar.open, bar.close):
            report.add(QualityIssue("error", "OHLC_LOW", f"{bar.instrument_id}@{bar.timestamp}"))
        if bar.low > bar.high:
            report.add(QualityIssue("error", "OHLC_ORDER", f"{bar.instrument_id}@{bar.timestamp}"))


def detect_duplicates(bars: list[MarketBar], report: QualityReport) -> list[MarketBar]:
    seen: dict[tuple, MarketBar] = {}
    unique: list[MarketBar] = []
    for bar in bars:
        key = (bar.instrument_id, bar.timeframe.value, int(bar.timestamp.timestamp()))
        if key in seen:
            prev = seen[key]
            if abs(prev.close - bar.close) > 1e-9:
                report.add(
                    QualityIssue(
                        "warning",
                        "DUPLICATE_CONFLICT",
                        f"{bar.instrument_id}@{bar.timestamp} close {prev.close} vs {bar.close}",
                    )
                )
            else:
                report.add(QualityIssue("warning", "DUPLICATE", f"{bar.instrument_id}@{bar.timestamp}"))
            continue
        seen[key] = bar
        unique.append(bar)
    return unique


def detect_price_anomalies(
    bars: list[MarketBar],
    report: QualityReport,
    *,
    max_abs_return: float = 0.35,
) -> None:
    by_instrument: dict[str, list[MarketBar]] = {}
    for bar in bars:
        by_instrument.setdefault(bar.instrument_id, []).append(bar)
    for instrument_id, series in by_instrument.items():
        ordered = sorted(series, key=lambda b: b.timestamp)
        for prev, cur in itertools.pairwise(ordered):
            if prev.close <= 0:
                continue
            ret = cur.close / prev.close - 1.0
            if abs(ret) > max_abs_return:
                report.add(
                    QualityIssue(
                        "warning",
                        "PRICE_JUMP",
                        f"{instrument_id} {prev.timestamp.date()}->{cur.timestamp.date()} return {ret:.2%}",
                    )
                )


def detect_missing_sessions(
    bars: list[MarketBar],
    report: QualityReport,
    *,
    holidays: set[date] | None = None,
    calendar: NSECalendar | None = None,
    max_gap_days: int = 10,
) -> None:
    """Flag gaps containing expected trading sessions.

    With a calendar supplied, only days the calendar deems trading days
    count as missing; otherwise weekday-minus-holidays logic is used.
    """
    by_instrument: dict[str, list[MarketBar]] = {}
    for bar in bars:
        by_instrument.setdefault(bar.instrument_id, []).append(bar)
    for instrument_id, series in by_instrument.items():
        ordered = sorted(series, key=lambda b: b.timestamp)
        for prev, cur in itertools.pairwise(ordered):
            gap_days = (cur.timestamp.date() - prev.timestamp.date()).days
            if gap_days <= 1 or gap_days > max_gap_days:
                continue
            if calendar is not None:
                unexplained = calendar.trading_days_between(prev.timestamp.date(), cur.timestamp.date())
                unexplained = unexplained[1:-1] if len(unexplained) > 2 else []
            else:
                missing_weekdays = _weekdays_between(prev.timestamp.date(), cur.timestamp.date())
                unexplained = [d for d in missing_weekdays if d not in (holidays or set())]
            if unexplained:
                report.add(
                    QualityIssue(
                        "warning",
                        "MISSING_SESSIONS",
                        f"{instrument_id} missing {len(unexplained)} sessions {unexplained[0]}..{unexplained[-1]}",
                    )
                )


def detect_adjustment_discontinuities(
    bars: list[MarketBar],
    actions: list[CorporateAction],
    report: QualityReport,
    *,
    tolerance_pct: float = 0.05,
) -> None:
    """Verify raw-price jumps at split/bonus ex-dates match declared ratios.

    Runs on UNADJUSTED bars. For each action with an ex_date, the observed
    close ratio post/pre should approximate the action's adjustment factor.
    """
    from indian_quant.schemas import CorporateActionType

    price_actions = [
        a for a in actions if a.action_type in (CorporateActionType.SPLIT, CorporateActionType.BONUS) and a.ex_date
    ]
    if not price_actions:
        return
    by_instrument: dict[str, list[MarketBar]] = {}
    for bar in bars:
        by_instrument.setdefault(bar.instrument_id, []).append(bar)
    for instrument_id, series in by_instrument.items():
        ordered = sorted(series, key=lambda b: b.timestamp)
        inst_actions = [a for a in price_actions if a.instrument_id == instrument_id]
        for action in inst_actions:
            ex = action.ex_date
            assert ex is not None
            pre = [b for b in ordered if b.timestamp.date() < ex]
            post = [b for b in ordered if b.timestamp.date() >= ex]
            if not pre or not post:
                report.add(QualityIssue("warning", "ADJ_NO_WINDOW", f"{instrument_id} no bars around ex-date {ex}"))
                continue
            pre_close = pre[-1].close
            post_close = post[0].close
            if pre_close <= 0:
                continue
            observed = post_close / pre_close
            expected = action.adjustment_ratio()
            drift = abs(observed / expected - 1.0) if expected else 0.0
            if drift > tolerance_pct:
                report.add(
                    QualityIssue(
                        "error",
                        "ADJ_DISCONTINUITY",
                        f"{instrument_id} ex-date {ex}: observed ratio "
                        f"{observed:.4f} vs declared {expected:.4f} "
                        f"(drift {drift:.2%})",
                    )
                )


def detect_census_drift(
    raw_census: dict[str, int],
    lake_census: dict[str, int],
    report: QualityReport,
    *,
    label: str = "ingest",
    min_ratio: float = 0.95,
    bucket_map: dict[str, str] | None = None,
    ignore_buckets: set[str] | frozenset[str] | None = None,
) -> None:
    """Population-parity guard between a raw source payload and the lake.

    Row-level validators cannot see records that never arrived. This check
    compares field-distribution histograms instead:

      1. MISSING-BUCKET: raw shows N>0 rows for a bucket but the lake
         contains zero -> silent segment drop (the SM/ST delivery bug).
      2. TOTAL-RATIO: lake rows must be >= min_ratio of raw rows, catching
         partial drops even within accepted buckets.

    ``bucket_map`` renames raw buckets into lake-space first (e.g.
    {"SM": "SME", "ST": "SME"}) so differently-named axes compare cleanly.
    Unmapped raw buckets pass through unchanged; mapped buckets merge by sum.
    """
    ignored = ignore_buckets or frozenset()
    if bucket_map or ignored:
        mapped: dict[str, int] = {}
        for bucket, count in raw_census.items():
            if bucket in ignored:
                continue
            target = bucket_map.get(bucket, bucket) if bucket_map else bucket
            mapped[target] = mapped.get(target, 0) + int(count)
        raw_census = mapped

    for bucket in sorted(raw_census):
        raw_n = int(raw_census[bucket])
        if raw_n <= 0:
            continue
        lake_n = int(lake_census.get(bucket, 0))
        if lake_n == 0:
            report.add(
                QualityIssue(
                    "error",
                    "CENSUS_DRIFT",
                    f"{label}: raw '{bucket}'={raw_n} but lake has 0 rows",
                )
            )

    total_raw = sum(int(v) for v in raw_census.values())
    total_lake = sum(int(v) for v in lake_census.values())
    if total_raw > 0 and (total_lake / total_raw) < min_ratio:
        report.add(
            QualityIssue(
                "error",
                "CENSUS_DROP",
                f"{label}: lake rows {total_lake} below {min_ratio:.0%} of raw rows {total_raw}",
            )
        )


def _weekdays_between(start: date, end: date) -> list[date]:
    days: list[date] = []
    cursor = start + timedelta(days=1)
    while cursor < end:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def run_quality_suite(
    bars: list[MarketBar],
    *,
    dataset: str,
    holidays: set[date] | None = None,
    calendar: NSECalendar | None = None,
    actions: list[CorporateAction] | None = None,
    max_gap_days: int = 10,
) -> tuple[QualityReport, list[MarketBar]]:
    report = QualityReport(dataset=dataset, n_rows=len(bars))
    validate_ohlc(bars, report)
    unique = detect_duplicates(bars, report)
    detect_price_anomalies(unique, report)
    detect_missing_sessions(unique, report, holidays=holidays, calendar=calendar, max_gap_days=max_gap_days)
    if actions:
        detect_adjustment_discontinuities(unique, actions, report)
    return report, unique


def frame_quality_summary(df: pd.DataFrame) -> pd.DataFrame:
    return df.describe(include="all").transpose()
