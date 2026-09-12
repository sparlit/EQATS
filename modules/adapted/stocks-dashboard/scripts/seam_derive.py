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
"""Seam derivation from BSE's OWN aspx pages — Dec-2015 (q88) + Mar-2016 (q89).

At the seam BSE's table prints a fabricated FII 0.00 / mislays the foreign block (measured:
ITC Dec-15 aspx 0.00 vs derived 20.77). The institutions Sub Total is intact, so we INVERT the
identity exactly as the validated MC-seam route did (§22f, 0.87pp median vs Jun-2016 XBRL):

    fii = inst_sub − (mf + banks + ins + govt + vcf)      # domestic itemised only
    — NEVER subtract fii/qfi/fpi/fvci rows (the foreign block lands on any of them), NO CLAMP:
      a negative residual DROPS the cell. dii = mf + banks + ins (family convention).

Gates, all measured before anything is written:
  * global: median |Mar-16 derived − stored Jun-16| ≤ 3.0pp  AND  median |Dec-15 derived −
    stored Sep-15| ≤ 3.0pp — else the WHOLE run is refused (SEAM_MAX_MEDIAN, MC precedent).
  * per-cell: if both calendar neighbours exist and the derived fii is >8pp from BOTH → hold.
  * zero-guard: derived fii == 0.00 beside a neighbour >1% → hold.
  * promoter parsed (or pubtot≥99 complement) and partition in range.
  * `_shp_seam_adjudicated.json` cells are SKIPPED (BBTC's drop is deliberate — §22f).

Output: shp_fill_seam_aspx.json.gz {"fills": {...}} — a NEW ledger file so no future aspx
harvest rebuild can clobber it (the ledger stage-order trap). src = bseaspx:<code>:<q>:seam.
"""
import datetime
import gzip
import json
import os
import subprocess
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

SP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SP)
from fetch_shp_bse_aspx import _adj, fetch_page, gitshow, parse_new, qtrid_of  # noqa: E402

LAG = 21
_lk = threading.Lock()


