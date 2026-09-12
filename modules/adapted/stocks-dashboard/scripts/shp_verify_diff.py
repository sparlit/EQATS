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
"""Diff raw site extractions against the pinned shp_history and emit verdict rows.

Inputs (SHP_VERIFY_CAMPAIGN §8):
  --extract  site extraction JSONL — RAW printed labels/values, one line per (stock, quarter)
  --map      the site's MAPPING CARD (built in Phase 2; which printed rows sum to our fields)
  --prov     per-cell provenance map from shp_verify_prov.py (drives PROVENANCE_ECHO, trap T3)
Output: verdict JSONL, one line per (sym, qe, field).

The engine compares LEVELS ONLY, never quarter-over-quarter — trap T1: the Jun->Sep-2022 format
change reclassified DR/ADR holdings between buckets, so both sides of that seam are individually
correct and any QoQ across it is meaningless. Cells at the boundary are flagged, not judged.

Mapping-card shape:
  {"site":"x", "precision":2,
   "map":   {"fii":["<printed label>", ...], "dii":[...], "prom":[...], "mf":[...], "ins":[...], "nsh":[...]},
   "eras":  [{"from":"2010-01-01","to":"2022-06-30","map":{...}}]   # optional per-era overrides (trap T2)
  }
A field maps to a LIST of printed labels that are SUMMED. Labels absent from an extraction row make
that field unavailable for that quarter (NO_DATA_SITE) — never silently treated as zero (§22b: the
zero-default is exactly what poisons FII/DII).

  python3 -X utf8 scripts/shp_verify_diff.py --extract p1/trendlyne_extract.jsonl \
      --map p2/trendlyne_map.json --prov prov.json.gz --pin 93de247c --out p2/trendlyne_verdicts.jsonl
"""
import argparse
import collections
import gzip
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

SLOT = {"prom": 0, "fii": 1, "dii": 2, "mf": 3, "ins": 4, "nsh": 6}
PCT_FIELDS = ("prom", "fii", "dii", "mf", "ins")
FORMAT_BOUNDARY = "2022-09-30"  # trap T1 — first new-taxonomy quarter
MATCH, ROUND_BASE, INVESTIGATE = 0.02, 0.06, 0.50


def load_hist(pin):
    r = subprocess.run(["git", "show", f"{pin}:scripts/shp_history.json"], capture_output=True, cwd=REPO)
    if r.returncode:
        sys.exit(f"cannot read shp_history.json at {pin}")
    return json.loads(r.stdout)


def load_prov(path):
    if not path:
        return {}
    raw = gzip.open(path, "rb").read() if path.endswith(".gz") else open(path, "rb").read()
    return json.loads(raw).get("prov", {})


def round_band(precision):
    """Trap T6: a site printing fewer decimals than us can differ by half its last digit."""
    try:
        p = int(precision)
    except (TypeError, ValueError):
        p = 2
    return max(ROUND_BASE, 0.5 * (10.0**-p) + 0.01)


def map_for(card, qe):
    """Per-era override wins (trap T2: pre-Sep-2022 'other institutions' sits in a different bucket)."""
    for era in card.get("eras", []):
        if era.get("from", "0") <= qe <= era.get("to", "9"):
            return era["map"]
    return card["map"]


def num(v):
    """Sites print '22.58%', '46,51,863' (Indian grouping), '-', '' and bare floats. Return float or None.

    A dash/blank is NOT zero — it means the site did not publish that row, and zero-defaulting is
    precisely the failure mode that poisons FII/DII (runbook §22b)."""
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


def site_value(row_labels, labels, scale=1.0):
    """Sum the printed labels, then apply the card's unit scale. Never zero-defaults.

    `scale` exists because units differ across sites: StockEdge prints shareholder counts as
    "No. of Shareholders (in Lacs)" = 46.52 where we store 4,651,863. Without it the engine
    reported every one of those as a multi-million MISMATCH."""
    total, missing = 0.0, []
    for lab in labels:
        v = num(row_labels.get(lab))
        if v is None:
            missing.append(lab)
        else:
            total += v
    if len(missing) == len(labels):
        return None, missing
    return total * scale, missing


