# -*- coding: utf-8 -*-
"""Apply scripts/_shp_seam_adjudicated.json to the wayback seam ledger.

Runs AFTER `fetch_shp_wayback_mc.py ledger`, because that stage rewrites the whole file from the
parsed cache and would otherwise silently revert every adjudication. Idempotent: re-running on an
already-adjudicated ledger is a no-op, so it is safe to chain unconditionally.

  python3 -X utf8 scripts/_shp_seam_adjudicate.py [--dry]
"""
import os, sys, json, gzip, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "shp_fill_hist_2010_2016.json.gz")
RULES = os.path.join(HERE, "_shp_seam_adjudicated.json")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    rules = json.load(open(RULES, encoding="utf-8"))["cells"]
    led = json.load(gzip.open(LEDGER, "rt", encoding="utf-8"))
    fills = led["fills"]
    done = {"replace": 0, "patch_promoter": 0, "drop": 0, "keep_mine": 0, "absent": 0}

    for sym, qs in rules.items():
        for qe, r in qs.items():
            act = r["action"]
            cur = (fills.get(sym) or {}).get(qe)
            if act == "keep_mine":
                done["keep_mine"] += 1; continue
            if cur is None:
                done["absent"] += 1
                print("  %-11s %s  %-14s cell not in ledger (already applied or never landed)" % (sym, qe, act))
                continue
            if act == "replace":
                w = list(r["with"])
                # preserve the provenance slot shape: [prom,fii,dii,mf,ins,sub,nsh,src]
                fills[sym][qe] = w + [None, "bse_late_xbrl:adjudicated-vs-jun2016-anchor"]
                done["replace"] += 1
            elif act == "patch_promoter":
                c = list(cur); c[0] = r["promoter"]
                if len(c) > 7:
                    c[7] = str(c[7]) + ";prom<-bse_late_xbrl"
                fills[sym][qe] = c
                done["patch_promoter"] += 1
            elif act == "drop":
                del fills[sym][qe]
                if not fills[sym]:
                    del fills[sym]
                done["drop"] += 1
            print("  %-11s %s  %-14s ok" % (sym, qe, act))

    led["_meta"]["cells"] = sum(len(v) for v in fills.values())
    led["_meta"]["seam_adjudicated"] = {k: v for k, v in done.items() if v}
    print("\n%s  ledger now %d cells" % (done, led["_meta"]["cells"]))
    if a.dry:
        print("(dry run — not written)"); return
    with gzip.open(LEDGER, "wt", encoding="utf-8") as fh:
        json.dump(led, fh, separators=(",", ":"))
    print("written -> %s" % os.path.basename(LEDGER))


if __name__ == "__main__":
    main()
