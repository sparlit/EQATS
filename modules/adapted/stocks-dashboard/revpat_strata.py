# -*- coding: utf-8 -*-
"""FREEZE the Phase-3 stratified sample for the REV/PAT verify campaign.

Deterministic by construction: within each stratum members are ordered by md5(symbol) and the
lowest N are taken; earlier strata win ties. Any agent on any machine re-derives the identical
list, so the sample can never be quietly reshaped to flatter numbers.

Strata target the FIVE rev/PAT traps (campaign doc §1), not generic representativeness:
  T-A basis      -> both_bases, con_only, std_only, banks (basis bites hardest)
  T-B profit def -> big_nci, insurers, nbfc  (owners-vs-total, ORFO, IRDAI format)
  T-C scale      -> loss_makers (sign handling), plus the store-divergent set
  T-D period     -> banks/insurers (different line items), recent_ipo (partial years)
  T-E restate    -> store_divergent (our own two files disagree = restatement candidates)
plus the named open items the plan folds in (LICI, GICRE) and cap terciles for breadth.

  python3 -X utf8 revpat_strata.py --pin e8a491c6 --out strata.json
"""
import os, sys, json, gzip, hashlib, argparse, subprocess, collections

TREE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # repo root of THIS checkout

# Named members: each exists to exercise a SPECIFIC trap the plan calls out by name.
PLAN_NAMED = ["RELIANCE",            # baseline
              "SBIN", "HDFCBANK",    # banks - T-A
              "SBILIFE",             # insurer - IRDAI format
              "BAJFINANCE",          # NBFC - ORFO rule
              "TATASTEEL", "GRASIM", # big NCI - T-B fingerprint
              "ETERNAL",             # renamed ticker
              "MOTHERSON", "MSUMI",  # demerger pair
              "GICRE",               # standalone pollution still suspect
              "LICI"]                # std slot held the con figure (runbook 58d)
INSURERS = ["LICI", "SBILIFE", "HDFCLIFE", "ICICIPRULI", "ICICIGI", "GICRE",
            "NIACL", "STARHEALTH", "GODIGIT", "NIVABUPA", "MFSL"]


def jload(rel):
    with open(os.path.join(TREE, rel), encoding="utf-8") as fh:
        return json.load(fh)


def h(sym):
    return hashlib.md5(sym.encode()).hexdigest()


