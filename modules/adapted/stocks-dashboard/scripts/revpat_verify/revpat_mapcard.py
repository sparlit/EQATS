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
"""DERIVE a site's rev/PAT mapping card ARITHMETICALLY. Labels are evidence, never definitions.

The SHP campaign's lesson, ported: Groww publishes `otherDomesticInstitutions.insurance` which is
NOT insurance. Mapping by name manufactured ~1.9pp of defect on every stock. For rev/PAT the same
failure mode has FOUR extra dimensions (campaign doc §1) and a site label of "Net Profit" tells you
none of them:
  T-A which BASIS the column is (standalone or consolidated)
  T-B which PROFIT (owners-attributable, total incl. NCI, pre/post exceptional)
  T-C which SCALE (crore / lakh / million)
  T-D which PERIOD (the quarter, or a YTD printed as one)

So: for every (site label x our field x scale) it measures how well the site column reproduces our
stored series across all overlapping (symbol, quarter) pairs, and picks the winner by hold_pct.
It REFUSES to emit a mapping that does not hold -- "nothing fits" is a valid, reportable answer.

Our fields, per P0 report §2 (authority, NOT the sf_revop PAT mirror):
    revS = sf_revop[sym][qe][0]      revC = sf_revop[sym][qe][1]
    patS = sf_fundamentals npStd     patC = sf_fundamentals npCon

Input: JSONL, one object per (symbol, quarter, basis) observation:
    {"site":"screener","sym":"RELIANCE","basis":"std","qe":"2025-06-30",
     "rows":{"Sales":122627.0,"Net Profit":9627.0}, "url":"...", "unit_declared":"Rs. Crores"}

  python3 -X utf8 revpat_mapcard.py --extract screener_pilot.jsonl --site screener \
      --out screener_map.json
"""
import argparse
import collections
import json
import os
import statistics
import sys

TREE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root of THIS checkout
OURS = ["revS", "revC", "patS", "patC"]
# scale candidates: site prints crore(1), million(/10), lakh(/100), thousand, or raw rupees
SCALES = [
    ("crore", 1.0),
    ("million", 0.1),
    ("lakh", 0.01),
    ("thousand", 0.001),
    ("rupees", 1e-7),
    ("x10", 10.0),
    ("x100", 100.0),
]
# a cell MATCHES when within the larger of an absolute floor and a relative band
ABS_FLOOR = 0.5  # Rs 0.5 crore -- absorbs 2dp-crore rounding differences across sites
REL_BAND = 0.005  # 0.5%
HOLD_MIN = 80.0  # below this the mapping is not emitted


