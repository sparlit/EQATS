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


"""Run slippage bottleneck benchmarks and compare to a saved baseline."""


import argparse
import gc
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE = REPO_ROOT / ".asv" / "baseline-pre-slippage-opt.json"


def _median_ms(fn: Callable[[], None], warmup: int = 2, repeats: int = 7) -> float:
    times: list[float] = []
    for i in range(warmup + repeats):
        gc.collect()
        t0 = time.perf_counter()
        fn()
        ms = (time.perf_counter() - t0) * 1000
        if i >= warmup:
            times.append(ms)
    return statistics.median(times)


def _run_bottleneck() -> dict[str, float]:
    from benchmarks.bench_slippage import (
        WalkforwardVolatilitySlippage,
        WalkforwardVolumeSlippage,
    )

    out: dict[str, float] = {}

    volume_bench = WalkforwardVolumeSlippage()
    volume_bench.setup()
    out["WalkforwardVolumeSlippage.time_walkforward_volume_slippage"] = _median_ms(
        volume_bench.time_walkforward_volume_slippage
    )

    vol_bench = WalkforwardVolatilitySlippage()
    vol_bench.setup()
    out["WalkforwardVolatilitySlippage.time_walkforward_volatility_slippage"] = _median_ms(
        vol_bench.time_walkforward_volatility_slippage
    )

    return out


def run_all() -> dict[str, Any]:
    bottleneck = _run_bottleneck()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    return {"commit": commit, "bottleneck": bottleneck}


def save_baseline(path: Path) -> None:
    results = run_all()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "commit": results["commit"],
        "bottleneck": results["bottleneck"],
    }
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    print(f"Saved slippage baseline to {path}")


def _pct(base: float, cur: float) -> str:
    if base == 0:
        return "—"
    return f"{((cur - base) / base) * 100:+.1f}%"


def compare(baseline_path: Path) -> int:
    base = json.loads(baseline_path.read_text(encoding="utf-8"))
    cur = run_all()
    base_metrics = base.get("bottleneck", {})
    cur_metrics = cur["bottleneck"]

    print("Slippage bottleneck benchmarks:")
    print(f"{'Benchmark':<72} {'Before':>10} {'After':>10} {'Change':>8}")
    print("-" * 104)
    for name in sorted(set(base_metrics) | set(cur_metrics)):
        b, c = base_metrics.get(name), cur_metrics.get(name)
        if b is None:
            print(f"{name:<72} {'—':>10} {c:>10.2f} {'new':>8}")
        elif c is None:
            print(f"{name:<72} {b:>10.2f} {'—':>10} {'removed':>8}")
        else:
            print(f"{name:<72} {b:>10.2f} {c:>10.2f} {_pct(b, c):>8}")
    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--save-baseline",
        type=Path,
        nargs="?",
        const=DEFAULT_BASELINE,
        default=None,
    )
    parser.add_argument(
        "--compare",
        type=Path,
        nargs="?",
        const=DEFAULT_BASELINE,
        default=None,
    )
    args = parser.parse_args(argv)

    if args.save_baseline is not None:
        save_baseline(args.save_baseline)
        return 0
    if args.compare is not None:
        return compare(args.compare)

    results = run_all()
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO_ROOT))
    raise SystemExit(main())
