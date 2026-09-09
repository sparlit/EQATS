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
"""DERIVE a site's mapping card arithmetically, instead of trusting its row labels.

Phase 1 caught the reason this script exists: Groww publishes a field literally named
`otherDomesticInstitutions.insurance` that is NOT insurance — it is every non-mutual-fund domestic
holding (mf + it == their dii, exactly). Mapping it across by name would have manufactured a
~1.9pp "defect" on every stock we own. Names lie; arithmetic doesn't.

So for each of our fields, this searches the site's printed rows for the SUBSET (size 1-3) whose
SUM best reproduces our value across every overlapping quarter, and reports how well and how
consistently it holds. The output is a candidate mapping card plus the evidence for it — a human
still signs it off, because a good fit on 12 quarters of one era can still be the wrong concept.

Judging: median |delta| picks the winner, but `hold_pct` (share of quarters within tolerance) is
what makes it trustworthy. A mapping with a great median and a poor hold rate is a coincidence
over a narrow window — usually an era boundary (trap T1/T2) hiding inside the sample.

  python3 -X utf8 scripts/shp_verify_mapcard.py --extract p2/screener/screener_pilot.jsonl \
      --pin 93de247c --site screener --out p2/screener_map.json
"""
import argparse
import collections
import itertools
import json
import os
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SLOT = {"prom": 0, "fii": 1, "dii": 2, "mf": 3, "ins": 4, "nsh": 6}
FIELDS = ["prom", "fii", "dii", "mf", "ins", "nsh"]
TOL = {"prom": 0.06, "fii": 0.06, "dii": 0.06, "mf": 0.06, "ins": 0.06, "nsh": 0.0}
MAX_TERMS = 3


