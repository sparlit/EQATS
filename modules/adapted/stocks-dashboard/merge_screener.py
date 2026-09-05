# -*- coding: utf-8 -*-
"""Merge Screener pre-IPO quarters into sf_fundamentals.json as YoY bases — BOTH standalone and
consolidated. Each basis is validated independently against NSE on the overlapping (post-listing)
quarters; only a basis that matches NSE is trusted. Pre-IPO quarters are added as
[qe, npStd|None, None, npCon|None, None] (dates null -> used only as the year-ago base, never as a
current quarter -> point-in-time-safe). Never overwrites an existing NSE quarter. Atomic write.
"""
import json, os
import build_fundamentals as bf
DOCS = os.path.join(os.path.dirname(bf.HERE), "docs", "sf_fundamentals.json")
OUT = bf.OUT
SCR = os.path.join(bf.HERE, "screener_pre.json")

def close(a, b):
    return a is not None and b is not None and abs(a - b) <= max(2, abs(a) * 0.05)

def main():
    nse = json.load(open(DOCS)); scr = json.load(open(SCR))
    added_sym = added_q = skipped = 0; rep = []
    for sym, d in scr.items():
        std = {int(k): v for k, v in d.get("std", {}).items()}
        con = {int(k): v for k, v in d.get("con", {}).items()}
        have = {r[0]: (r[1], r[3]) for r in nse.get(sym, [])}
        def valid(vals, idx):
            ov = [(qe, vals[qe]) for qe in vals if qe in have and have[qe][idx] is not None]
            if not ov: return False
            return sum(1 for qe, v in ov if close(have[qe][idx], v)) >= len(ov) * 0.8
        std_ok = valid(std, 0); con_ok = valid(con, 1)
        if not (std_ok or con_ok):
            skipped += 1; continue
        rows = {r[0]: list(r) for r in nse.get(sym, [])}
        newq = 0
        for qe in sorted(set(std) | set(con)):
            if qe in rows: continue                       # never overwrite NSE
            sv = std.get(qe) if std_ok else None
            cv = con.get(qe) if con_ok else None
            if sv is None and cv is None: continue
            rows[qe] = [qe, sv, None, cv, None]; newq += 1
        if newq:
            nse[sym] = [rows[k] for k in sorted(rows)]
            added_sym += 1; added_q += newq
            rep.append((sym, newq, "std" if std_ok else "", "con" if con_ok else ""))
    for path in (DOCS, OUT):
        tmp = path + ".tmp"; json.dump(nse, open(tmp, "w"), separators=(",", ":")); os.replace(tmp, path)
    print("merged pre-IPO bases into %d symbols (%d quarters); %d skipped (no/failed overlap)" % (added_sym, added_q, skipped))
    print("sample:", rep[:12])

if __name__ == "__main__":
    main()
