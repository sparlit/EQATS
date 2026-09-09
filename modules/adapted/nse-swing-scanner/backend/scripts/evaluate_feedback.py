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


#!/usr/bin/env python3
"""
evaluate_feedback.py
Continuous feedback loop for the recommendation engine (1.5.0).

The outcome tracker measures what happened to each suggestion. This script
closes the loop: it reads those labelled outcomes and produces the evidence
an operator needs to change WEIGHTS (backend/settings.py) on purpose rather
than on vibes:

  1. Sub-score rank IC  — Spearman correlation between each sub-score and
     realized excess return, per window, with a deterministic bootstrap CI.
  2. Regime split       — the same ICs computed within neutral vs risk_off
     cohorts (are components regime-dependent?).
  3. Confirmation A/B   — confirmed vs anticipatory T+5 outcomes.
  4. Shadow re-scoring  — recompute every closed row's score from its
     stored sub_scores under candidate weight sets (same renormalisation
     math as scanner.py), re-bucket with the pass_v3 bands, and compare
     band-level outcomes vs the baseline weights.

REPORT-ONLY BY DESIGN. Nothing here writes to settings.py; promotion is a
human decision gated by the checklist in the report. All in-sample numbers
are labelled as such — the out-of-sample test is the following weeks of
tracker cohorts.

Stdlib only; no network. Deterministic: fixed bootstrap seed, sorted keys.

Usage:
    python scripts/evaluate_feedback.py \
        --performance ../frontend/public/data/performance.json \
        --out ../docs/feedback/feedback-latest.json \
        --report ../docs/feedback/feedback-report.md

Exit codes:
    0  feedback written
    1  invalid arguments / unreadable inputs
    2  nothing evaluable (no closed rows with sub_scores)
"""

import argparse
import json
import random
import sys
from collections import defaultdict
from datetime import UTC, datetime, timezone
from pathlib import Path

_PATH_BOOTSTRAP_DONE = False


def _bootstrap_path() -> None:
    """Make backend modules importable regardless of invocation cwd."""
    global _PATH_BOOTSTRAP_DONE
    if _PATH_BOOTSTRAP_DONE:
        return
    here = Path(__file__).resolve().parent
    backend = here.parent
    for p in (str(backend), str(here)):
        if p not in sys.path:
            sys.path.insert(0, p)
    _PATH_BOOTSTRAP_DONE = True


_bootstrap_path()
from performance import cohort_stats, score_bucket  # noqa: E402
from settings import WEIGHTS  # noqa: E402  (backend/settings.py)

WINDOWS = ["T+5", "T+10", "T+20"]
IC_MIN_N = 30  # below this, an IC is reported but flagged unusable
CI_MIN_N = 20  # cohort_stats CI suppression threshold (mirrors UI)
BOOTSTRAP_RESAMPLES = 300
BOOTSTRAP_SEED = 42
SUB_SCORE_KEYS = sorted(WEIGHTS.keys())

PROMOTION_CHECKLIST = [
    (
        "Out-of-sample: the candidate weights beat baseline on the tracker's "
        "top-band mean excess for 4 consecutive weekly runs (not just this "
        "in-sample report)."
    ),
    ("The candidate's top-band (63+) T+5 mean CI sits above the baseline's, with n >= 20 in both."),
    ("No band's hit rate regresses by more than 5 points without a documented trade-off rationale."),
    (
        "The weight change is a single commit touching only "
        "backend/settings.py WEIGHTS + CHANGELOG.md, so the tracker can "
        "attribute the regime change to score_version."
    ),
]


# --------------------------------------------------------------------------
# Stats primitives (stdlib only)
# --------------------------------------------------------------------------


def _ranks(xs):
    """Average ranks, 1-based, ties averaged."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    n = len(order)
    while i < n:
        j = i
        while j + 1 < n and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return cov / ((vx * vy) ** 0.5)


def spearman_ic(xs, ys):
    """Spearman rank correlation; None when degenerate."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    return _pearson(_ranks(xs), _ranks(ys))


def _ic_bootstrap_ci(pairs, resamples=BOOTSTRAP_RESAMPLES, seed=BOOTSTRAP_SEED):
    """Deterministic percentile CI for the Spearman IC of (x, y) pairs."""
    if len(pairs) < IC_MIN_N:
        return None
    rng = random.Random(seed)
    n = len(pairs)
    ics = []
    for _ in range(resamples):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        ic = spearman_ic([p[0] for p in sample], [p[1] for p in sample])
        if ic is not None:
            ics.append(ic)
    if len(ics) < resamples * 0.8:
        return None
    ics.sort()
    lo = ics[max(0, int(0.025 * len(ics)) - 1)]
    hi = ics[min(len(ics) - 1, int(0.975 * len(ics)))]
    return [round(lo, 3), round(hi, 3)]


