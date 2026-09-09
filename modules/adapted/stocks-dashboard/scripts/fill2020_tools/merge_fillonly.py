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


"""Fill-only semantic merge of my sf_revop / revop_fundamentals work onto a newer origin/main.

A textual rebase of these minified single-line JSONs always conflicts because CI rewrites them every
few minutes. The MEANING of this change is "fill cells that were empty", so the correct merge is:
start from origin's (newer) file and copy in only the cells where mine has a value and origin does
not. CI's newer values always win; nothing of theirs is overwritten.

argv: <mine.json> <theirs.json> <out.json>
"""
import json
import sys

mine_p, theirs_p, out_p = sys.argv[1:4]
mine = json.load(open(mine_p, encoding="utf-8"))
theirs = json.load(open(theirs_p, encoding="utf-8"))

added = skipped_theirs_has = new_rows = 0
for sym, qmap in mine.items():
    tgt = theirs.setdefault(sym, {})
    for qe, row in qmap.items():
        trow = tgt.get(qe)
        if trow is None:
            tgt[qe] = list(row)
            new_rows += 1
            added += sum(1 for v in row if v is not None)
            continue
        for i, val in enumerate(row):
            if val is None:
                continue
            if i >= len(trow):
                continue
            if trow[i] is None:
                trow[i] = val
                added += 1
            elif trow[i] != val:
                skipped_theirs_has += 1

json.dump(theirs, open(out_p, "w", encoding="utf-8"), separators=(",", ":"))
print(
    f"merged -> {out_p}: {added} cells added, {new_rows} new rows, "
    f"{skipped_theirs_has} left as origin had them (origin wins)"
)
