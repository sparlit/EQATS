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


#!/usr/bin/env python3
"""Second-reader audit runner (runbook §214). Runs every check in scripts/xcheck/ (or the ones named) against the
live stores and writes docs/xcheck.json, the data behind docs/data-checks.html.

  python3 scripts/xcheck_run.py                 # all checks -> docs/xcheck.json
  python3 scripts/xcheck_run.py px_nse_yahoo    # one check (merged into the existing report)
  python3 scripts/xcheck_run.py --out /tmp/x.json px_nse_yahoo

Findings are REPORTED, never auto-fixed: a real defect is healed through its own ledger (DATA_RUNBOOK rule 5);
a disagreement adjudicated as not-a-defect goes into scripts/xcheck_accept.json {check: {key: {why, ts}}}."""
import datetime
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xcheck import common as C
from xcheck.fund import FundEpsShares, FundPbtTax, FundVisionXbrl
from xcheck.market import FlowsMonth, IdxLevels, McapShares
from xcheck.px_nse_yahoo import PxNseYahoo
from xcheck.shp import ShpNeighbours


def ist(fmt="%Y-%m-%d %H:%M"):
    """IST wall time from UTC — a CI runner's local clock is UTC (the first run stamped 04:28 'IST' at 09:58 IST)."""
    return (datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=5, minutes=30)).strftime(
        fmt
    )


CHECKS = [
    PxNseYahoo,
    FundVisionXbrl,
    FundPbtTax,
    FundEpsShares,
    McapShares,
    ShpNeighbours,
    IdxLevels,
    FlowsMonth,
]


def main(argv):
    out = os.path.join(C.DOCS, "xcheck.json")
    if "--out" in argv:
        i = argv.index("--out")
        out = argv[i + 1]
        argv = argv[:i] + argv[i + 2 :]
    want = set(argv)
    rep = {}
    if want and os.path.exists(out):
        try:
            rep = json.load(open(out, encoding="utf-8"))
        except ValueError:
            rep = {}
    rep.setdefault("checks", {})
    accept = C.load_accept()
    failed = []
    for K in CHECKS:
        if want and K.id not in want:
            continue
        t0 = time.time()
        k = K()
        try:
            k.run()
            r = k.report(accept)
            r["secs"] = round(time.time() - t0, 1)
            r["ran"] = ist()
            rep["checks"][K.id] = r
            print(
                "%-18s compared %9d  agree %7s%%  open %5d  explained %5d  accepted %4d  (%.0fs)"
                % (
                    K.id,
                    r["compared"],
                    r["agree_pct"],
                    r["n_open"],
                    r["n_explained"],
                    r["n_accepted"],
                    r["secs"],
                ),
                flush=True,
            )
        except Exception:
            failed.append(K.id)
            traceback.print_exc()
            rep["checks"][K.id] = dict(
                (rep["checks"].get(K.id) or {}),
                error=traceback.format_exc()[-600:],
                error_ran=ist(),
            )
    rep["generated"] = ist() + " IST"
    rep["order"] = [K.id for K in CHECKS]
    tmp = out + ".part"
    json.dump(rep, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, out)
    print("wrote %s (%d KB)" % (out, os.path.getsize(out) // 1024))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
