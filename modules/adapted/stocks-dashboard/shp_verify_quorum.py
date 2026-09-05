# -*- coding: utf-8 -*-
"""MULTI-SITE QUORUM — campaign rule 6b, the user's standing mandate (2026-08-09):

    "make sure u chek from many sites and it should mach, only then take it"

Nothing is confirmed, and nothing is written into our data, on ONE site's say-so. This script
folds every site's verdict JSONL into one decision per (sym, qe, field):

  CONFIRMED       enough INDEPENDENT sites match us, and they agree with each other  -> our value stands
  CONTRADICTED    enough independent sites agree with EACH OTHER and all differ from us -> P5 arbitration
  SITES_DISAGREE  the sites do not agree among themselves -> value NOT taken, disagreement recorded
  INSUFFICIENT    fewer independent sites carry the cell than the quorum needs -> stays open
  ECHO_ONLY       only sites our own cell was harvested from carry it (trap T3) -> proves transcription only

Quorum size (rule 6b): 2 independent sites where an exchange filing also backs the cell
(Jun-2016 onward — BSE/NSE XBRL exists), else 3 independent sites (pre-Jun-2016, no exchange route).
PROVENANCE_ECHO sites NEVER count toward quorum — a match against the site we copied from is
transcription evidence, not verification.

  python3 -X utf8 scripts/shp_verify_quorum.py --verdicts p3/*_verdicts.jsonl --out p5/quorum.jsonl
"""
import os, sys, json, glob, argparse, collections

EXCHANGE_ERA = "2016-06-30"        # first quarter with a real BSE XBRL file (runbook §22f)
AGREE = 0.06                       # within-ROUND: sites counted as matching
SPREAD_MAX = 0.50                  # independent sites further apart than this = SITES_DISAGREE
CONFIRMING = ("MATCH", "ROUND")
ECHO = "PROVENANCE_ECHO"


def quorum_needed(qe, prov):
    """Exchange-backed cells need 2 corroborating sites; the pre-2016 era needs 3."""
    return 2 if (qe >= EXCHANGE_ERA and prov not in ("wayback-mc", "thirdparty", "")) else 3


