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
"""N500 COVERAGE-100 — Phase 2 adjudicator: give EVERY queue row a class, with per-name evidence.

Campaign: scripts/N500_COVERAGE_100_CAMPAIGN.md

WHAT IT DECIDES, AND WHAT IT REFUSES TO DECIDE
  Only class C3 (PRE-HISTORY) can be settled by measurement alone, because "the input could not have
  existed at this date" is a fact about the symbol's own first bar / oldest filing — not a claim
  about the outside world. Everything else needs a source read, and this tool marks it
  `needs-source` rather than guessing. That split is the whole point: a measured verdict and an
  assumed one must never end up in the same field.

  ⚠️ C3 is decided against OUR OWN OLDEST ROW, which is exactly the reasoning
  `feedback-never-infer-absence-from-own-gaps` warns about — so it is allowed ONLY where the
  quantity is defined relative to the company's own history (an 8-quarter TTM cannot exist 3
  quarters after the first filing that exists anywhere). Where the missing input is a quarter that
  the company plausibly DID file and we simply lack, the row stays `needs-source`. The builder's own
  profitYoy* rule draws the same line (build_coverage_matrix.js:461-463, the CELLO case).

INPUTS   scripts/n500_cov_queue.json, scripts/n500_cov_facts.json (from --facts), sf_fundamentals,
         sf_revop, shp_engine, coverage_na_ledger
OUTPUT   rewrites n500_cov_queue.json with class / evidence / status filled, and prints the split
"""
import argparse
import collections
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS, SCRIPTS = os.path.join(ROOT, "docs"), os.path.join(ROOT, "scripts")
TODAY = datetime.date.today().isoformat()

_ap = argparse.ArgumentParser()
_ap.add_argument(
    "--queue",
    default=os.path.join(SCRIPTS, "n500_cov_queue.json"),
    help="queue file to adjudicate IN PLACE (era campaigns pass their own)",
)
_ap.add_argument("--facts", default=os.path.join(SCRIPTS, "n500_cov_facts.json"))
_A = _ap.parse_args()

QUEUE_PATH = _A.queue
Q = json.load(open(QUEUE_PATH))
F = json.load(open(_A.facts))
FUNDJ = json.load(open(os.path.join(DOCS, "sf_fundamentals.json")))
REVOP = json.load(open(os.path.join(DOCS, "sf_revop.json")))
LEDGER = json.load(open(os.path.join(SCRIPTS, "coverage_na_ledger.json")))

SER, FUND, SHP = F["series"], F["fund"], F["shp"]


def prev_qe(qe):
    y, m = qe // 10000, (qe // 100) % 100
    m -= 3
    if m <= 0:
        m += 12
        y -= 1
    return y * 10000 + m * 100 + {3: 31, 6: 30, 9: 30, 12: 31}[m]


def visible_quarters(sym, dateint):
    """Quarters of this symbol FILED on or before dateint, by the same ann>0 rule the builder uses."""
    out = []
    for q in FUNDJ.get(sym, []):
        anns = [x for x in (q[2], q[4]) if isinstance(x, (int, float)) and x > 0]
        if anns and min(anns) <= dateint:
            out.append(q[0])
    return sorted(out)


def facts_line(sym):
    s, f, h = SER.get(sym, {}), FUND.get(sym, {}), SHP.get(sym, {})
    return (
        f"firstBar={s.get('firstBar', '?')} · fundRows={f.get('nRows', 0)}"
        f" oldestQe={f.get('oldestQe', '?')} · shpRows={h.get('nRows', 0)}"
        f" firstSub={h.get('firstSub', '?')}"
    )


