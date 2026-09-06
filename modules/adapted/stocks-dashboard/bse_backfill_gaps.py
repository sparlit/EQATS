# -*- coding: utf-8 -*-
"""Backfill the consolidated-quarter gaps that NSE's feed lacks (see backfill_gaps.py finding:
the gaps are NSE-source-absent, recoverable only from BSE). For each gapped Nifty500 symbol in
_gap_work.json, pull its result filings from BSE and read net profit from the PDF TEXT LAYER
(bse_text), then a separate merge step fills the missing quarters into docs/sf_fundamentals.json.

Per-symbol, single shared session (re-warmed on error), paced, resumable: each symbol's quarters
are written to _bse_text/<SYM>.json (same format bse_text.main writes), so a re-run skips done work.
`since` is bounded to ~1yr before the symbol's earliest gap to keep the filing count small.

Run:  python -X utf8 bse_backfill_gaps.py            # all symbols in _gap_codes.json
      python -X utf8 bse_backfill_gaps.py SYM1 SYM2  # just these
"""
import os, sys, json, time
import bse_text as T, bse_vision as V

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = T.OUT  # scripts/_bse_text
work = json.load(open(os.path.join(HERE, "_gap_work.json")))
codes = json.load(open(os.path.join(HERE, "_gap_codes.json")))

def fetch_pdf(o, att):
    for base in ("AttachHis", "AttachLive"):
        try:
            d = V.get(o, "https://www.bseindia.com/xml-data/corpfiling/%s/%s" % (base, att), b=True)
            if d[:4] == b"%PDF": return d
        except Exception:
            continue
    return None

def do_symbol(o, sym, code, since):
    fl = V.filings(o, code, pages=30, since=since)
    if not fl:
        return None, 0
    obs = {}; anns = {}
    for ann, att in sorted(fl):
        pdf = fetch_pdf(o, att)
        if not pdf:
            continue
        try:
            r = T.parse_pdf(pdf, ann)
        except Exception:
            r = None
        if not r:
            continue
        std_c, con_c, _ = r
        qe = T.qe_from_ann(ann)
        anns[qe] = min(ann, anns.get(qe, ann))
        for basis, cols in (("s", std_c), ("c", con_c)):
            if not cols:
                continue
            qmap = [qe, T.prev_q(qe), qe - 10000]
            for ci, val in enumerate(cols[:3]):
                tq = qmap[ci]
                if tq:
                    obs.setdefault((tq, basis), []).append(val)
        time.sleep(0.3)
    qes = sorted(set(q for q, b in obs))
    arr = []
    for qe in qes:
        sv, ss, st = T.consensus(obs.get((qe, "s"), []))
        cv, cs, ct = T.consensus(obs.get((qe, "c"), []))
        arr.append([qe, sv, cv, anns.get(qe, 0), [ss, st], [cs, ct]])
    import statistics
    for idx in (1, 2):
        vals = [abs(r[idx]) for r in arr if r[idx] is not None and abs(r[idx]) > 0.01]
        if len(vals) >= 4:
            med = statistics.median(vals)
            for r in arr:
                if r[idx] is not None and med > 0 and abs(r[idx]) > med * 20:
                    r[idx] = round(r[idx] / 100.0, 2)
    return arr, len(fl)

def main():
    args = sys.argv[1:]
    syms = [s for s in (args or codes) if s in codes]
    print("backfilling %d symbols from BSE" % len(syms), flush=True)
    o = V.session()
    done = 0; proc = 0
    for sym in syms:
        outf = os.path.join(OUT, "%s.json" % sym)
        if os.path.exists(outf):
            done += 1; continue
        if proc and proc % 10 == 0:        # re-warm session periodically to dodge BSE throttling
            time.sleep(3); o = V.session()
        proc += 1
        since = "%d0101" % (min(work[sym]) // 10000 - 1)
        try:
            arr, nfl = do_symbol(o, sym, codes[sym], since)
        except Exception as e:
            print("  %-12s ERROR %s -> re-session" % (sym, e), flush=True)
            time.sleep(5); o = V.session()
            try:
                arr, nfl = do_symbol(o, sym, codes[sym], since)
            except Exception as e2:
                print("  %-12s ERROR(2) %s -> skip" % (sym, e2), flush=True)
                continue
        if arr is None:
            print("  %-12s no filings since %s" % (sym, since), flush=True)
            json.dump([], open(outf, "w")); continue
        json.dump(arr, open(outf, "w"))
        got = {q: (s, c) for q, s, c, *_ in arr}
        hit = {q: got.get(q) for q in work[sym]}
        done += 1
        print("  [%d/%d] %-12s %d filings -> %d q  gaps:%s" % (done, len(syms), sym, nfl, len(arr), hit), flush=True)
        time.sleep(0.5)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
