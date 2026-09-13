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
"""ROW-IDENTITY: is the stored value another LINE of the same as-filed statement?

`_vintage108_raw.json` holds every row BSE's detailed-results JSON served for the cell (values in
Rs million, /10 -> crore). If the stored number reproduces one of those lines to the paisa, the
defect is NAMED — a wrong-row read (§100f), not a mystery — and the correct line is the one the
same document calls Net Profit.  memory: feedback-row-identity-proof
"""
import json
import os
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
SKIP = ("Date Begin", "Date End", "Type")


def main():
    b = json.load(open(os.path.join(HERE, "_vintage109_byprod.json")))["cells"]
    raw = json.load(open(os.path.join(HERE, "_vintage108_raw.json")))
    hits, cnt = [], Counter()
    for k, r in b.items():
        f = raw.get("%s|%d" % (r["sym"], r["qe"]))
        if not f:
            cnt["no-detres-statement"] += 1
            continue
        st = r["stored"]
        found = []
        for lab, v in f.items():
            if lab in SKIP or v in (None, "", "-"):
                continue
            try:
                x = float(v) / 10.0
            except ValueError:
                continue
            if abs(x - st) <= max(0.02, abs(st) * 0.0015):
                found.append((lab, round(x, 4)))
        if found:
            hits.append((k, r, found))
            cnt["stored-IS-a-line-of-the-statement"] += 1
        else:
            cnt["stored-matches-no-line"] += 1
    print(dict(cnt))
    print("\nCells whose stored value reproduces a NON-PAT line of the as-filed statement:")
    n = 0
    for k, r, found in sorted(hits, key=lambda x: x[1]["sym"]):
        labs = [l for l, _ in found]
        if any("net profit" in l.lower() for l in labs):
            continue  # stored IS the statement's PAT — detres backs the store
        n += 1
        print(
            "  %-26s stored=%-11s nse=%-10s  == %s"
            % (
                k,
                r["stored"],
                None if r["nse_pat"] is None else round(r["nse_pat"], 2),
                "; ".join(f"{l}={v}" for l, v in found[:3]),
            )
        )
    print("\n%d cells" % n)
    json.dump(
        {"hits": [{"key": k, "lines": f} for k, _, f in hits]},
        open(os.path.join(HERE, "_vintage109_rowid.json"), "w"),
        indent=1,
    )


if __name__ == "__main__":
    main()