# How far BACK of the current (latest visible) quarter each parameter reaches, in quarters.
# ⚠️ The test is NOT "how many quarters have been filed" — that conflates "this company is young"
# with "this specific quarter is missing". It is the builder's own test (build_coverage_matrix.js
# :461-463): is the quarter the parameter reaches for OLDER than the oldest row this symbol has?
# If yes the input predates the company's existence as this entity (C3). If it falls INSIDE the
# symbol's own span, the quarter should be there and is not — a hole in the middle, which is a real
# gap. CELLO is the worked case the builder calls out by name: it needs 2022-12 while holding rows
# from 2022-06, and is deliberately NOT marked N/A. A count-based rule would have buried it.
NEEDS = {
    "profitTTM": ("8 consecutive filed quarters (4 vs the prior 4)", 7),
    "composite": ("profitTTM, so the same 8 quarters", 7),
    "profitAccel": ("quarters t, t-1, t-4 and t-5", 5),
    "profitYoyPct": ("the same quarter a year earlier (t-4)", 4),
    "profitBase": ("the same quarter a year earlier (t-4)", 4),
    "profitStreak": ("the same quarter a year earlier (t-4)", 4),
}

out_rows, split = [], collections.Counter()
for r in Q["rows"]:
    param, sym, months = r["param"], r["symbol"], r["months"]
    cls = evidence = None
    status = "open"

    # ---- C3: the symbol's own history cannot reach back far enough at the FIRST affected date ----
    if param in NEEDS:
        desc, back = NEEDS[param]
        oldest = FUND.get(sym, {}).get("oldestQe")
        first_bar = SER.get(sym, {}).get("firstBar", "?")
        # Adjudicate EVERY affected month, not just the first: a young company crosses from
        # pre-history into real-gap territory partway through its run of missing cells, and the
        # months on either side of that line deserve different verdicts.
        pre, hole = [], []
        for mo in months:
            di = int(mo.replace("-", ""))
            vis = visible_quarters(sym, di)
            if not vis:
                pre.append(mo)
                continue
            need = vis[-1]
            for _ in range(back):
                need = prev_qe(need)
            (pre if (oldest and need < oldest) else hole).append(mo)
        if hole:
            cls, status = "needs-source", "open"
            evidence = (
                f"REAL HOLE (measured {TODAY}): needs {desc}. On {len(hole)} of "
                f"{len(months)} affected month-ends the quarter it reaches for falls INSIDE "
                f"this symbol's own span (oldest row {oldest}) — it should be on file and "
                f"is not. {'The other ' + str(len(pre)) + ' month-end(s) are pre-history. ' if pre else ''}"
                f"First hole {hole[0]}. [{facts_line(sym)}]"
            )
        else:
            cls, status = "C3", "adjudicated-na"
            evidence = (
                f"PRE-HISTORY (measured {TODAY}): needs {desc}. On every one of the "
                f"{len(months)} affected month-ends that quarter predates this symbol's "
                f"oldest row ({oldest}); first traded bar {first_bar}. The input never "
                f"existed for this entity — not a gap to fill. [{facts_line(sym)}]"
            )

    # ---- revenue family -------------------------------------------------------------------
    elif param in ("rev", "op", "ebit"):
        rmap = REVOP.get(sym, {})
        nq = len(rmap)
        slot = {"rev": (1, 0), "op": (3, 2), "ebit": (8, 7)}[param]
        have = sum(
            1
            for c in rmap.values()
            if (len(c) > slot[0] and c[slot[0]] is not None) or (len(c) > slot[1] and c[slot[1]] is not None)
        )
        # A ledger verdict may carry from/to bounds (format belongs to the FILING, not the company
        # — BAJFINANCE flips F/N both directions). Months OUTSIDE the bounds are NOT covered by the
        # verdict: only a row whose every month the entry actually covers may inherit C1. A partial
        # overlap means the queue and the ledger disagree about the bake — flag, don't guess.
        entry = LEDGER.get(param, {}).get(sym)
        led_months = (
            [
                mo
                for mo in months
                if entry
                and not (entry.get("from") and mo < entry["from"])
                and not (entry.get("to") and mo > entry["to"])
            ]
            if entry
            else []
        )
        d0 = int(months[0].replace("-", ""))
        vis0 = visible_quarters(sym, d0)
        if entry and len(led_months) == len(months):
            cls, status = "C1", "adjudicated-na"
            evidence = entry["reader_1"]
        elif entry and led_months:
            cls, status = "needs-source", "open"
            evidence = (
                f"LEDGER/BAKE SKEW: {len(led_months)} of {len(months)} months fall inside "
                f"the {param} ledger entry's bounds (from={entry.get('from')}, "
                f"to={entry.get('to')}) yet the bake counted them missing, not N/A. "
                f"Re-bake before adjudicating. [{facts_line(sym)}]"
            )
        elif not vis0 and FUND.get(sym, {}).get("oldestQe"):
            cls, status = "C3", "adjudicated-na"
            evidence = (
                f"PRE-HISTORY (measured {TODAY}): no quarter of this symbol had been FILED "
                f"on or before {months[0]} (oldest row {FUND[sym]['oldestQe']}, first filing "
                f"postdates the month-end), so there is no visible quarter to carry a "
                f"{param}. [{facts_line(sym)}]"
            )
        else:
            cls, status = "needs-source", "open"
            evidence = (
                f"{param} present in {have} of {nq} sf_revop quarters; {len(vis0)} quarters "
                f"visible at {months[0]}. Needs a source read per name. [{facts_line(sym)}]"
            )

    # ---- shareholding change --------------------------------------------------------------
    elif param in ("fiiChgPp", "diiChgPp"):
        h = SHP.get(sym, {})
        d0 = int(months[0].replace("-", ""))
        if h.get("firstSub") and h["firstSub"] > d0:
            cls, status = "C3", "adjudicated-na"
            evidence = (
                f"PRE-HISTORY (measured {TODAY}): first shareholding filing submitted "
                f"{h['firstSub']}, after {months[0]}. [{facts_line(sym)}]"
            )
        else:
            cls, status = "needs-source", "open"
            evidence = (
                f"A prior-quarter filing is missing for the QoQ. shpRows={h.get('nRows', 0)}, "
                f"firstSub={h.get('firstSub', '?')}. Needs the SHP source per name — "
                f"coordinate with PLAN_SHP_4DP_FULL.md. [{facts_line(sym)}]"
            )

    elif param == "delivPct":
        cls, status = "needs-source", "open"
        evidence = (
            f"No bar in the trailing 20 days carried a delivery figure at {months[0]}. "
            f"Needs the MTO volume-identity route (runbook §88b). [{facts_line(sym)}]"
        )
    else:
        cls, status = "needs-source", "open"
        evidence = f"unclassified param {param}. [{facts_line(sym)}]"

    r = dict(r)
    r["class"], r["evidence"], r["status"] = cls, evidence, status
    out_rows.append(r)
    split[(param, cls)] += r["n"]

Q["rows"] = out_rows
Q["adjudicated"] = TODAY
json.dump(Q, open(QUEUE_PATH, "w"), indent=1)

print(f"adjudicated {len(out_rows)} rows / {sum(r['n'] for r in out_rows)} cells\n")
print(f"{'param':14s} {'class':14s} {'cells':>6s} {'names':>6s}")
names = collections.Counter()
for r in out_rows:
    names[(r["param"], r["class"])] += 1
for (p, c), n in sorted(split.items()):
    print(f"{p:14s} {c:14s} {n:6d} {names[(p, c)]:6d}")
print()
tot_na = sum(n for (p, c), n in split.items() if c in ("C1", "C3"))
tot_src = sum(n for (p, c), n in split.items() if c == "needs-source")
print(f"ADJUDICATED N/A (measured)      {tot_na:5d} cells")
print(f"NEEDS A SOURCE READ (real work) {tot_src:5d} cells")
print(f"rows still `open`: {sum(1 for r in out_rows if r['status'] == 'open')}")
