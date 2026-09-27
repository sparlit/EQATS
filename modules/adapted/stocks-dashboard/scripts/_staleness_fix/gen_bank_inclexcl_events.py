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
"""
NSE's dated inclusion/exclusion register for NIFTY BANK -> scripts/_bank_inclexcl_events.json

Source: scripts/_staleness_fix/IndexInclExcl.xls, sheet "Nifty Bank" (28 rows, 2000-05-02 ..
2020-03-19, Excel serial dates), the same NSE register whose "Nifty 500" sheet feeds
_n500_inclexcl_events.json (gen_inclexcl_events.py). Company names are resolved with an EXPLICIT
map (20 banks, every one unambiguous; the tape key is the sf bin's own key for that bank, verified
2026-09-21 against the bin meta names). The membership builder (build_membership_v2.py) merges
these events into the Nifty Bank walk exactly like the Nifty 500 register: pre-changelog events
wholesale, in-window ones only where the changelog has no same-symbol event within +-10 days.

Measured 2026-09-21 (runbook section 141a): walking these 28 events backward from each archived
official list reproduces EVERY other archived list exactly (12 wayback captures 2006-2026, 0
mismatches), which is the evidence the map and the dates are right.

Run: python3 scripts/_staleness_fix/gen_bank_inclexcl_events.py
"""
import datetime
import json
import os

import xlrd

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
XLS = os.path.join(HERE, "IndexInclExcl.xls")
OUT = os.path.join(SCRIPTS, "_bank_inclexcl_events.json")

NAME_MAP = {
    "Jammu & Kashmir Bank Ltd.": "J&KBANK",
    "Syndicate Bank": "SYNDIBANK",
    "Andhra Bank": "ANDHRABANK",
    "ING Vysya Bank Ltd.": "INGVYSYABK",
    "Axis Bank Ltd.": "AXISBANK",  # traded as UTIBANK until 2007-08-16; bin folds it under AXISBANK
    "Punjab National Bank": "PNB",
    "IndusInd Bank Ltd.": "INDUSINDBK",
    "Union Bank of India": "UNIONBANK",
    "Canara Bank": "CANBK",
    "Global Trust Bank Ltd.": "GLOBLTRUST",
    "Kotak Mahindra Bank Ltd.": "KOTAKBANK",
    "Corporation Bank": "CORPBANK",
    "IDBI Bank Ltd.": "IDBI",  # IDBI Ltd became IDBI Bank in 2008; the bin key is IDBI (tape from 1996)
    "Oriental Bank of Commerce": "ORIENTBANK",
    "Yes Bank Ltd.": "YESBANK",
    "Federal Bank Ltd.": "FEDERALBNK",
    "Bank of India": "BANKINDIA",
    "IDFC Bank Ltd.": "IDFCBANK",  # -> IDFCFIRSTB 2019-01-16 (symchg); builder canon()s it
    "RBL Bank Ltd.": "RBLBANK",
    "Bandhan Bank Ltd.": "BANDHANBNK",
}


def to_iso(v):
    if isinstance(v, float):
        return (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(v))).isoformat()
    s = str(v).strip()
    if len(s) == 10 and s[2] == "-" and s[5] == "-":  # dd-mm-yyyy (the PSU Bank sheet style)
        return s[6:] + "-" + s[3:5] + "-" + s[:2]
    msg = f"unparsed date {v!r}"
    raise SystemExit(msg)


def main():
    sh = xlrd.open_workbook(XLS).sheet_by_name("Nifty Bank")
    events, unmapped = [], []
    for r in range(1, sh.nrows):
        _, dv, name, desc = sh.row_values(r)[:4]
        name = name.strip()
        sym = NAME_MAP.get(name)
        if not sym:
            unmapped.append(name)
            continue
        kind = "inc" if "inclusion" in desc.lower() else "exc" if "exclusion" in desc.lower() else None
        if not kind:
            msg = f"unknown description {desc!r}"
            raise SystemExit(msg)
        events.append([to_iso(dv), sym, kind])
    if unmapped:
        msg = f"unmapped register names: {unmapped}"
        raise SystemExit(msg)
    events.sort()
    out = {
        "events": events,
        "name_map": NAME_MAP,
        "source": "IndexInclExcl.xls sheet 'Nifty Bank' (%d rows %s..%s), explicit name map, gen_bank_inclexcl_events.py 2026-09-21"
        % (len(events), events[0][0], events[-1][0]),
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"), indent=0)
    print("wrote %s: %d events %s..%s" % (OUT, len(events), events[0][0], events[-1][0]))
    for e in events:
        print("  ", e)


if __name__ == "__main__":
    main()