def num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("%", "").replace(",", "").replace("−", "-")
    if s in ("", "-", "--", "NA", "N/A", "na", "nil"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def load_hist(pin):
    r = subprocess.run(["git", "show", f"{pin}:scripts/shp_history.json"], capture_output=True, cwd=REPO)
    if r.returncode:
        sys.exit(f"cannot read shp_history.json at {pin}")
    return json.loads(r.stdout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract", required=True)
    ap.add_argument("--pin", default="origin/main")
    ap.add_argument("--site", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--max-terms", type=int, default=MAX_TERMS)
    ap.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="multiply site values before comparing (e.g. 100000 for a 'in Lacs' count column)",
    )
    a = ap.parse_args()

    HIST = load_hist(a.pin)
    obs = []  # [(sym, qe, {label: value}, ours_cell)]
    labels = collections.Counter()
    for line in open(a.extract, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        e = json.loads(line)
        qe = e.get("asof") or ""
        if e.get("event") or qe[5:] not in ("03-31", "06-30", "09-30", "12-31"):
            continue
        cell = HIST.get(e.get("sym"), {}).get(qe)
        if not cell:
            continue
        vals = {k: num(v) for k, v in (e.get("rows") or {}).items()}
        vals = {k: v for k, v in vals.items() if v is not None}
        if not vals:
            continue
        obs.append((e["sym"], qe, vals, cell))
        for k in vals:
            labels[k] += 1

    if not obs:
        sys.exit(f"no overlapping (sym, quarter) rows between {a.extract} and shp_history@{a.pin}")

    # Keep any label with real support. A 50% floor silently dropped Screener's "Promoters" row
    # (absent for MCX and ETERNAL, which have no promoter), and the search then fitted garbage
    # to whatever was left. The per-combo support guard below is what actually protects the fit.
    common = [l for l, n in labels.items() if n >= max(2, 0.2 * len(obs))]
    print(
        "%s: %d comparable stock-quarters, %d labels (%d with >=20%% support)"
        % (a.site, len(obs), len(labels), len(common))
    )

    card = {"site": a.site, "precision": 2, "map": {}, "_derived": {}, "_pin": a.pin, "_comparable_rows": len(obs)}
    if a.scale != 1.0:
        card["scale"] = {"nsh": a.scale}  # carried into the diff engine, which applies it

    def search(field, rows):
        """Best subset of labels whose SUM reproduces our field over `rows`. None if unsupported."""
        slot = SLOT[field]
        pairs = [(o, c) for (o, c) in rows if len(c) > slot and c[slot] is not None]
        if not pairs:
            return None
        best = []
        for r in range(1, a.max_terms + 1):
            for combo in itertools.combinations(sorted(common), r):
                deltas = []
                for vals, cell in pairs:
                    if not all(l in vals for l in combo):
                        continue
                    s = sum(vals[l] for l in combo) * (a.scale if field == "nsh" else 1.0)
                    deltas.append(s - float(cell[slot]))
                if len(deltas) < max(2, 0.5 * len(pairs)):
                    continue
                med = statistics.median(abs(d) for d in deltas)
                if field == "nsh":
                    hold = sum(
                        1
                        for (v, c) in pairs
                        if all(l in v for l in combo)
                        and abs(sum(v[l] for l in combo) * a.scale - float(c[slot]))
                        <= 0.01 * max(1.0, abs(float(c[slot])))
                    ) / len(deltas)
                else:
                    hold = sum(1 for d in deltas if abs(d) <= TOL[field]) / len(deltas)
                best.append((med, -hold, combo, hold, statistics.median(deltas), len(deltas)))
        if not best:
            return None
        best.sort(key=lambda t: (t[0], t[1]))
        return best

    BOUNDARY = "2022-09-30"  # trap T1/T2 — the SEBI taxonomy change
    era_overrides = {}
    for field in FIELDS:
        allrows = [(o, c) for (_s, _q, o, c) in obs]
        best = search(field, allrows)
        if not best:
            continue
        med, _nh, combo, hold, bias, used = best[0]
        entry = {
            "labels": list(combo),
            "median_abs_delta": round(med, 4),
            "hold_pct": round(100 * hold, 1),
            "median_bias": round(bias, 4),
            "rows": used,
            "runners_up": [
                {"labels": list(c), "median_abs_delta": round(m, 4), "hold_pct": round(100 * h, 1)}
                for m, _n, c, h, _b, _u in best[1:4]
            ],
        }
        verdict = "OK" if (med <= TOL[field] and hold >= 0.9) else ("WEAK" if hold >= 0.6 else "NO CREDIBLE MAPPING")
        print(
            "  %-5s <- %-52s med|d|=%-7.4f hold=%5.1f%% bias=%+7.4f  %s"
            % (field, " + ".join(combo)[:52], med, 100 * hold, bias, verdict)
        )

        # A mapping that fits well overall but holds poorly is usually TWO mappings with an era
        # boundary hidden between them (T1: the Sep-2022 taxonomy change; T2: old-format
        # "other institutions"). Split and re-derive rather than reporting one mushy answer.
        if hold < 0.9:
            old = [(o, c) for (_s, q, o, c) in obs if q < BOUNDARY]
            new = [(o, c) for (_s, q, o, c) in obs if q >= BOUNDARY]
            eras = {}
            for tag, subset in (("pre_2022_09", old), ("post_2022_09", new)):
                if len(subset) < 3:
                    continue
                b = search(field, subset)
                if not b:
                    continue
                m2, _n2, c2, h2, b2, u2 = b[0]
                eras[tag] = {
                    "labels": list(c2),
                    "median_abs_delta": round(m2, 4),
                    "hold_pct": round(100 * h2, 1),
                    "median_bias": round(b2, 4),
                    "rows": u2,
                }
                print("        %-13s <- %-38s med|d|=%-7.4f hold=%5.1f%%" % (tag, " + ".join(c2)[:38], m2, 100 * h2))
            if eras:
                entry["eras"] = eras
                # Only adopt a per-era override when the OLD era stands on its own; collected
                # per field and assembled into one era block at the end (the diff engine reads
                # a single map per era, and an entry without a "map" key would crash map_for).
                pre, post = eras.get("pre_2022_09"), eras.get("post_2022_09")
                if pre and pre["hold_pct"] >= 90:
                    era_overrides[field] = pre["labels"]
                    # The base map covers the MODERN era, since `eras` only overrides <=2022-06-30.
                    # Adopting the overall-best combo here would install the mushy cross-era fit
                    # (for Screener that was prom <- "Government", pure noise) as the live mapping.
                    if post and post["hold_pct"] >= 90:
                        verdict, combo = "OK (era-split)", tuple(post["labels"])
                    else:
                        verdict = "PRE-2022 ONLY"

        card["_derived"][field] = entry
        if verdict.startswith("OK") or verdict == "WEAK":
            card["map"][field] = list(combo)
        elif verdict == "PRE-2022 ONLY":
            print("        -> mapped for <=2022-06-30 only; modern era has no credible mapping")

    if era_overrides:
        card["eras"] = [{"from": "0000-00-00", "to": "2022-06-30", "map": era_overrides}]
        print("  era override (<= 2022-06-30): {}".format(", ".join(era_overrides)))

    # name-vs-arithmetic contradiction check (the Groww 'insurance' trap)
    warn = []
    for field, d in card["_derived"].items():
        for lab in common:
            if field in ("mf", "ins") and field[:2] in lab.lower().replace("mutual", "mf")[:400]:
                pass
        if field == "ins":
            named = [l for l in common if "insur" in l.lower()]
            chosen = d["labels"]
            if named and sorted(named) != sorted(chosen) and d["hold_pct"] >= 90:
                warn.append(
                    f"field 'ins': a label named {named} exists but the arithmetic picks {chosen} — "
                    "the site's name does not mean what ours does"
                )
    for w in warn:
        print(f"  ! {w}")
    card["_warnings"] = warn

    if a.out:
        json.dump(card, open(a.out, "w", encoding="utf-8"), indent=1)
        print("wrote {}  (mapped fields: {})".format(a.out, ", ".join(card["map"]) or "NONE"))


if __name__ == "__main__":
    main()