def classify(delta, band_round, echoed):
    a = abs(delta)
    if a <= MATCH:
        return "PROVENANCE_ECHO" if echoed else "MATCH"
    if a <= band_round:
        return "PROVENANCE_ECHO" if echoed else "ROUND"
    if a <= INVESTIGATE:
        return "INVESTIGATE"
    return "MISMATCH"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract", required=True)
    ap.add_argument("--map", required=True)
    ap.add_argument("--prov", default="")
    ap.add_argument("--pin", default="origin/main")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    HIST, PROV = load_hist(a.pin), load_prov(a.prov)
    card = json.load(open(a.map, encoding="utf-8"))
    site = card["site"]
    band = round_band(card.get("precision", 2))
    # per-field unit scale, e.g. {"nsh": 100000} for a site printing counts "in Lacs"
    scales = card.get("scale", {}) or {}
    echo_sites = json.loads(gzip.open(a.prov).read())["_meta"]["echoes"] if a.prov else {}

    rows, tally = [], collections.Counter()
    seen_ours = collections.defaultdict(set)

    for line in open(a.extract, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        ext = json.loads(line)
        sym, qe = ext["sym"], (ext.get("asof") or "")
        base = {
            "sym": sym,
            "qe": qe,
            "site": site,
            "evidence_url": ext.get("url", ""),
            "fetched": ext.get("fetched", ""),
        }

        if ext.get("event") or qe[5:] not in ("03-31", "06-30", "09-30", "12-31"):
            rows.append(
                dict(
                    base,
                    field="*",
                    verdict="EVENT_SHP",
                    note=f"site as-on {qe} is not a quarter end; we keep quarter-end series only",
                )
            )
            tally["EVENT_SHP"] += 1
            continue

        ours_cell = HIST.get(sym, {}).get(qe)
        route = PROV.get(sym, {}).get(qe, "")
        echoed = site in (echo_sites.get(route) or [])
        seen_ours[sym].add(qe)
        fmap = map_for(card, qe)

        if ours_cell is None:
            rows.append(
                dict(
                    base,
                    field="*",
                    verdict="NO_DATA_OURS",
                    prov="",
                    note="site publishes this quarter and we hold no cell — coverage finding",
                )
            )
            tally["NO_DATA_OURS"] += 1
            continue

        for field, labels in fmap.items():
            if field not in SLOT:
                continue
            sval, missing = site_value(ext.get("rows") or {}, labels, float(scales.get(field, 1.0)))
            slot = SLOT[field]
            ours = ours_cell[slot] if len(ours_cell) > slot else None
            if sval is None:
                v, delta = "NO_DATA_SITE", None
            elif ours is None:
                v, delta = "NO_DATA_OURS", None
            elif field == "nsh":
                delta = float(sval) - float(ours)
                # A scaled count inherits the site's PRINTING quantum, not a relative band:
                # StockEdge prints "in Lacs" to 2dp, so its quantum is 0.01 lakh = 1,000 people
                # and any value can sit +/-500 from the truth. For a 32k-shareholder company that
                # is 1.5%, so a flat 1% rule called correct data a MISMATCH.
                q = float(scales.get(field, 1.0)) * 0.5 * (10.0 ** -int(card.get("precision", 2)))
                band_n = max(0.01 * max(1.0, float(ours)), q)
                v = "MATCH" if delta == 0 else ("ROUND" if abs(delta) <= band_n else "MISMATCH")
                if v in ("MATCH", "ROUND") and echoed:
                    v = "PROVENANCE_ECHO"
            else:
                delta = round(float(sval) - float(ours), 4)
                v = classify(delta, band, echoed)

            note = ""
            if missing and sval is not None:
                note = "partial sum; labels absent: {}".format(",".join(missing))
            if qe == FORMAT_BOUNDARY:
                note = (note + "; " if note else "") + "T1 format-boundary quarter — level only, never QoQ"
            rows.append(
                dict(base, field=field, ours=ours, site_val=sval, delta_pp=delta, verdict=v, prov=route, note=note)
            )
            tally[v] += 1

    # the other direction of coverage: quarters we hold that the site never showed
    for sym in seen_ours:
        for qe in sorted(HIST.get(sym, {})):
            if qe not in seen_ours[sym]:
                rows.append(
                    {
                        "sym": sym,
                        "qe": qe,
                        "site": site,
                        "field": "*",
                        "verdict": "NO_DATA_SITE",
                        "prov": PROV.get(sym, {}).get(qe, ""),
                        "note": "we hold this quarter; site did not show it",
                    }
                )
                tally["NO_DATA_SITE"] += 1

    with open(a.out, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, separators=(",", ":")) + "\n" for r in rows)

    print("%s: %d verdict rows -> %s" % (site, len(rows), a.out))
    for v, n in tally.most_common():
        print("  %-16s %5d" % (v, n))
    bad = [r for r in rows if r["verdict"] == "MISMATCH"]
    if bad:
        print("  ! %d MISMATCH rows need Phase-5 arbitration; worst:" % len(bad))
        for r in sorted(bad, key=lambda r: -abs(r.get("delta_pp") or 0))[:10]:
            print(
                "     %-12s %s %-4s ours=%s site=%s d=%+.2f"
                % (r["sym"], r["qe"], r["field"], r.get("ours"), r.get("site_val"), r.get("delta_pp") or 0)
            )


if __name__ == "__main__":
    main()
