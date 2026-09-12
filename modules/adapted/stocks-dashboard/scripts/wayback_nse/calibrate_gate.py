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


# -*- coding: utf-8 -*-
"""HOLD-OUT calibration of THE gate (wbgate.judge) against cells we ALREADY hold.

Measures the only number that licenses a write: of the cells the gate WOULD WRITE, how many
disagree with what we store? Run it before landing anything, and re-run it whenever a gate clause
is relaxed (runbook §112f).

★★ EXCLUDE EVERY AGGREGATOR-DERIVED CELL FROM THE TRUTH SIDE, not just this campaign's.
`--exclude-agg` walks the aggregator ledgers BY GLOB (agg_pat_cell_fills, mc_*_fills,
fav14_pat_std_fills — ~12,000 cells) and drops them. Measured 2026-08-26: with only this session's
fills excluded the harness still read 7.14% on two-token pages, and the single mismatch
(AJANTPHARM Mar-02, ours 0.79 vs archive 0.99) turned out to be a Moneycontrol cell landed by an
EARLIER campaign on 2026-08-12. So the contamination is not just "today's work" — this era's store
is substantially aggregator-derived, and a calibration that does not filter on PROVENANCE is
measuring MC against MC and reporting the agreement as validation. A random split of a contaminated
pool is still contaminated.

★ EXCLUDE THE CURRENT CAMPAIGN'S OWN FILLS. A hold-out is only a hold-out if the "truth" side is
independent of the work being validated, and in a shared store that stops being true within HOURS.
Measured 2026-08-26: the first run of this harness read 12% mismatch on two-token pages, and all
three misses were Moneycontrol cells the SAME SESSION had landed a few hours earlier. Excluding
them: 91 writes, 0 mismatches. Pass --exclude <props.json> with the proposals file of any batch
this campaign has already applied.

⚠️ Its other limit, which must travel with the number: cells we already hold skew to WELL-COVERED
companies, while the cells actually wanted have no stored value to check against. The measured
mismatch rate is a LOWER bound on the rate that matters.

  python3 -X utf8 scripts/wayback_nse/calibrate_gate.py --n 200 [--seed 5] [--exclude props.json]
"""
import collections
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from wbcache import fetch_cached  # noqa: E402
from wbgate import judge  # noqa: E402


def main():
    av = sys.argv
    n = int(av[av.index("--n") + 1]) if "--n" in av else 200
    seed = int(av[av.index("--seed") + 1]) if "--seed" in av else 5
    excl = set()
    if "--exclude-agg" in av:
        import glob

        for path in (
            glob.glob(os.path.join(ROOT, "scripts", "agg_pat_cell_fills.json"))
            + glob.glob(os.path.join(ROOT, "scripts", "mc_*_fills.json"))
            + glob.glob(os.path.join(ROOT, "scripts", "fav14_pat_std_fills.json"))
        ):
            try:
                d = json.load(open(path))
            except Exception:
                continue
            if isinstance(d.get("fills"), dict):  # nested {SYM:{QE:[...]}}
                for sym, qs in d["fills"].items():
                    for qe in qs:
                        excl.add((sym, int(qe)))
            else:
                for k in d:
                    if "|" in k:
                        a, b = k.rsplit("|", 1)
                        if b.isdigit():
                            excl.add((a, int(b)))
        print(f"provenance filter: {len(excl)} aggregator-derived cells excluded from the TRUTH side")
    if "--exclude" in av:
        for path in av[av.index("--exclude") + 1].split(","):
            for k in json.load(open(path)).get("proposals") or {}:
                p = k.split("|")
                excl.add((p[0], int(p[1])))
        print(f"excluding {len(excl)} cells this campaign already wrote")

    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))
    idx = json.load(open(os.path.join(HERE, "_wb_index.json")))
    std = {}
    for s, rows in fund.items():
        for r in rows:
            if len(r) > 1 and r[1] is not None:
                std[(s, r[0])] = r[1]

    cands = [
        k
        for k in idx
        if (k.split("|")[0], int(k.split("|")[1])) in std and (k.split("|")[0], int(k.split("|")[1])) not in excl
    ]
    random.seed(seed)
    random.shuffle(cands)

    per, mism, refused = collections.defaultdict(collections.Counter), [], collections.Counter()
    for k in cands:
        if sum(c["write"] for c in per.values()) >= n:
            break
        sym, qe = k.split("|")[0], int(k.split("|")[1])
        val, why, p = judge(sym, fetch_cached(*idx[k]))
        if val is None:
            refused[why.split(":")[0][:44]] += 1
            continue
        ntok = len([x for x in (p.get("result_type") or "").split(",") if x.strip()])
        rev = "2-token(no basis axis)" if ntok < 3 else "3-token"
        ours = std[(sym, qe)]
        ok = abs(val - ours) <= max(0.05, 0.01 * abs(ours))
        per[rev]["write"] += 1
        per[rev]["match" if ok else "mismatch"] += 1
        if not ok:
            mism.append((sym, qe, rev, val, ours))

    tw = sum(c["write"] for c in per.values())
    tm = sum(c["mismatch"] for c in per.values())
    print("=== HOLD-OUT of THE gate (wbgate.judge) ===")
    for rev, c in sorted(per.items()):
        print(
            f"  {rev:24s} write {c['write']:4d}  match {c['match']:4d}  "
            f"mismatch {c['mismatch']:3d} = {100 * c['mismatch'] / max(1, c['write']):.2f}%"
        )
    print(f"  {'TOTAL':24s} write {tw:4d}  mismatch {tm:3d} = {100 * tm / max(1, tw):.2f}%")
    print("refused:", dict(refused.most_common()))
    for m in mism:
        print("   MISMATCH", m)


if __name__ == "__main__":
    main()
