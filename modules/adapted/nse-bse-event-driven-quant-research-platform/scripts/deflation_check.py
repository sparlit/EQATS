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


"""Multiple-testing deflation check for delivery-sweep hypotheses.

Collects every signal x horizon x variant hypothesis from the sweep JSONs,
converts t-stats to two-sided p-values, applies Bonferroni (alpha/m) and
Benjamini-Hochberg FDR (q=0.10), and reports whether the R2b candidate
(dz_hi_up, price<100, 10d) survives both.

Usage:
    python scripts/deflation_check.py
"""


import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from statistics import NormalDist

from indian_quant.config import load_settings
from indian_quant.research import ExperimentTracker
from indian_quant.storage import MetadataStore

TARGET = ("dz_hi_up", "price<100", "10")


def p_from_t(t: float) -> float:
    if t is None or math.isnan(t):
        return 1.0
    return 2.0 * (1.0 - NormalDist().cdf(abs(t)))


def collect_hypotheses(gen_dir: Path) -> list[dict]:
    hyps: list[dict] = []

    def add(source: str, name: str, horizon: str, stats: dict, label=None):
        t = stats.get("t_stat")
        n = stats.get("n", 0)
        if t is None or not n or n < 30:
            return
        hyps.append(
            {
                "source": source,
                "name": f"{name}|{str(horizon).rstrip('d')}d",
                "t_stat": float(t),
                "n": int(n),
                "p": p_from_t(float(t)),
                "mean_bps": stats.get("mean_bps"),
            }
        )
        _ = label

    sweep_path = gen_dir / "delivery_sweep.json"
    if sweep_path.exists():
        full = json.loads(sweep_path.read_text()).get("full", {})
        for signal, by_h in full.items():
            for horizon, stats in by_h.items():
                add("sweep_base", signal, horizon, stats)

    r2b_path = gen_dir / "delivery_r2b.json"
    if r2b_path.exists():
        r2b = json.loads(r2b_path.read_text())
        for variant, by_h in r2b.items():
            for horizon, stats in by_h.items():
                add("r2b", variant, horizon, stats)
    return hyps


def bonferroni(hyps: list[dict], alpha: float = 0.05) -> set[int]:
    threshold = alpha / max(1, len(hyps))
    return {i for i, h in enumerate(hyps) if h["p"] <= threshold}


def benjamini_hochberg(hyps: list[dict], q: float = 0.10) -> set[int]:
    order = sorted(range(len(hyps)), key=lambda i: hyps[i]["p"])
    m = len(hyps)
    rejected: set[int] = set()
    largest_k = 0
    for rank, idx in enumerate(order, start=1):
        if hyps[idx]["p"] <= rank / m * q:
            largest_k = rank
    if largest_k:
        rejected = set(order[:largest_k])
    return rejected


def main() -> int:
    settings = load_settings(None if len(sys.argv) < 2 else sys.argv[1])
    gen_dir = Path("docs/research/generated")

    hyps = collect_hypotheses(gen_dir)
    if not hyps:
        print("no hypotheses found")
        return 1
    print(f"hypotheses tested: {len(hyps)}")

    bonf = bonferroni(hyps)
    bh = benjamini_hochberg(hyps)

    target_idx = [
        i
        for i, h in enumerate(hyps)
        if h["name"].startswith(TARGET[0])
        and TARGET[2].replace("d", "") + "d" in h["name"]
        and (TARGET[1] in h["name"] or TARGET[1] in h["source"])
    ]

    rows = []
    for i, h in enumerate(hyps):
        rows.append(
            {
                "hypothesis": f"[{h['source']}] {h['name']}",
                "n": h["n"],
                "mean_bps": h["mean_bps"],
                "t": round(h["t_stat"], 2),
                "p": round(h["p"], 6),
                "bonferroni_sig": i in bonf,
                "bh_sig": i in bh,
            }
        )
    rows.sort(key=lambda r: r["p"])

    print("\ntop survivors after correction:")
    shown = 0
    for r in rows:
        if r["bonferroni_sig"] or r["bh_sig"]:
            print(
                f"  {r['hypothesis']} | t={r['t']} p={r['p']} "
                f"bonf={r['bonferroni_sig']} bh={r['bh_sig']}"
            )
            shown += 1
        if shown >= 12:
            break

    target_survives = any(i in bonf and i in bh for i in target_idx)
    verdict = {
        "n_hypotheses": len(hyps),
        "bonferroni_threshold_p": 0.05 / len(hyps),
        "target": "|".join(TARGET),
        "target_survives_both": target_survives,
        "rows": rows,
    }
    out = gen_dir / "deflation_verdict.json"
    out.write_text(json.dumps(verdict, indent=1))

    metadata = MetadataStore(settings.storage.metadata_dsn)
    tracker = ExperimentTracker(metadata)
    tracker.record(
        kind="deflation_check",
        config={"m": len(hyps), "q": 0.10},
        metrics={"target_survives": int(target_survives)},
    )
    metadata.close()
    print(f"\nTARGET ({verdict['target']}) survives Bonferroni+BH: {target_survives}")
    print(f"saved -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
