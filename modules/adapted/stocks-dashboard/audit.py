# -*- coding: utf-8 -*-
"""THE DECISIVE TEST, per suspect cell, walking the §57 route ladder in yield order.

For a cell (sym, qe) where the stored standalone PAT equals the stored consolidated PAT:

    std_source == stored_std                                  -> OK
    std_source != stored_std AND con_source == stored_std     -> DEFECT (std slot holds con)
    std_source != stored_std AND con_source != stored_std     -> OTHER-DEFECT (std wrong, not by copy)
    std_source != stored_std, con not read                    -> STD-MISMATCH-CON-UNREAD
    nothing read                                              -> INCONCLUSIVE (routes recorded)

Rungs, in the order they are tried (§57b):
  5. NSE results XBRL, one document per basis, period+basis gated   -- decisive, covers 2019+
  1. BSE detailed-results JSON (§42), standalone, basis-CALIBRATED  -- covers 2015+, incl. delisted
  3. BSE announcement PDF, column-anchored                          -- the one that wins when 5 and 1 are blind
  2. NSE archive detail pages (§52/§53), both bases                 -- pre-2020 tail

Every rung tried is recorded whether it answers or not, so a refusal is reported as
`not-found-via:<routes>` and never as "the value does not exist" (§0, §57a).
"""
import json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import bse_vision as V                                    # noqa: E402
import detres as D                                        # noqa: E402
import scrips as SC                                       # noqa: E402
import xbrl_route as X                                    # noqa: E402
import nse_arch as NA                                     # noqa: E402
import probe as P                                         # noqa: E402

FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
OUT = os.path.join(HERE, "_audit.json")


def close(a, b):
    return abs(a - b) <= max(0.05, 0.005 * abs(b))


