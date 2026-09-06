# -*- coding: utf-8 -*-
"""Fold the corrected PAT extraction back into the vintage records, re-verdict OFFLINE, and say
what it changes — including whether any §109-LANDED heal rests on a mis-read page.

OUT: _vintage109_nse_fixed.json / _vintage109_nse_con_fixed.json
"""
import json, os, sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
NEAR_ABS, NEAR_REL = 0.35, 0.005


def near(a, b):
    return a is not None and b is not None and abs(a - b) <= max(NEAR_ABS, abs(b) * NEAR_REL)


def verdict_of(got, stored):
    first = got[0]
    out = {"as_filed": first["pat"], "restated": [x["pat"] for x in got[1:]]}
    if near(stored, first["pat"]):
        out["verdict"] = ("single-vintage-matches-store" if len(got) == 1 else "store-as-filed")
        out["nearest"] = {"filed": first["filed"], "pat": first["pat"],
                          "gap": round(abs(stored - first["pat"]), 4)}
        return out
    hits = [x for x in got[1:] if near(stored, x["pat"])]
    if hits:
        best = min(hits, key=lambda x: abs(stored - x["pat"]))
        out["verdict"] = "vintage-confirmed"
        out["nearest"] = {"filed": best["filed"], "pat": best["pat"],
                          "gap": round(abs(stored - best["pat"]), 4),
                          "as_filed_gap": round(abs(stored - first["pat"]), 4)}
        return out
    out["verdict"] = ("single-vintage-mismatch" if len(got) == 1 else "stored-in-neither")
    out["nearest"] = {"gap_to_as_filed": round(abs(stored - first["pat"]), 4)}
    return out


def main():
    pat = json.load(open(os.path.join(HERE, "_vintage109_pat_rows.json")))["pages"]
    fixed_seq = {s: r for s, r in pat.items()
                 if (r["pat_old"] is None) != (r["pat_new"] is None)
                 or (r["pat_old"] is not None and r["pat_new"] is not None
                     and abs(r["pat_old"] - r["pat_new"]) > 0.005)}
    print("pages whose PAT the corrected rule moves: %d" % len(fixed_seq))

    props = json.load(open(os.path.join(HERE, "_vintage108_proposals.json")))
    touched = [p for p in props["proposals"] + props["revop"]
               if str(p["_ev"].get("as_filed_seq")) in fixed_seq
               or str(p["_ev"].get("restated_seq")) in fixed_seq]
    print("§109 LANDED heals resting on one of those pages: %d" % len(touched))
    for p in touched:
        print("   ", p["sym"], p["qe"], p["basis"], p["was"], "->", p["fixed"])

    for src, dst in (("_vintage108_nse.json", "_vintage109_nse_fixed.json"),
                     ("_vintage108_nse_con.json", "_vintage109_nse_con_fixed.json")):
        n = json.load(open(os.path.join(HERE, src)))
        moved, reverd = 0, Counter()
        for k, v in n.items():
            ch = False
            for x in v.get("vintages", []):
                r = fixed_seq.get(str(x.get("seq")))
                if r is not None and x.get("pat") != r["pat_new"]:
                    x["pat_before_fix"], x["pat"] = x.get("pat"), r["pat_new"]
                    x["pat_row"] = r["row_new"]
                    x["pat_fix_note"] = r["note"]
                    ch = True
            if not ch:
                continue
            moved += 1
            got = [x for x in v.get("vintages", [])
                   if x.get("pat") is not None and x.get("cumulative") != "Cumulative"]
            before = v.get("verdict")
            if got:
                v.update(verdict_of(got, v["stored"]))
            else:
                v["verdict"] = "no-readable-vintage"
            reverd[(before, v["verdict"])] += 1
        json.dump(n, open(os.path.join(HERE, dst), "w"), indent=1)
        print("\n%s -> %s : %d cells re-read" % (src, dst, moved))
        for (a, b), c in reverd.most_common():
            print("    %4d  %-28s -> %s" % (c, a, b))


if __name__ == "__main__":
    main()