def subscore_ics(rows, window):
    """IC per sub-score key for one window over closed, labelled rows."""
    out = {}
    for key in SUB_SCORE_KEYS:
        pairs = []
        for r in rows:
            sub = (r.get("sub_scores") or {}).get(key)
            w = (r.get("windows") or {}).get(window) or {}
            v = w.get("excess_return_pct")
            if isinstance(sub, (int, float)) and isinstance(v, (int, float)) and not w.get("untrackable"):
                pairs.append((float(sub), float(v)))
        ic = spearman_ic([p[0] for p in pairs], [p[1] for p in pairs])
        out[key] = {
            "ic": round(ic, 3) if ic is not None else None,
            "ci95": _ic_bootstrap_ci(pairs),
            "n": len(pairs),
            "usable": len(pairs) >= IC_MIN_N and ic is not None,
        }
    return out


def confirmation_ab(rows, window="T+5"):
    """Confirmed vs anticipatory outcome cohorts (reuse tracker stats)."""
    groups = {"confirmed": [], "anticipatory": []}
    for r in rows:
        state = r.get("confirmation")
        w = (r.get("windows") or {}).get(window) or {}
        v = w.get("excess_return_pct")
        if state in groups and isinstance(v, (int, float)) and not w.get("untrackable"):
            groups[state].append(float(v))
    return {k: cohort_stats(v) for k, v in groups.items()}


# --------------------------------------------------------------------------
# Shadow re-scoring
# --------------------------------------------------------------------------


def _shadow_score(sub_scores, weights):
    """Mirror scanner.py's renormalised weighted blend (100x scale)."""
    num, den = 0.0, 0.0
    for k, w in weights.items():
        v = sub_scores.get(k)
        if isinstance(v, (int, float)):
            num += float(v) * w
            den += w
    return 100.0 * num / den if den > 0 else None


def _normalize(weights):
    total = sum(weights.values())
    if total <= 0:
        msg = "candidate weights must sum to a positive value"
        raise ValueError(msg)
    return {k: w / total for k, w in weights.items()}


def ic_proportional_weights(ics):
    """Candidate weights proportional to positive evidence (T+5 IC), with a
    smoothing floor so no component is fully amputated on one regime's data."""
    raw = {}
    for k in SUB_SCORE_KEYS:
        ic = (ics.get("T+5", {}).get(k) or {}).get("ic")
        raw[k] = max(ic if isinstance(ic, (int, float)) else 0.0, 0.0) + 0.02
    return _normalize(raw)


def shadow_compare(rows, candidates):
    """Re-score every closed row under each candidate weight set and compare
    band-level outcomes. Baseline scores are ALSO recomputed from sub_scores
    so differences come from weights, not data availability."""
    usable = [
        r
        for r in rows
        if isinstance(r.get("sub_scores"), dict) and any(isinstance(v, (int, float)) for v in r["sub_scores"].values())
    ]
    buckets = {w: {c: defaultdict(list) for c in candidates} for w in WINDOWS}
    mismatch = 0
    for r in usable:
        sub = {k: float(v) for k, v in r["sub_scores"].items() if isinstance(v, (int, float))}
        base_score = _shadow_score(sub, candidates["baseline"])
        if base_score is None:
            continue
        stored = r.get("score")
        if isinstance(stored, (int, float)) and abs(base_score - stored) > 5.0:
            mismatch += 1
        for w in WINDOWS:
            cell = (r.get("windows") or {}).get(w) or {}
            v = cell.get("excess_return_pct")
            if not isinstance(v, (int, float)) or cell.get("untrackable"):
                continue
            for cname, cweights in candidates.items():
                score = base_score if cname == "baseline" else _shadow_score(sub, cweights)
                if score is None:
                    continue
                buckets[w][cname][score_bucket(score)].append(float(v))
    result = {
        "rows_used": len(usable),
        "baseline_score_mismatch_gt5": mismatch,
        "windows": {},
    }
    for w in WINDOWS:
        result["windows"][w] = {
            cname: {
                b: {
                    "n": len(vs),
                    "mean": round(sum(vs) / len(vs), 2) if vs else None,
                    "hit_rate": round(sum(1 for v in vs if v > 0) / len(vs), 3) if vs else None,
                }
                for b, vs in sorted(per_bucket.items())
            }
            for cname, per_bucket in buckets[w].items()
        }
    return result


def top_band_lift(shadow, window="T+5", band="63+"):
    """Mean excess of a candidate's top band vs baseline's, same rows basis."""
    out = {}
    cell = shadow["windows"].get(window, {})
    base = (cell.get("baseline", {}).get(band) or {}).get("mean")
    for cname, per_bucket in cell.items():
        if cname == "baseline":
            continue
        cand = (per_bucket.get(band) or {}).get("mean")
        if isinstance(base, (int, float)) and isinstance(cand, (int, float)):
            out[cname] = round(cand - base, 2)
        else:
            out[cname] = None
    return out