def take(pool, n, used):
    out = []
    for s in sorted(set(pool), key=h):
        if s in used:
            continue
        out.append(s); used.add(s)
        if len(out) >= n:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pin", default="e8a491c6")
    ap.add_argument("--out", default="strata.json")
    a = ap.parse_args()

    REVOP = jload("docs/sf_revop.json")
    FUND = jload("docs/sf_fundamentals.json")
    IH = jload("scripts/indices_history.json")
    RMAP = jload("scripts/_rename_map.json")

    slim = json.loads(gzip.decompress(open(os.path.join(TREE, "docs/dash_slim.bin"), "rb").read()))
    mcap = {}
    for _k, r in slim.get("meta", {}).items():
        if r.get("symbol") and r.get("mcap"):
            mcap[r["symbol"]] = float(r["mcap"])

    snaps = sorted(IH["Nifty 500"], key=lambda s: s["effectiveDate"])
    members = set(snaps[-1]["symbols"])
    latest_snap = snaps[-1]["effectiveDate"]

    # ---- per-symbol facts used to define strata --------------------------------
    patf = collections.defaultdict(dict)
    for s, rows in FUND.items():
        for r in rows:
            if isinstance(r, list) and len(r) >= 5 and isinstance(r[0], int):
                patf[s][r[0]] = (r[1], r[3])

    n_rev_s = collections.Counter(); n_rev_c = collections.Counter()
    isfin = set(); divergent = collections.Counter()
    for s, d in REVOP.items():
        for k, row in d.items():
            q = int(k)
            if row[0] is not None: n_rev_s[s] += 1
            if row[1] is not None: n_rev_c[s] += 1
            if row[6] == 1: isfin.add(s)
            # store divergence on the PAT mirror = restatement / defect candidate
            for idx, pi in ((4, 0), (5, 1)):
                a_, b_ = row[idx], (patf.get(s, {}).get(q) or (None, None))[pi]
                if a_ is not None and b_ is not None and abs(a_ - b_) > max(0.5, abs(b_) * 0.005):
                    divergent[s] += 1

    n_pat_s = collections.Counter(); n_pat_c = collections.Counter()
    lossy = collections.Counter(); nci_gap = {}
    for s, qd in patf.items():
        gaps = []
        for q, (ps, pc) in qd.items():
            if ps is not None: n_pat_s[s] += 1
            if pc is not None: n_pat_c[s] += 1
            if ps is not None and ps < 0: lossy[s] += 1
            if ps and pc and abs(ps) > 5:
                gaps.append(abs(pc - ps) / abs(ps))
        if len(gaps) >= 8:
            nci_gap[s] = sorted(gaps)[len(gaps) // 2]          # median relative con-std gap

    held = [s for s in members if n_rev_s[s] + n_rev_c[s] >= 8 and (n_pat_s[s] + n_pat_c[s]) >= 8]
    universe = sorted([s for s in held if s in mcap], key=lambda s: -mcap[s])
    third = max(1, len(universe) // 3)
    mega, mid, small = universe[:third], universe[third:2 * third], universe[2 * third:]

    both_bases = [s for s in held if n_rev_s[s] >= 8 and n_rev_c[s] >= 8]
    con_only = [s for s in held if n_rev_c[s] >= 8 and n_rev_s[s] < 4]
    std_only = [s for s in held if n_rev_s[s] >= 20 and n_rev_c[s] == 0]
    banks = [s for s in held if s in isfin]
    big_nci = [s for s, g in sorted(nci_gap.items(), key=lambda kv: -kv[1]) if s in held][:40]
    losses = [s for s in held if lossy[s] >= 4]
    renamed = [s for s in set(list(RMAP.values()) + list(RMAP.keys())) if s in held]
    ipos = [s for s in held if (n_rev_s[s] + n_rev_c[s]) <= 14]
    diverg = [s for s in divergent if divergent[s] >= 2]

    used, strata = set(), collections.OrderedDict()
    for name, pool, n in [
        ("plan_named",       [s for s in PLAN_NAMED if s in REVOP or s in FUND], len(PLAN_NAMED)),
        ("insurers",         [s for s in INSURERS if s in REVOP or s in FUND], 4),
        ("store_divergent",  diverg, 8),
        ("big_nci",          big_nci, 5),
        ("banks_nbfc",       banks, 5),
        ("loss_makers",      losses, 4),
        ("con_only",         con_only, 3),
        ("std_only",         std_only, 4),
        ("renamed",          renamed, 4),
        ("recent_ipo",       ipos, 3),
        ("cap_mega",         mega, 7),
        ("cap_mid",          mid, 7),
        ("cap_small",        small, 7),
    ]:
        picked = take(pool, n, used)
        strata[name] = picked
        if len(picked) < n:
            print("  ! stratum %s: only %d/%d available" % (name, len(picked), n), file=sys.stderr)

    allsyms = sorted(used)
    doc = {"_meta": {"pin": a.pin,
                     "rule": "lowest md5(symbol) within each stratum; earlier strata win",
                     "universe_current_n500_with_history": len(universe),
                     "n500_snapshot": latest_snap, "total": len(allsyms),
                     "authority": "rev=sf_revop[0]/[1]; pat=sf_fundamentals npStd/npCon "
                                  "(NEVER sf_revop[4]/[5], see P0 report §2)"},
           "strata": strata, "symbols": allsyms,
           "facts": {s: {"revS": n_rev_s[s], "revC": n_rev_c[s], "patS": n_pat_s[s],
                         "patC": n_pat_c[s], "fin": int(s in isfin),
                         "store_divergent_cells": divergent[s]} for s in allsyms}}
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)

    print("universe (current N500, >=8 rev and >=8 pat cells, with mcap): %d  snapshot %s"
          % (len(universe), latest_snap))
    for k, v in strata.items():
        print("  %-17s %2d  %s" % (k, len(v), ",".join(v)))
    tot_cells = sum(n_rev_s[s] + n_rev_c[s] + n_pat_s[s] + n_pat_c[s] for s in allsyms)
    print("TOTAL %d symbols, %d stored field-cells in scope" % (len(allsyms), tot_cells))
    print("wrote %s" % a.out)


if __name__ == "__main__":
    main()
