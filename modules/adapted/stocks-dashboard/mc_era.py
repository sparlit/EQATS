# -*- coding: utf-8 -*-
"""ERA-AWARE Moneycontrol resolution + reach measurement for the pre-2015 window.

Why this exists on top of agg_sources.mc_id: that resolver accepts ONLY a row whose NSE-symbol
token equals ours, which is the right gate for a live symbol and useless for a 2002-2014 name.
Companies rename (HIMACHLFUT -> HFCL), delist, and merge, and MC prints only the CURRENT symbol.
So the ladder here is, strongest gate first, and it never guesses:

  R1  exact NSE-symbol token in autosuggest              (agg_sources.mc_id, URL-encoded)
  R2  autosuggest BY OUR ISIN, accept only a row whose printed ISIN equals it exactly
      -- ISIN survives renames, so this is what reaches the era names. Measured 2026-08-12:
         querying INE168A01041 returns exactly Jammu and Kashmir Bank / JKB.
  R3  unresolved. Never a name-similarity guess (memory: feedback-scrip-id-ticker-coincidence).

ISIN comes from scripts/_bse_master_all.json (10,786 rows, Active AND Delisted, ISIN + scrip_id).
⚠️ scrip_id is BSE's ticker and equals the NSE symbol only by convention, so a resolution that
came through R2 records `isin_src` and the BSE row it came from -- and the value gate in
agg_gate.py still has to reproduce our stored quarters before any number is written.

Nothing here writes into a dataset.

  python3 -X utf8 scripts/agg_tools/mc_era.py --cells /tmp/open_cells_0214.json --out /tmp/reach.json
"""
import argparse
import collections
import json
import os
import re
import sys
import time
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, HERE)
import agg_sources as A                                            # noqa: E402

_MASTER = None
_ISIN_CACHE = os.path.join(HERE, "_mc_era_ids.json")


def bse_master():
    global _MASTER
    if _MASTER is None:
        rows = json.load(open(os.path.join(SCRIPTS, "_bse_master_all.json")))
        by = collections.defaultdict(list)
        for r in rows:
            sid = (r.get("scrip_id") or "").strip().upper()
            if sid and r.get("ISIN_NUMBER"):
                by[sid].append(r)
        _MASTER = by
    return _MASTER


def isin_for(sym):
    """-> (isin, note) or (None, why). Active row preferred over a Delisted one."""
    rows = bse_master().get(sym.upper()) or []
    if not rows:
        return None, "no BSE scrip_id == %s in the 10,786-row master" % sym
    act = [r for r in rows if (r.get("Status") or "") == "Active"] or rows
    r = act[0]
    return r["ISIN_NUMBER"], "bse_master scrip_id=%s code=%s status=%s name=%s" % (
        r.get("scrip_id"), r.get("SCRIP_CD"), r.get("Status"), (r.get("Scrip_Name") or "")[:40])


def _sugg_rows(q, tag):
    txt = A._get("www.moneycontrol.com", A.MC_SUGGEST % quote(q, safe=""), A.MC_PACE, "mc",
                 tag + re.sub(r"[^A-Za-z0-9]", "_", q), ttl=86400 * 30)
    try:
        rows = json.loads(txt) if txt else []
    except ValueError:
        rows = []
    out = []
    for r in rows if isinstance(rows, list) else []:
        dis = re.sub(r"<[^>]+>", "", (r.get("pdt_dis_nm") or "")).replace("&nbsp;", " ")
        m = re.search(r"(INE[0-9A-Z]{9}|IN[0-9A-Z]{10})\s*,\s*([A-Z0-9&_-]*)\s*,?\s*(\d*)", dis)
        out.append({"sc_id": r.get("sc_id") or "", "name": r.get("stock_name") or "",
                    "isin": m.group(1) if m else None, "sym": m.group(2) if m else None,
                    "bse": m.group(3) if m else None})
    return out


