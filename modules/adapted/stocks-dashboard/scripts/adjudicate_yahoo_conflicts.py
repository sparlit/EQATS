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
"""Resolve the YAHOO_SPLIT verdicts of scripts/ca_review_verdicts.json (DATA_RUNBOOK §161h).

Each is a factor baked into the price bins with no exchange record, where Yahoo's split-EVENT record
(a third-party record, not its adjusted closes) matches the factor. Rule — the §87 campaign's
standard, record + tape — fixed before it was run:

  REAL_YAHOO_TAPE  Yahoo's split record matches F within 3% (given), no exchange record contradicts it,
                   AND the tape agrees: the ex-day OPEN sits at the adjusted basis ((open/prev)/F in
                   [0.88,1.12], the §87c band) OR — for large factors (F <= 0.25 or F >= 4, where the
                   share count change dominates volume) — the persistent volume step is within 2x of
                   1/F; AND no large-factor volume step contradicts it (> 3x away from 1/F).
                   -> keep the adjustment; record the factor in corp_actions_hist.json.
  YAHOO_CONFLICT   anything else — stays as is, reason stated.

  REAL_YAHOO_FILING  a conflict above settled by a THIRD measured source listed in MEASURED below — the
                   company's own results filings (shares = PAT / EPS, docs/fin) stepping by 1/F across
                   the event, or for an ETF its holdings' same-day moves (a unit split vs a real loss).

Volume step = median traded shares over the 10 sessions after the ex-day / the 10 before.
Run: python3 scripts/adjudicate_yahoo_conflicts.py <dir with sf_deep_*.bin + sf_recent_*.bin> [--apply]
"""
import glob
import gzip
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


# Measured 2026-09-25 (§161h). Each entry: (sym, ex) -> the measurement that settles the conflict.
MEASURED = {
    ("HEG", 20241018): "results filings: shares (PAT/EPS) 3.851-3.859 cr in Dec-23..Jun-24 quarters -> "
    "19.28-19.32 cr from Sep-24 on = x5.00, a 1:5 split (Yahoo 2024-10-18 1:5)",
    ("VERTOZ", 20250711): "results filings: shares ~84-98 cr (Sep-24..Mar-25, after the official x0.05 of "
    "2024-07-05) -> 8.40-8.70 cr from Jun-25 on = /10, a 10:1 consolidation (Yahoo 2025-06-25)",
    ("LOWVOLIETF", 20240301): "ETF of Nifty100 low-vol stocks: 90 largest stocks moved -2.24%..+6.46% (median "
    "+1.19%) that day, so a raw x0.1006 cannot be a loss — a 1:10 unit split (Yahoo "
    "2024-03-01; NV20IETF and PVTBANIETF split x0.1 the same day); adjusted move +0.67%",
}


def main():
    d = sys.argv[1]
    VP = os.path.join(HERE, "ca_review_verdicts.json")
    VV = json.load(open(VP))
    E = {(e["sym"], e["b"]): e for e in json.load(open(os.path.join(HERE, "ca_review_evidence.json")))["events"]}
    todo = [v for v in VV["verdicts"] if v["verdict"] == "YAHOO_SPLIT"]
    syms = {v["sym"] for v in todo}
    ser = {}
    for f in sorted(glob.glob(os.path.join(d, "*deep_*.bin"))) + sorted(glob.glob(os.path.join(d, "*recent_*.bin"))):
        D = json.loads(gzip.open(f).read())
        for s in syms:
            o = D["data"].get(s)
            if o:
                for i, x in enumerate(o["d"]):
                    ser.setdefault(s, {})[x] = o["v"][i]
    H = json.load(open(os.path.join(HERE, "corp_actions_hist.json")))
    n_h = 0
    for v in todo:
        F = v["F"]
        e = E[(v["sym"], v["b"])]
        m = ser.get(v["sym"], {})
        ds = sorted(m)
        j = ds.index(v["b"]) if v["b"] in m else None
        vr = None
        if j is not None:
            pre = [m[x] for x in ds[max(0, j - 10) : j] if m[x]]
            post = [m[x] for x in ds[j + 1 : j + 11] if m[x]]
            if len(pre) >= 3 and len(post) >= 3:
                vr = statistics.median(post) / statistics.median(pre)
        og = e.get("open_over_prev_bhav")
        gate = (og / F) if og else None
        large = F <= 0.25 or F >= 4
        open_ok = gate is not None and 0.88 <= gate <= 1.12
        vol_ok = large and vr is not None and 0.5 <= vr * F <= 2.0
        vol_bad = large and vr is not None and not (1 / 3 <= vr * F <= 3.0)
        ev = {
            "open_gate": round(gate, 4) if gate else None,
            "vol_step": round(vr, 3) if vr else None,
            "vol_expected": round(1 / F, 2),
            "yahoo": v["evidence"].get("yahoo"),
        }
        measured = MEASURED.get((v["sym"], v["b"]))
        if ((open_ok or vol_ok) and not vol_bad) or measured:
            v["verdict"] = (
                "REAL_YAHOO_FILING" if measured and not ((open_ok or vol_ok) and not vol_bad) else "REAL_YAHOO_TAPE"
            )
            if measured:
                ev["measured"] = measured
            v["evidence"] = ev
            y = ev["yahoo"][0]
            lst = H["factors"].setdefault(v["sym"], [])
            if not any(abs(int(x[0]) - y["date"]) <= 3 for x in lst):
                lst.append([y["date"], round(y["factor"], 6)])
                lst.sort()
                n_h += 1
        else:
            why = []
            if not open_ok:
                why.append("open gate {} outside [0.88,1.12]".format(ev["open_gate"]))
            if large and not vol_ok:
                why.append("volume step {} vs ~{} for a real split".format(ev["vol_step"], ev["vol_expected"]))
            v["verdict"] = "YAHOO_CONFLICT"
            ev["why"] = why
            v["evidence"] = ev
        print(
            "%-15s %-11s %d F=%.3f open_gate=%s vol=%s (split=>%s)"
            % (v["verdict"], v["sym"], v["b"], F, ev["open_gate"], ev["vol_step"], ev["vol_expected"])
        )
    if "--apply" in sys.argv:
        json.dump(VV, open(VP, "w"), indent=0)
        json.dump(H, open(os.path.join(HERE, "corp_actions_hist.json"), "w"), indent=0)
        print("applied: %d factors recorded in corp_actions_hist.json" % n_h)


if __name__ == "__main__":
    main()
