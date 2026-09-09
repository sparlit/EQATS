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
generate_digest.py
Public weekly digest of the scanner's measured accuracy. Implements the
distribution workstream agreed in the product review (Sep 2026): the
outcome tracker already computes per-cohort attribution; this renders it
as a committed, linkable markdown artifact under docs/digests/.

Behaviour:
  - Reads performance.json (per_name rows + bucket aggregates).
  - Composes docs/digests/YYYY-Www.md: headline numbers per pass_v3 band,
    best/worst calls of the week, regime mix, and the honest caveats.
  - Deterministic output: same inputs -> byte-identical digest (safe to
    commit from CI, diffable).
  - Stdlib only; no network. CI guard smoke-runs it with --help.

Required arguments:
  --performance PATH   performance.json produced by compute_performance.py
  --out PATH           Output markdown file (e.g. docs/digests/2026-W36.md)

Optional:
  --site-base URL      Prepend "{site_base}/..." links (default: none)
  --week YYYY-Www      Force the digest week (default: ISO week of the
                       payload's generated_at)

Exit codes:
  0  digest written
  1  invalid arguments / unreadable inputs
  2  nothing digestable (no per_name rows with closed windows)
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

# pass_v3 display order (matches performance.py; unknown excluded).
BUCKET_ORDER = ["63+", "60-63", "55-60", "45-55", "<45"]
WINDOWS = ["T+5", "T+10", "T+20"]
MIN_CI_N = 20  # below this, refuse to headline a band's numbers

CAVEATS = (
    "Overlapping windows inflate cross-band agreement; cohorts are not "
    "independent. Excess returns are vs Nifty 50 over the same window. "
    "Single market regime so far. This is a scoreboard of past "
    "suggestions, not investment advice or a promise of future returns."
)


def _iso_week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _monday_of_iso_week(label: str) -> date:
    year, week = label.split("-W")
    d = date(int(year), 1, 4)
    d -= timedelta(days=d.isoweekday() - 1)  # Monday of ISO week 1
    return d + timedelta(weeks=int(week) - 1)


def _fmt(v) -> str:
    return "—" if v is None else f"{v:+.2f}%"


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def _path_bootstrap() -> None:
    """Make backend modules importable regardless of how we were invoked."""
    here = Path(__file__).resolve().parent
    backend = here.parent
    for p in (str(backend), str(here)):
        if p not in sys.path:
            sys.path.insert(0, p)


def load_rows(perf_path: Path):
    with perf_path.open("r", encoding="utf-8") as f:
        perf = json.load(f)
    meta = perf.get("meta") or {}
    rows = perf.get("per_name") or []
    return perf, meta, rows


def closed(row: dict, window: str):
    """Excess return when the window closed and the name was trackable."""
    w = (row.get("windows") or {}).get(window) or {}
    if w.get("untrackable"):
        return None
    v = w.get("excess_return_pct")
    return v if isinstance(v, (int, float)) else None


def band_tables(rows):
    """Per (window, bucket) mean/hit/n from closed rows, from scratch."""
    cells = defaultdict(list)
    for r in rows:
        bucket = r.get("bucket")
        if bucket not in BUCKET_ORDER:
            continue  # 'unknown' and anything unexpected: never headlined
        for w in WINDOWS:
            v = closed(r, w)
            if v is not None:
                cells[(w, bucket)].append(v)
    out = {}
    for (w, bucket), vals in cells.items():
        n = len(vals)
        out[(w, bucket)] = {
            "n": n,
            "mean": sum(vals) / n,
            "hit_rate": sum(1 for v in vals if v > 0) / n,
        }
    return out


def week_rows(rows, week_label: str):
    """Rows whose snapshot falls inside the digest week (per_name snapshot
    labels are YYYY-MM-DD-slot)."""
    monday = _monday_of_iso_week(week_label)
    sunday = monday + timedelta(days=6)
    picked = []
    for r in rows:
        snap = str(r.get("snapshot") or "")
        day = snap[:10]
        try:
            d = date.fromisoformat(day)
        except ValueError:
            continue
        if monday <= d <= sunday:
            picked.append(r)
    return picked


def best_and_worst(week_rows_):
    """Best/worst T+5 closed calls of the week (ties broken by symbol)."""
    scored = []
    for r in week_rows_:
        v = closed(r, "T+5")
        if v is not None:
            scored.append((v, str(r.get("symbol")), str(r.get("snapshot"))))
    if not scored:
        return None, None
    scored.sort(key=lambda t: (-t[0], t[1]))
    return scored[0], scored[-1]


def _cell(tables, w, bucket, key):
    return tables.get((w, bucket), {}).get(key)


def render_digest(week_label: str, perf, meta, rows, tables, week_rows_, site_base: str | None) -> str:
    gen_at = perf.get("generated_at") or "unknown"
    total_pass = meta.get("total_passed")
    n_rows = len(rows)
    lines = []
    ap = lines.append
    scope = (
        f"across {meta.get('snapshots_used')} scans"
        if total_pass and total_pass == n_rows
        else f"{total_pass} gate-passed across {meta.get('snapshots_used')} scans"
        if total_pass
        else ""
    )
    ap(f"# Weekly digest — {week_label}")
    ap("")
    ap(
        f"_Generated from the forward-return tracker on {gen_at[:10]}. "
        f"{n_rows} tracked suggestions since inception" + (f" ({scope})" if scope else "") + ". _"
    )
    ap("")

    # Headline: only bands whose T+5 cohort is large enough to headline.
    ap("## The scoreboard")
    ap("")
    ap("Mean excess return vs Nifty 50, all closed windows to date:")
    ap("")
    ap("| Band | T+5 mean (n) | T+5 hit rate | T+10 mean (n) | T+20 mean (n) |")
    ap("|---|---|---|---|---|")
    for b in BUCKET_ORDER:
        t5n = _cell(tables, "T+5", b, "n") or 0
        t5m = _fmt(_cell(tables, "T+5", b, "mean"))
        t5h = _pct(_cell(tables, "T+5", b, "hit_rate"))
        t10 = f"{_fmt(_cell(tables, 'T+10', b, 'mean'))} ({_cell(tables, 'T+10', b, 'n') or 0})"
        t20 = f"{_fmt(_cell(tables, 'T+20', b, 'mean'))} ({_cell(tables, 'T+20', b, 'n') or 0})"
        flag = " **" if t5n >= MIN_CI_N else ""
        end = "**" if flag else ""
        ap(f"| {flag}{b}{end} | {t5m} ({t5n}) | {t5h} | {t10} | {t20} |")
    ap("")
    ap(
        f"Bands in bold have at least {MIN_CI_N} closed T+5 outcomes; "
        "smaller cohorts are shown but not headlined. The dashboard's "
        "confidence intervals are the authoritative view — this table is "
        "the weekly snapshot of it."
    )
    ap("")

    # This week's calls.
    ap("## This week's calls")
    ap("")
    if week_rows_:
        best, worst = best_and_worst(week_rows_)
        ap(f"- Suggestions this week: **{len(week_rows_)}**")
        regimes = defaultdict(int)
        for r in week_rows_:
            regimes[str(r.get("regime"))] += 1
        ap("- Regime mix: " + ", ".join(f"{k} ×{v}" for k, v in sorted(regimes.items())))
        if best:
            v, sym, snap = best
            ap(f"- Best T+5 close: **{sym}** {_fmt(v)} (from {snap})")
        if worst and (not best or worst[1] != best[1]):
            v, sym, snap = worst
            ap(f"- Worst T+5 close: **{sym}** {_fmt(v)} (from {snap})")
        open_count = sum(1 for r in week_rows_ for w in WINDOWS if closed(r, w) is None)
        ap(f"- Windows still open: {open_count} (they close as sessions accrue)")
    else:
        ap(
            "No tracked suggestions have snapshot dates inside this week — "
            "either the tracker has not refreshed since Sunday, or the week "
            "predates tracking."
        )
    ap("")

    # Regime x band note from raw rows.
    ap("## Regime note")
    ap("")
    regime_counts = defaultdict(int)
    for r in rows:
        regime_counts[str(r.get("regime"))] += 1
    if regime_counts.get("risk_on", 0) == 0:
        ap(
            "Every tracked cohort to date formed in neutral or risk-off "
            "regime — the top band's edge has not yet been observed in a "
            "risk-on market. See the band × regime cross-tab on the "
            "dashboard."
        )
    else:
        ap(
            "Risk-on cohorts present: "
            + str(regime_counts.get("risk_on", 0))
            + " of "
            + str(n_rows)
            + ". Compare band × regime cells on the dashboard before "
            "trusting a band across regimes."
        )
    ap("")

    # Links.
    ap("## Links")
    ap("")
    if site_base:
        base = site_base.rstrip("/")
        ap(f"- Live dashboard: {base}")
        ap(f"- Full attribution data: {base}/data/performance.json")
    else:
        ap("- Live dashboard: https://nse-swing-scanner.netlify.app")
        ap("- Full attribution data: /data/performance.json (in-repo: `frontend/public/data/performance.json`)")
    ap("")
    ap(f"> {CAVEATS}")
    ap("")
    return "\n".join(lines)


def build_digest(perf_path: Path, week_label: str | None, site_base: str | None):
    perf, meta, rows = load_rows(perf_path)
    gen_at = perf.get("generated_at")
    if not gen_at:
        msg = "performance.json has no generated_at — refusing to digest"
        raise SystemExit(msg)
    resolved_week = week_label or _iso_week(date.fromisoformat(gen_at[:10]))
    tables = band_tables(rows)
    if not tables:
        return resolved_week, None
    wrows = week_rows(rows, resolved_week)
    return resolved_week, render_digest(resolved_week, perf, meta, rows, tables, wrows, site_base)


def main() -> int:
    ap = argparse.ArgumentParser(description="Render the public weekly accuracy digest.")
    ap.add_argument("--performance", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--week", default=None, help="Override digest week (YYYY-Www)")
    ap.add_argument("--site-base", default=None, help="Dashboard base URL for links")
    args = ap.parse_args()

    perf_path = Path(args.performance)
    if not perf_path.is_file():
        print(f"error: performance file not found: {perf_path}", file=sys.stderr)
        return 1

    try:
        resolved_week, body = build_digest(perf_path, args.week, args.site_base)
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        print(f"error: unreadable performance.json: {exc}", file=sys.stderr)
        return 1

    if body is None:
        print("nothing to digest: no closed-window rows in per_name", file=sys.stderr)
        return 2

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    print(f"wrote {out_path} ({resolved_week}, {len(body)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
