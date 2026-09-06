# -*- coding: utf-8 -*-
"""Build docs/results_coverage.json — the feed behind docs/results-coverage.html.

Answers, for the current quarter: how many companies DECLARED a result, how many we have
NUMBERS for, and how many are still empty (plus exactly which ones, and why).

Counts come from results_pending.classify(), the same module the scheduled vision routine
(bse_vision_prep.py) uses to pick its work — so the dashboard can never disagree with what
the routine will actually fill.

Run: python -X utf8 scripts/build_results_coverage.py
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from results_pending import classify, _load

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "docs", "results_coverage.json")


def qlabel(qe):
    """20260630 -> 'Q1 FY27' (Indian fiscal year: Apr-Mar)."""
    y, m = int(str(qe)[:4]), int(str(qe)[4:6])
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(m)
    fy = y + 1 if m >= 6 else y
    return "Q%s FY%s" % (q, str(fy)[2:]) if q else str(qe)


def main():
    qe, rows = classify()
    vf = _load("vision_fills.json") or {}
    bf = (_load("bse_fundamentals.json") or {}).get("px", {})
    sqe = str(qe)

    def by_vision(e):
        if e["exch"] == "NSE":
            return e["sym"] in vf and sqe in vf.get(e["sym"], {})
        d = bf.get(e["scrip"], {}).get(sqe) or {}
        return d.get("src") == "vision"

    stat = {"declared": len(rows), "filled": 0, "pending": 0, "no_pdf": 0, "bse_dup": 0, "vision": 0}
    ex = {"NSE": dict(declared=0, filled=0, open=0), "BSE": dict(declared=0, filled=0, open=0)}
    out_rows = []
    for e in rows:
        s = e["status"]
        stat[s] = stat.get(s, 0) + 1
        x = ex[e["exch"]]
        x["declared"] += 1
        if s == "filled":
            x["filled"] += 1
            if by_vision(e):
                stat["vision"] += 1
        else:
            if s != "bse_dup":
                x["open"] += 1
            out_rows.append([e["sym"], e["name"], e["exch"], round(e["mcap"] or 0, 1), e["ann"], s])

    # biggest first — the ones that matter most are the ones you want to see at the top
    out_rows.sort(key=lambda r: -(r[3] or 0))
    # "open" = declared but no numbers yet, i.e. what the routine still owes you
    stat["open"] = stat["pending"] + stat["no_pdf"]
    doc = {
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "qe": qe,
        "qlabel": qlabel(qe),
        "stat": stat,
        "byExch": ex,
        "cols": ["sym", "name", "exch", "mcap", "declared_on", "status"],
        "rows": out_rows,
    }
    json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("WROTE %s: %s — %d declared, %d filled, %d open (%d pending, %d no-pdf), %d of the filled came from vision"
          % (os.path.normpath(OUT), doc["qlabel"], stat["declared"], stat["filled"],
             stat["open"], stat["pending"], stat["no_pdf"], stat["vision"]))


if __name__ == "__main__":
    main()
