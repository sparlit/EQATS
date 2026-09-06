# -*- coding: utf-8 -*-
"""Re-check every cell filled by the PAT-ONLY anchor — the root cause behind the AADHARHFC defect.

WHY THESE CELLS. `scripts/screener_prerev.py` accepts a Screener revenue row as soon as that page's
NET PROFIT matches our stored PAT. PAT matching proves the page is the right company and the right
quarter; it proves nothing about WHICH REVENUE ROW was taken. AADHARHFC 2023-06/2023-12 landed the
filing's `Interest income` row (533.47 / 579.26, exact to the cent) against totals of 578.01 /
658.54. `scripts/screener_rev_fills.json` is the tracked ledger of every cell filled that way.

IS COMPARING BACK TO SCREENER CIRCULAR? For this specific question, no — and the distinction
matters. These cells were sourced FROM Screener, so Screener cannot *confirm* them (rule 6b's
provenance echo still bars that). But the defect is that the WRONG ROW was taken from that page, so
comparing our stored value against Screener's revenue row TODAY is a row-selection check, not a
corroboration. A mismatch is real evidence; a match is not proof.

TWO RISKS ARE TESTED:
  R1 wrong row   -- our stored value differs from Screener's current revenue row.
  R2 basis copy  -- the ledger recorded the SAME revenue for con and std, i.e. one scrape reused for
                    both bases. Sometimes legitimate (HUDCO is genuinely identical) so it is a flag,
                    never a verdict.

  python3 -X utf8 scripts/revpat_verify/check_exposed_cells.py --sweep <p4>/screener_p4.jsonl \
      [--sweep more.jsonl] --out exposed_recheck.json
"""
import os, json, csv, argparse, collections

TREE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REV_LABELS = ("Revenue", "Sales")
TOL_ABS, TOL_REL = 0.5, 0.005


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", action="append", required=True)
    ap.add_argument("--out", default="exposed_recheck.json")
    ap.add_argument("--csv", default="")
    a = ap.parse_args()

    led = json.load(open(os.path.join(TREE, "scripts/screener_rev_fills.json"), encoding="utf-8"))
    revop = json.load(open(os.path.join(TREE, "docs/sf_revop.json"), encoding="utf-8"))

    site = collections.defaultdict(dict)          # (sym, basis) -> qe -> revenue
    for p in a.sweep:
        if not os.path.exists(p):
            print("  ! missing sweep file: %s" % p); continue
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            b = e.get("basis")
            if b not in ("std", "con"):
                continue
            rv = next((e["rows"][k] for k in REV_LABELS if k in e["rows"]), None)
            if rv is not None:
                site[(e["sym"].upper(), b)][int(str(e["qe"]).replace("-", ""))] = float(rv)

    rows, tally = [], collections.Counter()
    for key, v in led.items():
        sym, qe = key.split("|")[0].upper(), key.split("|")[1]
        stored_row = (revop.get(sym) or {}).get(qe)
        led_con = (v.get("con") or {}).get("rev")
        led_std = (v.get("std") or {}).get("rev")
        basis_copy = (led_con is not None and led_std is not None
                      and abs(led_con - led_std) <= 0.005)
        if basis_copy:
            tally["R2_basis_copy_flag"] += 1

        for basis, idx, ledv in (("std", 0, led_std), ("con", 1, led_con)):
            if ledv is None:
                continue
            stored = stored_row[idx] if stored_row and len(stored_row) > idx else None
            sv = site.get((sym, basis), {}).get(int(qe))
            rec = {"sym": sym, "qe": int(qe), "basis": basis, "ledger_rev": ledv,
                   "stored_now": stored, "screener_now": sv,
                   "basis_copy_in_ledger": basis_copy,
                   "src": (v.get(basis) or {}).get("src")}
            if stored is None:
                rec["status"] = "NOT_IN_STORE"          # ledger staged it; sf_revop has nothing
            elif sv is None:
                rec["status"] = "NO_SITE_DATA"          # 404 / empty table / slug mismatch
            else:
                rec["delta"] = round(stored - sv, 2)
                rec["pct"] = round(100 * (stored - sv) / abs(sv), 2) if sv else None
                ok = abs(stored - sv) <= max(TOL_ABS, abs(sv) * TOL_REL)
                rec["status"] = "MATCHES_SITE_ROW" if ok else (
                    "BELOW_SITE_ROW" if stored < sv else "ABOVE_SITE_ROW")
            tally[rec["status"]] += 1
            rows.append(rec)

    suspect = [r for r in rows if r["status"] == "BELOW_SITE_ROW"]
    suspect.sort(key=lambda r: r.get("pct") or 0)

    doc = {"_meta": {
        "cohort": "scripts/screener_rev_fills.json -- cells filled by screener_prerev.py, whose "
                  "anchor checks PAT ONLY and is therefore blind to which revenue row was taken",
        "ledger_keys": len(led), "basis_cells_checked": len(rows), "tally": dict(tally),
        "circularity": "these cells came FROM Screener, so a MATCH is not corroboration (rule 6b "
                       "provenance echo). A MISMATCH is still real evidence of a row-selection error.",
        "note": "BELOW_SITE_ROW is a candidate. Only a filing read decides."},
        "suspects": suspect, "all": rows}
    json.dump(doc, open(a.out, "w", encoding="utf-8"), indent=1)
    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["sym", "qe", "basis", "status", "stored_now", "screener_now", "pct",
                        "basis_copy_in_ledger"])
            for r in rows:
                w.writerow([r["sym"], r["qe"], r["basis"], r["status"], r.get("stored_now"),
                            r.get("screener_now"), r.get("pct"), r["basis_copy_in_ledger"]])

    print("ledger keys: %d | basis-cells checked: %d" % (len(led), len(rows)))
    for k, n in sorted(tally.items(), key=lambda kv: -kv[1]):
        print("   %-22s %4d" % (k, n))
    print("\nR1 SUSPECTS -- stored value BELOW Screener's current revenue row (%d):" % len(suspect))
    print("   %-12s %-9s %10s %10s %8s" % ("sym", "qe", "ours", "screener", "pct"))
    for r in suspect[:40]:
        print("   %-12s %-9d %10s %10s %7.1f%%" % (r["sym"], r["qe"], r["stored_now"],
                                                   r["screener_now"], r["pct"]))
    print("\nwrote %s" % a.out)


if __name__ == "__main__":
    main()