def num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace("−", "-").replace("%", "")
    s = s.replace("(", "-").replace(")", "")  # (123) = negative
    if s in ("", "-", "--", "NA", "N/A", "na", "nil", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def load_ours():
    with open(os.path.join(TREE, "docs/sf_revop.json"), encoding="utf-8") as fh:
        revop = json.load(fh)
    with open(os.path.join(TREE, "docs/sf_fundamentals.json"), encoding="utf-8") as fh:
        fund = json.load(fh)
    ours = collections.defaultdict(dict)  # sym -> qe(int) -> {field: value}
    isfin = set()  # banks/NBFCs: revenue = Interest Earned, not Total Income
    for s, d in revop.items():
        for k, row in d.items():
            try:
                q = int(k)
            except Exception:
                continue
            ours[s][q] = {"revS": row[0], "revC": row[1]}
            if row[6] == 1:
                isfin.add(s)
    for s, rows in fund.items():
        for r in rows:
            if isinstance(r, list) and len(r) >= 5 and isinstance(r[0], int):
                ours[s].setdefault(r[0], {}).update({"patS": r[1], "patC": r[3]})
    return ours, isfin


def qe_int(s):
    s = str(s).strip()
    if len(s) == 10 and s[4] == "-":
        return int(s.replace("-", ""))
    if len(s) == 8 and s.isdigit():
        return int(s)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract", required=True)
    ap.add_argument("--site", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--hold-min", type=float, default=HOLD_MIN)
    a = ap.parse_args()

    ours, isfin = load_ours()
    obs = []
    labels = collections.Counter()
    skipped = collections.Counter()
    for line in open(a.extract, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except Exception:
            skipped["unparseable_line"] += 1
            continue
        q = qe_int(e.get("qe") or "")
        sym = (e.get("sym") or "").upper()
        if not q or not sym:
            skipped["no_sym_or_qe"] += 1
            continue
        if q % 10000 not in (331, 630, 930, 1231):
            skipped["not_a_calendar_quarter_end"] += 1
            continue
        mine = ours.get(sym, {}).get(q)
        if not mine:
            skipped["we_hold_nothing_for_this_cell"] += 1
            continue
        rows = {k: num(v) for k, v in (e.get("rows") or {}).items()}
        rows = {k: v for k, v in rows.items() if v is not None}
        if not rows:
            skipped["no_numeric_rows"] += 1
            continue
        obs.append(
            {
                "sym": sym,
                "qe": q,
                "basis": e.get("basis") or "?",
                "cls": "fin" if sym in isfin else "nonfin",
                "rows": rows,
                "mine": mine,
            }
        )
        for k in rows:
            labels[k] += 1

    if not obs:
        sys.exit(f"no comparable (sym, quarter) rows in {a.extract} -- skipped: {dict(skipped)}")

    print("%s: %d comparable stock-quarters | %d distinct labels" % (a.site, len(obs), len(labels)))
    if skipped:
        print(f"  skipped: {dict(skipped)}")

    bases = sorted({o["basis"] for o in obs})
    card = {
        "site": a.site,
        "comparable_rows": len(obs),
        "bases_seen": bases,
        "abs_floor_cr": ABS_FLOOR,
        "rel_band": REL_BAND,
        "map": {},
        "rejected": [],
        "_authority": "rev=sf_revop[0]/[1]; pat=sf_fundamentals npStd/npCon",
    }

    # Segment by (basis, company class). The class split is NOT cosmetic: our revenue for a
    # bank/NBFC is Interest Earned (fin=1), while a site's "total revenue" is Total Income
    # (interest + other income). Measured on this pilot: SBIN's site revenue runs 29-42% above
    # ours every quarter while RELIANCE's agrees to ~0.1%. One global mapping would call every
    # bank a defect -- the same failure mode as the SHP campaign's wrong era-split, on a
    # different axis.
    segments = [(b, c) for b in bases for c in ("nonfin", "fin")]
    for basis, cls in segments:
        rows_b = [o for o in obs if o["basis"] == basis and o["cls"] == cls]
        if not rows_b:
            continue
        print("\n--- basis=%r  class=%s  (%d rows) ---" % (basis, cls, len(rows_b)))
        for label in sorted(labels):
            support = [o for o in rows_b if label in o["rows"]]
            if len(support) < max(3, 0.2 * len(rows_b)):
                continue
            results = []
            for field in OURS:
                pairs = [(o["rows"][label], o["mine"].get(field)) for o in support if o["mine"].get(field) is not None]
                if len(pairs) < max(3, 0.3 * len(support)):
                    continue
                for sname, mult in SCALES:
                    hits, deltas, rels = 0, [], []
                    for sv, mv in pairs:
                        got = sv * mult
                        tol = max(ABS_FLOOR, abs(mv) * REL_BAND)
                        d = got - mv
                        deltas.append(d)
                        if abs(mv) > 1e-9:
                            rels.append(d / abs(mv))
                        if abs(d) <= tol:
                            hits += 1
                    hold = 100.0 * hits / len(pairs)
                    results.append(
                        {
                            "field": field,
                            "scale": sname,
                            "mult": mult,
                            "hold_pct": round(hold, 1),
                            "n": len(pairs),
                            "median_abs_delta": round(statistics.median(abs(x) for x in deltas), 3),
                            "median_rel_bias": round(statistics.median(rels), 5) if rels else None,
                        }
                    )
            if not results:
                continue
            results.sort(key=lambda r: (-r["hold_pct"], r["median_abs_delta"]))
            top = results[0]
            runner = results[1] if len(results) > 1 else None
            entry = {
                "label": label,
                "basis_as_labelled": basis,
                "company_class": cls,
                **top,
                "runner_up": {k: runner[k] for k in ("field", "scale", "hold_pct")} if runner else None,
            }
            if top["hold_pct"] >= a.hold_min:
                card["map"].setdefault(f"{basis}|{cls}", {})[label] = entry
                flag = ""
                # T-B fingerprint: a consistent one-sided bias is a DEFINITION difference,
                # not noise -- e.g. site prints total PAT where we store owners-attributable.
                if top["median_rel_bias"] is not None and abs(top["median_rel_bias"]) > 0.002:
                    flag = "  <-- one-sided bias %.3f%% (T-B definition? investigate)" % (100 * top["median_rel_bias"])
                print(
                    "  %-34s -> %-5s x%-8s hold %5.1f%% (n=%d) medΔ=%.3f%s"
                    % (label, top["field"], top["scale"], top["hold_pct"], top["n"], top["median_abs_delta"], flag)
                )
            else:
                card["rejected"].append(entry)
                print(
                    "  %-34s -> NOTHING FITS (best %s x%s hold %.1f%%, n=%d) -- REFUSED"
                    % (label, top["field"], top["scale"], top["hold_pct"], top["n"])
                )

    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(card, fh, indent=1)
        print(
            "\nwrote %s  (%d mappings accepted, %d refused)"
            % (a.out, sum(len(v) for v in card["map"].values()), len(card["rejected"]))
        )


if __name__ == "__main__":
    main()