def tolerances(field, ours, obs=None):
    """Return (agree, spread_max) in the FIELD's own units.

    Percentages are compared in percentage points; `nsh` is a raw headcount in the millions, so
    reusing the pp thresholds there declared two sites in conflict over half a person. Sites also
    publish counts at different precision (StockEdge rounds to 2dp of lakhs = +/-500 people), so
    the headcount bands are relative.

    When WE hold no value the scale has to come from the sites themselves — these are exactly the
    NO_DATA_OURS cells the campaign exists to find, and defaulting them to a 0.5-person spread
    buried real fillable gaps (TCS Jun-2024: BSE and Screener agree to the person) under
    SITES_DISAGREE."""
    if field != "nsh":
        return AGREE, SPREAD_MAX
    base = abs(float(ours)) if ours else None
    if base is None and obs:
        vals = [abs(float(o["val"])) for o in obs if o.get("val") is not None]
        base = (sorted(vals)[len(vals) // 2] if vals else None)
    if not base:
        return AGREE, SPREAD_MAX
    return max(1.0, 0.01 * base), max(1.0, 0.02 * base)


def decide(ours, obs, qe, prov, field="", agree=None, spread_max=None):
    """obs = [{site, val, verdict, echo}] — one entry per site that carried this cell."""
    AGREE, SPREAD_MAX = (agree if agree is not None else globals()["AGREE"]), \
                        (spread_max if spread_max is not None else globals()["SPREAD_MAX"])
    indep = [o for o in obs if not o["echo"] and o["val"] is not None]
    echoes = [o for o in obs if o["echo"] and o["val"] is not None]
    need = quorum_needed(qe, prov)

    if not indep:
        return ("ECHO_ONLY" if echoes else "INSUFFICIENT"), need, 0, 0, None

    vals = [float(o["val"]) for o in indep]
    spread = max(vals) - min(vals)
    confirm = [o for o in indep if o["verdict"] in CONFIRMING or
               (ours is not None and abs(float(o["val"]) - float(ours)) <= AGREE)]
    contra = [o for o in indep if o not in confirm]

    if spread > SPREAD_MAX:
        return "SITES_DISAGREE", need, len(confirm), len(contra), spread
    if len(confirm) >= need and not contra:
        return "CONFIRMED", need, len(confirm), 0, spread
    # CONTRADICTED is the top of the arbitration queue and means something specific: the sites
    # agree with EACH OTHER and all of them disagree with us. That requires them to be tight
    # among themselves. Without this guard, three sites scattered across 0.46pp (wider than the
    # 0.06 tolerance, so none matches us) were being reported as a united front against our
    # value — when in truth each simply rounds or derives the bucket differently. Those are
    # SITES_DISAGREE: nothing is taken, and no one is accused.
    if len(contra) >= need and not confirm and spread <= AGREE:
        return "CONTRADICTED", need, 0, len(contra), spread
    if contra and (confirm or spread > AGREE):
        return "SITES_DISAGREE", need, len(confirm), len(contra), spread
    return "INSUFFICIENT", need, len(confirm), len(contra), spread


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdicts", nargs="+", required=True, help="verdict JSONLs (globs ok)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--echo-map", default="", help="prov.json.gz — to re-derive which sites echo which routes")
    a = ap.parse_args()

    paths = [p for pat in a.verdicts for p in sorted(glob.glob(pat))] or []
    if not paths:
        sys.exit("no verdict files matched")

    cells = collections.defaultdict(lambda: {"ours": None, "prov": "", "obs": [], "urls": {}})
    for path in paths:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("field") in (None, "*"):
                continue
            key = (r["sym"], r["qe"], r["field"])
            c = cells[key]
            if r.get("ours") is not None:
                c["ours"] = r["ours"]
            c["prov"] = r.get("prov") or c["prov"]
            c["obs"].append({"site": r["site"], "val": r.get("site_val"),
                             "verdict": r.get("verdict", ""), "echo": r.get("verdict") == ECHO})
            if r.get("evidence_url"):
                c["urls"][r["site"]] = r["evidence_url"]

    out, tally = [], collections.Counter()
    for (sym, qe, field), c in sorted(cells.items()):
        ag, sp = tolerances(field, c["ours"], c["obs"])
        d, need, nc, nx, spread = decide(c["ours"], c["obs"], qe, c["prov"], field, ag, sp)
        tally[d] += 1
        out.append({"sym": sym, "qe": qe, "field": field, "ours": c["ours"], "prov": c["prov"],
                    "decision": d, "quorum_needed": need, "n_confirm": nc, "n_contradict": nx,
                    "site_spread": (round(spread, 3) if spread is not None else None),
                    "sites": {o["site"]: o["val"] for o in c["obs"]},
                    "urls": c["urls"]})

    with open(a.out, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")

    total = len(out)
    print("%d cell-fields across %d site files -> %s" % (total, len(paths), a.out))
    for d, n in tally.most_common():
        print("  %-15s %6d  %5.1f%%" % (d, n, 100.0 * n / total))
    esc = [r for r in out if r["decision"] in ("CONTRADICTED", "SITES_DISAGREE")]
    print("\n%d cells need Phase-5 arbitration (CONTRADICTED first — sites agree with each other, not with us):" % len(esc))
    for r in sorted(esc, key=lambda r: (r["decision"] != "CONTRADICTED", -(r["site_spread"] or 0)))[:20]:
        print("  %-11s %s %-4s ours=%-8s sites=%s  [%s]" %
              (r["sym"], r["qe"], r["field"], r["ours"], r["sites"], r["decision"]))


if __name__ == "__main__":
    main()
