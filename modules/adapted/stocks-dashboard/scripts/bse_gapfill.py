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
"""Fill interior quarter-gaps (2018+) in docs/sf_fundamentals.json from BSE filing PDFs (text layer),
with an OVERLAP-VALIDATION gate: each BSE filing also reports the surrounding quarters we already
hold from NSE, so we only trust (and fill) a stock's gaps when the BSE extraction AGREES with the
existing NSE values on the quarters they share. Reuses bse_text's parser + consensus.

  python bse_gapfill.py 0 60      # process gap-stocks [0:60)
Writes _gapfill/<batch>.json = {SYM: {"fills": [[qe,std,con,ann]...], "agree":x, "overlap":y}}
"""
import json
import os
import statistics
import sys
import time

import bse_text as T
import bse_vision as V

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "_gapfill")
os.makedirs(OUT, exist_ok=True)
FUND = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))
GAPS = json.load(open(os.path.join(HERE, "_gaps.json")))
SC = json.load(open(os.path.join(HERE, "bse_scrips.json")))["by_id"]
STAND = {"ABBOTINDIA", "BAYERCROP", "KENNAMET", "SPICEJET"}


def close(a, b):
    return a is not None and b is not None and abs(a - b) <= max(0.5, abs(a) * 0.04)


def extract(o, code, since):
    fl = V.filings(o, code, pages=30, since=since)
    obs = {}
    anns = {}
    for ann, att in sorted(fl):
        pdf = None
        for base in ("AttachHis", "AttachLive"):
            try:
                d = V.get(o, f"https://www.bseindia.com/xml-data/corpfiling/{base}/{att}", b=True)
                if d[:4] == b"%PDF":
                    pdf = d
                    break
            except Exception:
                continue
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
                if qmap[ci]:
                    obs.setdefault((qmap[ci], basis), []).append(val)
        time.sleep(0.25)
    ser = {}
    sup = {}
    for (qe, b), vals in obs.items():
        v, s, _tot = T.consensus(vals)
        ser[(qe, b)] = v
        sup[(qe, b)] = s
    return ser, anns, sup


def main():
    lo, hi = int(sys.argv[1]), int(sys.argv[2])
    stocks = [s for s in sorted(GAPS) if any(q >= 20180101 for q in GAPS[s]) and s in SC][lo:hi]
    outf = os.path.join(OUT, "%d_%d.json" % (lo, hi))
    res = json.load(open(outf)) if os.path.exists(outf) else {}  # resume
    o = V.session()
    for i, sym in enumerate(stocks):
        if sym in res:
            continue  # already done
        miss = sorted(q for q in GAPS[sym] if q >= 20180101)
        since = "%d0101" % (miss[0] // 10000 - 1)  # a year before earliest gap (for context cols)
        try:
            ser, anns, sup = extract(o, SC[sym], since)
        except Exception as e:
            print(f"  {sym} EXTRACT-ERR {e}", flush=True)
            continue
        ex = {r[0]: r for r in FUND.get(sym, [])}
        # validate: compare extraction to existing NSE values on overlapping quarters
        agree = ov = 0
        for qe, row in ex.items():
            for bi, b in ((1, "s"), (3, "c")):
                if row[bi] is not None and (qe, b) in ser and ser[(qe, b)] is not None:
                    ov += 1
                    agree += close(row[bi], ser[(qe, b)])
        rate = agree / ov if ov else 0
        med = statistics.median(
            [abs(row[bi]) for row in ex.values() for bi in (1, 3) if row[bi] is not None and abs(row[bi]) > 0.01] or [0]
        )

        def ok(qe, b):  # corroborated (>=2 filings) and not a magnitude outlier (YTD/9M)
            v = ser.get((qe, b))
            return v is not None and sup.get((qe, b), 0) >= 2 and (med <= 0 or abs(v) <= med * 6)

        fills = []
        if ov >= 4 and rate >= 0.8:  # extraction trusted
            for qe in miss:
                s = ser.get((qe, "s")) if ok(qe, "s") else None
                c = ser.get((qe, "c")) if ok(qe, "c") else None
                if sym in STAND:
                    c = c if c is not None else s
                    s = c
                if s is None and c is None:
                    continue
                fills.append([qe, s, c, anns.get(qe, miss[0])])
        res[sym] = {"fills": fills, "agree": agree, "overlap": ov, "rate": round(rate, 2)}
        print(
            "  [%d/%d] %-12s overlap=%d agree=%.0f%% -> %d gap-fills"
            % (lo + i + 1, lo + len(stocks), sym, ov, rate * 100, len(fills)),
            flush=True,
        )
        json.dump(res, open(outf, "w"))  # incremental save (resumable)
    json.dump(res, open(outf, "w"))
    filled = sum(len(r["fills"]) for r in res.values())
    print("BATCH %d-%d DONE: %d stocks, %d validated gap-fills" % (lo, hi, len(res), filled), flush=True)


if __name__ == "__main__":
    main()