def resolve(sym, cache=None):
    """-> dict(sc_id, via, isin, mc_sym, note) or None. Gated at every rung."""
    if cache is not None and sym in cache:
        return cache[sym]
    out = None
    hit = A.mc_id(sym)                                     # R1: exact NSE symbol token
    if hit and hit.get("sc_id"):
        out = {"sc_id": hit["sc_id"], "via": "symbol", "isin": hit.get("isin"),
               "mc_sym": sym, "note": "autosuggest exact symbol token"}
    else:
        isin, isrc = isin_for(sym)                         # R2: ISIN equality
        if isin:
            for r in _sugg_rows(isin, "isin_"):
                if r["isin"] and r["isin"].upper() == isin.upper() and r["sc_id"]:
                    out = {"sc_id": r["sc_id"], "via": "isin", "isin": isin,
                           "mc_sym": r["sym"], "mc_name": r["name"],
                           "note": "ISIN query matched exactly; ours from %s" % isrc}
                    break
            if out is None:
                out = None if False else None
        # R3: give up rather than guess
    if cache is not None:
        cache[sym] = out
        json.dump(cache, open(_ISIN_CACHE, "w"), indent=0, sort_keys=True)
    return out


def quarters(ident, con=False):
    """MC quarterly table for an ALREADY-RESOLVED sc_id (agg_sources.mc_quarters needs a symbol)."""
    tf = "cons_quarterly" if con else "quarterly"
    txt = A._get("appfeeds.moneycontrol.com", A.MC_FEED % (ident["sc_id"], tf), A.MC_PACE,
                 "mc", "q_%s_%s" % (ident["sc_id"], tf))
    if txt is None:
        return {}, "mc: BLOCKED-TRANSPORT"
    try:
        rows = (json.loads(txt) or {}).get("data") or []
    except ValueError:
        return {}, "mc: unparseable"
    if not isinstance(rows, list) or not rows:
        return {}, "mc: empty %s table" % tf
    out, dupes = {}, set()
    for r in rows:
        qe = A.qe_from_label(r.get("yrc0"))
        if qe is None:
            continue
        if qe in out:
            dupes.add(qe)
            continue
        # the same rows + derivations as agg_sources.mc_quarters -- the era reader used to skip
        # MC_DERIVED, so an ISIN-resolved symbol had no op candidate and every op cell read as
        # NOT-FOUND (found 2026-09-05)
        vals = A.mc_row_values(r)
        if vals:
            out[qe] = vals
    for qe in dupes:
        out.pop(qe, None)
    return out, "mc: %d periods %s..%s" % (len(out), min(out, default="-"), max(out, default="-"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    cells = json.load(open(a.cells))
    gaps = collections.defaultdict(list)
    for sym, qe, field in cells:
        gaps[sym].append(qe)
    syms = sorted(gaps, key=lambda s: -len(gaps[s]))
    if a.limit:
        syms = syms[:a.limit]

    cache = json.load(open(_ISIN_CACHE)) if os.path.exists(_ISIN_CACHE) else {}
    res, t0 = {}, time.time()
    tot_gap = tot_hit = 0
    for i, sym in enumerate(syms):
        g = sorted(gaps[sym])
        ident = resolve(sym, cache)
        rec = {"gaps": len(g), "first_gap": g[0], "last_gap": g[-1]}
        if not ident:
            rec.update({"resolved": False, "why": "R1 symbol + R2 ISIN both failed"})
        else:
            series, note = quarters(ident, con=False)
            hits = [q for q in g if q in series and series[q].get("pat_total") is not None]
            offframe = [q for q in series if q % 10000 not in (331, 630, 930, 1231)]
            rec.update({"resolved": True, "sc_id": ident["sc_id"], "via": ident["via"],
                        "mc_sym": ident.get("mc_sym"), "isin": ident.get("isin"),
                        "periods": len(series), "oldest": min(series) if series else None,
                        "offframe_periods": len(offframe),
                        "have": len(hits), "note": note})
            tot_hit += len(hits)
        tot_gap += len(g)
        res[sym] = rec
        if (i + 1) % 25 == 0 or i == len(syms) - 1:
            print("[%3d/%3d] %-12s gaps=%-3d have=%-3d  (%.0fs)  running %d/%d"
                  % (i + 1, len(syms), sym, rec["gaps"], rec.get("have", 0),
                     time.time() - t0, tot_hit, tot_gap))
            sys.stdout.flush()
            json.dump(res, open(a.out, "w"), indent=1, sort_keys=True)

    json.dump(res, open(a.out, "w"), indent=1, sort_keys=True)
    nres = sum(1 for r in res.values() if r.get("resolved"))
    print("\nresolved %d/%d symbols; %d of %d gap quarters carry an MC standalone PAT (%.1f%%)"
          % (nres, len(res), tot_hit, tot_gap, 100.0 * tot_hit / max(1, tot_gap)))


if __name__ == "__main__":
    main()