# --------------------------------------------------------------------------
# Assembly + report
# --------------------------------------------------------------------------


def build_feedback(perf_path: Path) -> dict:
    with perf_path.open("r", encoding="utf-8") as f:
        perf = json.load(f)
    rows = perf.get("per_name") or []
    closed_rows = [
        r
        for r in rows
        if any(
            isinstance(((r.get("windows") or {}).get(w) or {}).get("excess_return_pct"), (int, float))
            and not ((r.get("windows") or {}).get(w) or {}).get("untrackable")
            for w in WINDOWS
        )
    ]

    ics = {w: subscore_ics(rows, w) for w in WINDOWS}
    candidates = {"baseline": _normalize(dict(WEIGHTS))}
    try:
        candidates["ic_proportional"] = ic_proportional_weights(ics)
    except ValueError:
        candidates["ic_proportional"] = None
    candidates = {k: v for k, v in candidates.items() if v}

    shadow = shadow_compare(rows, candidates) if closed_rows else {"rows_used": 0, "windows": {}}

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "meta": {
            "rows_total": len(rows),
            "rows_closed_any_window": len(closed_rows),
            "ic_min_n": IC_MIN_N,
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "baseline_weights": {k: round(v, 4) for k, v in candidates.get("baseline", {}).items()},
            "in_sample": True,
        },
        "subscore_ic": ics,
        "confirmation_ab": {w: confirmation_ab(rows, w) for w in WINDOWS},
        "shadow": shadow,
        "top_band_lift": {w: top_band_lift(shadow, w) for w in WINDOWS},
        "promotion_checklist": PROMOTION_CHECKLIST,
    }


def render_report(fb: dict) -> str:
    L = []
    ap = L.append
    ap("# Feedback loop report")
    ap("")
    ap(
        f"_Generated {fb['generated_at'][:10]} from "
        f"{fb['meta']['rows_closed_any_window']} closed rows "
        f"(of {fb['meta']['rows_total']}). IN-SAMPLE — read with the "
        "promotion checklist, not instead of it._"
    )
    ap("")
    for w in WINDOWS:
        ap(f"## Sub-score rank IC — {w}")
        ap("")
        ap("| Sub-score | IC | 95% CI | n | usable |")
        ap("|---|---|---|---|---|")
        for k in SUB_SCORE_KEYS:
            cell = fb["subscore_ic"][w][k]
            ci = cell["ci95"]
            ap(
                f"| {k} | {cell['ic']} "
                f"| {f'[{ci[0]}, {ci[1]}]' if ci else '—'} "
                f"| {cell['n']} | {'yes' if cell['usable'] else 'no'} |"
            )
        ap("")
    ap("## Confirmation A/B")
    ap("")
    ap("| Window | Confirmed mean (n) | Anticipatory mean (n) |")
    ap("|---|---|---|")
    for w in WINDOWS:
        c = fb["confirmation_ab"][w]["confirmed"]
        a = fb["confirmation_ab"][w]["anticipatory"]
        ap(f"| {w} | {c['mean']} ({c['n']}) | {a['mean']} ({a['n']}) |")
    ap("")
    ap("## Shadow re-scoring (in-sample)")
    ap("")
    for w in WINDOWS:
        lift = fb["top_band_lift"][w]
        if not lift:
            continue
        parts = ", ".join(f"{k}: {v:+.2f}pp" if isinstance(v, (int, float)) else f"{k}: n/a" for k, v in lift.items())
        ap(f"- Top-band lift vs baseline at {w}: {parts}")
    ap("")
    ap("Full band tables live in `feedback-latest.json` (`shadow.windows`).")
    ap("")
    ap("## Promotion checklist")
    ap("")
    for item in fb["promotion_checklist"]:
        ap(f"- [ ] {item}")
    ap("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="Evaluate the feedback loop evidence for the scoring weights.")
    ap.add_argument("--performance", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", default=None, help="Also write a human-readable markdown report")
    args = ap.parse_args()

    perf_path = Path(args.performance)
    if not perf_path.is_file():
        print(f"error: performance file not found: {perf_path}", file=sys.stderr)
        return 1

    try:
        fb = build_feedback(perf_path)
    except (json.JSONDecodeError, KeyError) as exc:
        print(f"error: unreadable performance.json: {exc}", file=sys.stderr)
        return 1

    if fb["meta"]["rows_closed_any_window"] == 0:
        print("nothing to evaluate: no closed-window rows", file=sys.stderr)
        return 2

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(fb, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")

    if args.report:
        rep_path = Path(args.report)
        rep_path.parent.mkdir(parents=True, exist_ok=True)
        rep_path.write_text(render_report(fb), encoding="utf-8")
        print(f"wrote {rep_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