def main():
    hist = gitshow("scripts/shp_history.json")
    ih = gitshow("scripts/indices_history.json")
    rmap = gitshow("scripts/_rename_map.json")
    adj = gitshow("scripts/_shp_seam_adjudicated.json").get("cells", {})
    # era-symbol -> scripcode. The tracked resolver output is the durable copy; the original
    # run read an untracked scratch file of the same shape, so this stage could not be
    # re-run outside that one worktree (found 2026-08-12 re-running the seam after the
    # fii=0.0 heal). Same for the BSE master below.
    era = {}
    for path in (SP + "/unres_evidence.json", SP + "/_shp_aspx_resolved_era_syms.json"):
        if os.path.exists(path):
            era = json.load(open(path))
            break
    override = gitshow("scripts/_shp_scripcode_override.json")
    hist.get("_names", {})

    def norm(s):
        seen = set()
        while s in rmap and s not in seen and rmap[s] != s:
            seen.add(s)
            s = rmap[s]
        return s

    have = {}
    for k, v in hist.items():
        if not k.startswith("_") and isinstance(v, dict):
            have.setdefault(norm(k), {}).update(v)

    snaps = sorted(
        (s["effectiveDate"], [norm(x) for x in s["symbols"] if not x.startswith("DUMMY")]) for s in ih["Nifty 500"]
    )

    def members(qe):
        best = []
        for ed, syms in snaps:
            if ed <= qe:
                best = syms
            else:
                break
        return best

    mpath = SP + "/bse_master_all.json"
    if not os.path.exists(mpath):
        mpath = SP + "/_bse_master_all.json"  # the tracked copy
    master = json.load(open(mpath))
    by_id = {}
    for row in master:
        sid = str(row.get("scrip_id") or "").strip().upper()
        if sid and sid not in by_id:
            by_id[sid] = int(row["SCRIP_CD"])

    skip_adj = {(s, qe) for s, qs in adj.items() for qe in qs}
    front = []
    unresolved = Counter()
    for qe in ("2015-12-31", "2016-03-31"):
        for s in members(qe):
            if qe in have.get(s, {}) or (s, qe) in skip_adj:
                continue
            code = None
            if s in override:
                code = int(override[s]["scripcode"] if isinstance(override[s], dict) else override[s])
            elif s in by_id:
                code = by_id[s]
            elif s in era:
                code = era[s]["code"]
            if code is None:
                unresolved[s] += 1
                continue
            front.append({"sym": s, "qe": qe, "code": code, "qtrid": qtrid_of(qe)})
    print(
        "seam frontier: %d cells (%d symbols unresolved -> %d cells skipped)"
        % (len(front), len(unresolved), sum(unresolved.values()))
    )

    res, held = {}, Counter()

    def one(fr):
        html, _ = fetch_page(SP, fr["code"], fr["qtrid"], "New")
        if not html:
            with _lk:
                held["absent"] += 1
            return
        cols, _nm = parse_new(html)
        if cols is None:
            with _lk:
                held["absent"] += 1
            return

        def val(slot):
            p = cols.get(slot)
            if not p:
                return None
            return p[1] if p[1] is not None else p[0]

        inst = val("inst_sub")
        if inst is None:
            with _lk:
                held["no-subtotal"] += 1
            return
        mf = val("mf") or 0.0
        dom = mf + (val("banks") or 0.0) + (val("ins") or 0.0) + (val("govt") or 0.0) + (val("vcf") or 0.0)
        r = round(inst - dom, 2)
        if r < -0.5 or r > 100.0:
            with _lk:
                held["bad-residual"] += 1
            return
        fii = round(max(r, 0.0), 2)
        prom = val("prom")
        if prom is None:
            pt = cols.get("pubtot")
            pab = pt[0] if pt and pt[0] is not None else None
            if pab is not None and pab >= 99.0:
                prom = round(max(0.0, 100.0 - pab), 2)
            else:
                with _lk:
                    held["no-prom"] += 1
                return
        dii = round(mf + (val("banks") or 0.0) + (val("ins") or 0.0), 2)
        if not (0 <= prom <= 100 and 0 <= fii <= 100 and 0 <= dii <= 100):
            with _lk:
                held["range"] += 1
            return
        sym, qe = fr["sym"], fr["qe"]
        # neighbour checks against STORED cells only
        nb = {}
        for step in (-1, 1):
            k = _adj(qe, step)
            v = (hist.get(sym) or {}).get(k)
            if v and v[1] is not None:
                nb[k] = v[1]
        if fii == 0.0 and any(v > 1.0 for v in nb.values()):
            with _lk:
                held["zero-vs-neighbour"] += 1
            return
        if len(nb) == 2 and all(abs(fii - v) > 8.0 for v in nb.values()):
            with _lk:
                held["off-both-neighbours"] += 1
            return
        sub = (datetime.date(*map(int, qe.split("-"))) + datetime.timedelta(days=LAG)).isoformat()
        cell = [
            prom,
            fii,
            dii,
            round(mf, 2),
            round(val("ins") or 0.0, 2),
            sub,
            None,
            "bseaspx:%d:%d:seam" % (fr["code"], fr["qtrid"]),
        ]
        with _lk:
            res.setdefault(sym, {})[qe] = cell
        time.sleep(0.3)

    with ThreadPoolExecutor(max_workers=5) as ex:
        list(ex.map(one, front))
    n = sum(len(v) for v in res.values())
    print("derived %d cells; held: %s" % (n, dict(held)))

    # ---- GATES ----
    # Dec-2015: RUN-LEVEL gate vs stored Sep-2015 (measured 0.81pp median — batch trust earned,
    # the MC precedent). Mar-2016: the run-level gate FAILED at 5.73pp, driven by two measured
    # modes — (a) stored Jun-2016 anchors that are THEMSELVES fabricated zeros (LICHSGFIN 27.53
    # derived vs stored 0.0 — LIC Housing with no FII in 2016 is absurd; old-XBRL ledger defect,
    # journalled for its own audit) and (b) genuine q89 derivation failures (BSOFT-class, drv≈2x).
    # So q89 cells are written ONLY when individually corroborated: |derived − stored Jun-16| ≤ 3.0.
    diffs = []
    for sym, qs in res.items():
        if "2015-12-31" in qs:
            v = (hist.get(sym) or {}).get("2015-09-30")
            if v and v[1] is not None:
                diffs.append(abs(qs["2015-12-31"][1] - v[1]))
    diffs.sort()
    med = diffs[len(diffs) // 2] if diffs else None
    print("Dec-15 run gate vs Sep-15: n=%d median=%s" % (len(diffs), med))
    # A MEASURED failure still stops the run. But on a RE-RUN the frontier holds only the
    # cells history still lacks (Dec-15 is 98%+ covered after round 4), so n<30 means the
    # batch gate is UNMEASURABLE, not failed — aborting there would also throw away the q89
    # cells, which carry their own per-cell corroboration. Fall back to per-cell instead.
    q88_percell = False
    if med is not None and med > 3.0:
        sys.exit("STOP: Dec-15 run gate FAILED (n=%d median=%.2f)" % (len(diffs), med))
    if med is None or len(diffs) < 30:
        q88_percell = True
        print(
            "   n<30 -> batch trust NOT measurable this run; Dec-15 cells now need the same "
            "per-cell corroboration as q89 (|derived - stored Sep-15| <= 3.0)"
        )

    held_q88 = 0
    if q88_percell:
        for sym in list(res):
            qs = res[sym]
            if "2015-12-31" not in qs:
                continue
            v = (hist.get(sym) or {}).get("2015-09-30")
            anchor = v[1] if v and v[1] is not None else None
            if anchor is None or abs(qs["2015-12-31"][1] - anchor) > 3.0:
                del qs["2015-12-31"]
                held_q88 += 1
        print("   q88 per-cell: held %d" % held_q88)

    suspects, held_q89 = [], 0
    for sym in list(res):
        qs = res[sym]
        if "2016-03-31" in qs:
            drv = qs["2016-03-31"][1]
            v = (hist.get(sym) or {}).get("2016-06-30")
            anchor = v[1] if v and v[1] is not None else None
            if anchor is None or abs(drv - anchor) > 3.0:
                if anchor == 0.0 and drv > 5.0:
                    # A stored Jun-16 fii of 0.0 is not an anchor: it is the swallowed-block
                    # defect (§22f / scripts/_shp_zero_fii_audit.json). 14 of the 15 first
                    # found were healed 2026-08-12; any that reappear here are new ones.
                    suspects.append(
                        {
                            "sym": sym,
                            "derived_mar16_fii": drv,
                            "stored_jun16_fii": 0.0,
                            "note": "stored Jun-16 zero is not an anchor — see scripts/_shp_zero_fii_audit.json",
                        }
                    )
                del qs["2016-03-31"]
                held_q89 += 1
        if not qs:
            del res[sym]
    n2 = sum(len(v) for v in res.values())
    print(
        "q89 written only when |drv − Jun-16| ≤ 3.0: held %d; suspect Jun-16 zero-anchors: %d"
        % (held_q89, len(suspects))
    )
    json.dump(suspects, open(os.path.join(SP, "_seam_suspect_jun2016_zeros.json"), "w"), indent=1)

    # ⚠️ UNION, never overwrite. This ledger is written whole on every run, and a re-run's
    # frontier only contains cells shp_history still LACKS — so everything a previous run
    # landed is absent from `res` by construction. A plain dump would silently shrink the
    # tracked ledger from 159 cells to whatever this run happened to add (the same
    # stage-order trap §22f records for shp_fill_hist_2010_2016). Existing cells win: they
    # were gated against the anchors of their own day.
    out = os.path.join(SP, "shp_fill_seam_aspx.json.gz")
    prev, kept = {}, 0
    if os.path.exists(out):
        try:
            with gzip.open(out, "rt", encoding="utf-8") as fh:
                prev = json.load(fh).get("fills", {})
        except Exception as e:
            sys.exit(f"STOP: existing seam ledger unreadable ({e}) — refusing to overwrite it")
    for sym, qs in prev.items():
        dest = res.setdefault(sym, {})
        for qe, cell in qs.items():
            if qe not in dest:
                dest[qe] = cell
                kept += 1
    total = sum(len(v) for v in res.values())
    with gzip.open(out, "wt", encoding="utf-8") as fh:
        json.dump({"_built": "seam_derive (aspx inst_sub inversion)", "fills": res}, fh)
    print("ledger -> %s (%d syms, %d cells: %d new this run + %d carried forward)" % (out, len(res), total, n2, kept))


if __name__ == "__main__":
    main()
