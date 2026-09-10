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


"""Generate validated monthly reviews for the prepared portfolio queue."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.portfolio_review.recovery import write_recovery_manifest
from src.portfolio_review.review_policy import ReviewPolicy, should_review_symbol
from src.portfolio_review.review_runner import ReviewRunResult, run_review


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate monthly portfolio reviews")
    parser.add_argument("--queue", default="data/review_queue.json")
    parser.add_argument("--scanner", default="telegram_last_scan.json")
    parser.add_argument("--reports-root", default="reports/portfolio")
    parser.add_argument("--primary-provider", default=None)
    parser.add_argument("--fallback-provider", default=None)
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--max-age-days", type=int, default=None)
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--result", default="data/portfolio_review_run.json")
    parser.add_argument("--recovery", default="data/portfolio_review_recovery.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    queue_path = Path(args.queue)
    if not queue_path.exists():
        msg = f"Review queue not found: {queue_path}"
        raise FileNotFoundError(msg)

    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    period = str(queue.get("review_period", ""))
    items = queue.get("items", queue.get("symbols", []))
    if not isinstance(items, list):
        msg = "Review queue items must be a list"
        raise ValueError(msg)

    env_policy = ReviewPolicy.from_env()
    policy = ReviewPolicy(
        max_age_days=args.max_age_days or env_policy.max_age_days,
        max_symbols_per_run=(args.max_symbols if args.max_symbols is not None else env_policy.max_symbols_per_run),
        max_provider_calls_per_run=env_policy.max_provider_calls_per_run,
        force_refresh=args.force_refresh or env_policy.force_refresh,
    )

    normalized_items: list[dict] = []
    for item in items[: policy.max_symbols_per_run]:
        normalized_items.append(item if isinstance(item, dict) else {"symbol": str(item), "position": {}})

    results: list[ReviewRunResult] = []
    estimated_calls = 0
    for item in normalized_items:
        symbol = str(item.get("symbol", "")).strip().upper()
        should_run, reason = should_review_symbol(symbol, reports_root=args.reports_root, policy=policy)
        if not should_run:
            results.append(ReviewRunResult(symbol=symbol, status="SKIPPED", error=reason))
            continue

        # Primary + fallback with one retry each can consume up to four calls.
        worst_case_calls = 4
        if estimated_calls + worst_case_calls > policy.max_provider_calls_per_run:
            results.append(
                ReviewRunResult(
                    symbol=symbol,
                    status="SKIPPED",
                    error="provider-call budget exhausted",
                )
            )
            continue
        estimated_calls += worst_case_calls
        results.append(
            run_review(
                item,
                period,
                scanner_path=args.scanner,
                reports_root=args.reports_root,
                primary_provider=args.primary_provider,
                fallback_provider=args.fallback_provider,
            )
        )

    serialized = [asdict(result) for result in results]
    payload = {
        "review_period": period,
        "requested_count": len(normalized_items),
        "success_count": sum(result.status == "SUCCESS" for result in results),
        "skipped_count": sum(result.status == "SKIPPED" for result in results),
        "failed_count": sum(result.status == "FAILED" for result in results),
        "estimated_provider_call_budget_used": estimated_calls,
        "policy": asdict(policy),
        "results": serialized,
    }
    output = Path(args.result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_recovery_manifest(serialized, review_period=period, path=args.recovery)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["failed_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