def audit_cell(sym, qe, fund, o, lcache):
    rows = fund.get(sym) or []
    row = {r[0]: r for r in rows}.get(qe)
    if not row:
        return {"verdict": "NO-STORED-ROW"}
    ss, sc = row[1], row[3]
    res = {"sym": sym, "qe": qe, "stored_std": ss, "stored_con": sc,
           "routes": [], "std": [], "con": []}

    # ---- rung 5: NSE results XBRL, per basis --------------------------------------------------
    for want_con, bucket in ((False, "std"), (True, "con")):
        v, ev = X.read(sym, qe, want_con)
        tag = "xbrl-%s" % bucket
        if v is None:
            res["routes"].append("%s: %s" % (tag, ev.get("skip")))
        else:
            res["routes"].append("%s: %.2f (ctx %s, %s, declared %s)"
                                 % (tag, v, ev["ctx"], ev["period"], ev["basis_declared"]))
            res[bucket].append({"src": "nse-xbrl", "value": v, "ev": ev})

    # ---- rung 1: BSE detailed-results JSON, standalone, basis-calibrated -----------------------
    code, csrc = SC.code_for(sym)
    res["scrip"] = code
    res["scrip_src"] = csrc
    if code:
        dr = D.read(code, qe)
        if dr and dr["span_ok"]:
            cal = P.calibrate(sym, qe, code, rows, dr)
            res["routes"].append("detres: %.2f span-ok calib=%s %s"
                                 % (dr["pat"], cal["verdict"], "; ".join(cal["notes"])))
            if cal["verdict"] == "standalone":
                res["std"].append({"src": "bse-detres", "value": dr["pat"],
                                   "ev": {"rev": dr["rev"], "type": dr["type"],
                                          "calib": cal["notes"]}})
        elif dr:
            res["routes"].append("detres: row is %s months ending %s -- not this quarter"
                                 % (dr.get("span"), dr.get("end")))
        else:
            res["routes"].append("detres: no row")
    else:
        res["routes"].append("bse-scrip: unresolved in live + delisted + suspended masters")

    # ---- decide whether the cheap rungs already settled it ------------------------------------
    def settled():
        s = [r["value"] for r in res["std"]]
        c = [r["value"] for r in res["con"]]
        if s and all(close(v, ss) for v in s):
            return True                          # std confirmed correct -> nothing more to prove
        if s and c:
            return True                          # both bases in hand -> decisive either way
        return False

    # ---- rung 3: BSE announcement PDF (both bases, column-anchored) ----------------------------
    if not settled() and code:
        try:
            pr = P.probe(sym, qe, fund, o, lcache)
        except Exception as ex:
            pr = {"routes": ["pdf-route ERROR %s: %s" % (type(ex).__name__, ex)]}
        res["routes"] += ["pdf/" + r for r in pr.get("routes", []) if not r.startswith("detres")]
        rd = pr.get("read") or {}
        for b in ("std", "con"):
            rec = rd.get(b) or {}
            if rec.get("accepted") and rec.get("value") is not None:
                res[b].append({"src": "bse-ann-pdf", "value": rec["value"],
                               "tier": rec.get("tier"), "garbled": rec.get("garbled"),
                               "ev": {"ann": rd.get("ann"), "page": rec["page"],
                                      "label": rec["label"], "unit_div": rec["unit_div"],
                                      "evidence": rec["evidence"], "header": rec.get("header"),
                                      "row": rec.get("raw_row"), "why": rec.get("why")}})

    # ---- rung 2: NSE archive detail pages ------------------------------------------------------
    if not settled():
        for want_con, bucket in ((False, "std"), (True, "con")):
            v, note = NA.read(sym, qe, want_con)
            res["routes"].append("nse-archive-%s: %s" % (bucket, note if v is None else
                                                          "%.2f (%s)" % (v, note)))
            if v is not None:
                res[bucket].append({"src": "nse-archive", "value": v, "ev": {"note": note}})

    # ---- verdict --------------------------------------------------------------------------------
    sv = [r["value"] for r in res["std"]]
    cv = [r["value"] for r in res["con"]]
    res["std_val"] = sv[0] if sv else None
    res["con_val"] = cv[0] if cv else None
    # a read carried by a single anchor deserves a human look before it is acted on
    # anything not carried by a confirmed column map gets a human read before it is acted on
    res["needs_eyes"] = any(r.get("tier") == "B" or len(r.get("ev", {}).get("evidence") or []) < 2
                            for r in res["std"] + res["con"] if r["src"] == "bse-ann-pdf")
    if len(sv) > 1 and not all(close(v, sv[0]) for v in sv[1:]):
        res["verdict"] = "CONFLICT-STD-SOURCES"
    elif not sv:
        res["verdict"] = "INCONCLUSIVE"
    elif close(sv[0], ss):
        res["verdict"] = "OK"
    elif cv and close(cv[0], ss):
        res["verdict"] = "DEFECT"
    elif cv:
        res["verdict"] = "OTHER-DEFECT"
    else:
        res["verdict"] = "STD-MISMATCH-CON-UNREAD"
    return res


def main():
    args = sys.argv[1:]
    fund = json.load(open(FUND))
    if "--cells" in args:
        cells = [(c.split(":")[0], int(c.split(":")[1]))
                 for c in args[args.index("--cells") + 1].split(",")]
    else:
        src = args[args.index("--from") + 1] if "--from" in args else "_sample.json"
        cells = [(c["sym"], c["qe"]) for c in json.load(open(os.path.join(HERE, src)))]
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    if "--redo" in args:
        for s, q in cells:
            out.pop("%s|%d" % (s, q), None)
    o = V.session()
    lcache = {}
    for sym, qe in cells:
        k = "%s|%d" % (sym, qe)
        if k in out:
            continue
        try:
            r = audit_cell(sym, qe, fund, o, lcache)
        except Exception as ex:
            r = {"verdict": "ERROR", "err": "%s: %s" % (type(ex).__name__, ex)}
        out[k] = r
        print("%-12s %d  %-22s std=%-10s con=%-10s stored=%s  [%s]"
              % (sym, qe, r["verdict"], r.get("std_val"), r.get("con_val"), r.get("stored_std"),
                 ",".join(sorted({x["src"] for x in r.get("std", []) + r.get("con", [])}))),
              flush=True)
        json.dump(out, open(OUT, "w"), indent=1, sort_keys=True)
    import collections
    print("\n" + " | ".join("%s=%d" % kv for kv in
          collections.Counter(v["verdict"] for v in out.values()).most_common()))


if __name__ == "__main__":
    main()
