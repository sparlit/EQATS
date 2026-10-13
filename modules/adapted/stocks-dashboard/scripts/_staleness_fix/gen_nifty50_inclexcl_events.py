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
NSE's dated inclusion/exclusion register for NIFTY 50 -> scripts/_nifty50_inclexcl_events.json

Source: scripts/_staleness_fix/IndexInclExcl.xls, sheet "Nifty 50" (196 rows, 1996-09-18 ..
2020-07-31, Excel serial dates) - the same NSE register whose "Nifty 500" sheet feeds
_n500_inclexcl_events.json (gen_inclexcl_events.py) and whose "Nifty Bank" sheet feeds
_bank_inclexcl_events.json. build_membership_v2.py merges these events into the Nifty 50 walk
(pre-changelog wholesale, in-window only where the changelog has no same-symbol event within
+-10 days) and pins the 18 archived official lists 2006-2026 (_idx_official_snaps.json).

Name -> symbol precedence (nothing guessed):
  1. MANUAL below - the 34 spellings the Nifty 500 sheet never used (older company names). Each
     target is the sf bin's own tape for that company, checked 2026-09-21 (tape span in the comment),
     or the current key whose rename chain reaches the era tape (build_membership_v2 era_key).
     Both legs of a company ALWAYS land on one key (Reckitt & Colman inc 1999 / Reckitt Benckiser
     exc 2002 -> RECKCOLMAN), else the backward walk fabricates a member before its inclusion.
  2. The Nifty 500 ledger's era map (per-event-date symbol, NSE-document bound) for dates before
     2015-03-23, then its exact name map.
  3. Unmapped names are RECORDED, never emitted (Brooke Bond Lipton: excluded 1997-05-07, no tape
     under any key we hold - the 1995-97 rosters are one name short, and say so).

Run: python3 scripts/_staleness_fix/gen_nifty50_inclexcl_events.py
"""
import collections
import datetime
import json
import os

import xlrd

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
XLS = os.path.join(HERE, "IndexInclExcl.xls")
N500 = os.path.join(SCRIPTS, "_n500_inclexcl_events.json")
OUT = os.path.join(SCRIPTS, "_nifty50_inclexcl_events.json")
ERA_CUTOFF = "2015-03-23"

MANUAL = {
    "Arvind Mills Ltd": "ARVIND",  # tape 1996-01-01..
    "Bajaj Auto Ltd": "BAJAJHLDNG",  # the pre-2008 Bajaj Auto = today's Bajaj Holdings (BAJAJAUTO->BAJAJHLDNG); excluded 2008-03-14 on the demerger. "Bajaj Auto Ltd." (dot) = BAJAJ-AUTO, included 2010-10-01
    "Bharti Tele-Ventures Ltd.": "BHARTIARTL",  # tape 2002-02-18..
    "Colgate Palmolive (I) Ltd": "COLPAL",
    "Digital Equipment (india) Ltd.": "DIGITALEQP",  # Digital GlobalSoft, tape 1996..2004-04-08; its 2004 exclusion maps here too
    "East India Hotels Ltd": "EIHOTEL",
    "Essar Gujarat Ltd.": "ESSARGUJ",  # Essar Steel, tape 1996..2005-04-22
    "Gas Authority of India Limited": "GAIL",
    "Glaxo (India) Ltd.": "GLAXO",
    "Great Eastern Shipping Company Limited.": "GESHIP",  # era tape GESHIPPING 1996..2006-11-07 via _rename_map
    "HDFC Life Insurance Company Ltd.": "HDFCLIFE",
    "Hero Honda Motors Limited": "HEROMOTOCO",  # tape 1996-01-01.. (HEROHONDA folded)
    "IDFC Ltd": "IDFC",  # tape 2005-08-12..2024-10-09
    "Indian Rayon & Industries Ltd.": "ABIRLANUVO",  # tape 1996..2017-07-04
    "Industrial Development Bank of India Limited": "IDBI",
    "Industrial Finance Corporation Of India Ltd.": "IFCI",
    "Infosys Technologies Limited": "INFY",
    "Infrastructure Development Finance Company Limited": "IDFC",
    "Madras Refineries Ltd.": "CHENNPETRO",
    "Maruti Udyog Limited": "MARUTI",  # tape 2003-07-09..
    "Nestle India Limited": "NESTLEIND",  # both legs (inc 1996, exc 2003); the bin's NESTLEIND daily tape starts 2010 - early prices stay null, membership is right
    "Novartis India Ltd": "NOVARTIND",  # its 2003 exclusion maps here too
    "Ponds (India) Ltd.": "PONDS",  # tape 1996..1999-01-18
    "Procter & Gamble India Ltd.": "PGHH",
    "Reckitt & Colman India Ltd.": "RECKCOLMAN",  # = "Reckitt Benckiser (India) Ltd" (exc 2002-01-25) in the Nifty 500 map
    "SCICI Ltd.": "SCICI",  # tape 1996..1997-05-05
    "Sesa Goa Limited": "VEDL",  # SESAGOA->VEDL in _rename_map (tape folded under VEDL)
    "Smithkline Beecham Consumer Healthcare Ltd.": "GSKCONS",  # tape 1996..2020-04-15
    "TVS Suzuki Ltd.": "TVSSUZUKI",  # own tape 1996..2000-05-15 (the Nifty 500 map's "TVS Suzuki Ltd. (old)")
    "Tata Tea Limited": "TATACONSUM",  # TATATEA->TATACONSUM in _rename_map
    "Titan Company Ltd.": "TITAN",
    "Videsh Sanchar Nigam Ltd.": "TATACOMM",  # VSNL->TATACOMM in _rename_map
    "Zee Telefilms Ltd": "ZEEL",
}


def to_iso(v):
    if isinstance(v, float):
        return (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(v))).isoformat()
    s = str(v).strip()
    if len(s) == 10 and s[2] == "-" and s[5] == "-":
        return s[6:] + "-" + s[3:5] + "-" + s[:2]
    raise SystemExit(f"unparsed date {v!r}")


def main():
    n500 = json.load(open(N500, encoding="utf-8"))
    name_map, era_map = n500.get("name_map", {}), n500.get("era_map", {})
    sh = xlrd.open_workbook(XLS).sheet_by_name("Nifty 50")
    raw = []
    for r in range(1, sh.nrows):
        _, dv, name, desc = sh.row_values(r)[:4]
        kind = (
            "inc" if "inclusion" in desc.lower() else "exc" if "exclusion" in desc.lower() else None
        )
        if not kind:
            raise SystemExit(f"unknown description {desc!r}")
        raw.append((to_iso(dv), name.strip(), kind))

    def sym_for(n, d):
        if n in MANUAL:
            return MANUAL[n], "manual"
        segs = era_map.get(n)
        if segs and d < ERA_CUTOFF:
            best = None
            for f, sym in segs:
                if f <= d:
                    best = sym
            return (best if best is not None else segs[0][1]), "era"
        if n in name_map:
            return name_map[n], "n500"
        return None, "unmapped"

    events, used, unmapped = [], collections.Counter(), collections.OrderedDict()
    out_map = {}
    for d, n, k in raw:
        sym, how = sym_for(n, d)
        used[how] += 1
        if sym is None:
            unmapped.setdefault(n, []).append((d, k))
            continue
        out_map[n] = sym
        events.append([d, sym, k])
    # NO seam-twin mirroring here (unlike gen_inclexcl_events.py): this walk has no pins before 2006,
    # so a mirrored exclusion (Essar Gujarat 1997-12-24 -> ESSARGUJ AND its 2005 relisting key ESTL)
    # resurrects TWO keys for one company and the 1997 rosters carried 51 names. The builder's era_key
    # already emits the tape alive on the date. Measured 2026-09-21.
    mirrored = []
    events.sort()
    bad = [g for g, c in collections.Counter((d, s) for d, s, _ in events).items() if c > 1]
    for d, s in bad:
        ks = {k for dd, ss, k in events if dd == d and ss == s}
        if len(ks) > 1:
            print(f"  CONFLICT same-day inc+exc: {s} {d} - dropping both")
            events = [e for e in events if not (e[0] == d and e[1] == s)]
    out = {
        "events": events,
        "name_map": out_map,
        "unmapped": dict(unmapped.items()),
        "source": "IndexInclExcl.xls sheet 'Nifty 50' (%d rows %s..%s); precedence MANUAL(%d) > N500 era map(%d) > N500 name map(%d); "
        "unmapped %d; gen_nifty50_inclexcl_events.py 2026-09-21"
        % (
            len(raw),
            raw[0][0] if raw else "",
            max(x[0] for x in raw) if raw else "",
            used["manual"],
            used["era"],
            used["n500"],
            used["unmapped"],
        ),
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"), indent=0)
    print(
        "wrote %s: %d events (%d mirrored on seam twins), names mapped %d; resolution %s"
        % (OUT, len(events), len(mirrored), len(out_map), dict(used))
    )
    for n, v in unmapped.items():
        print(f"  UNMAPPED {n}: {v}")


if __name__ == "__main__":
    main()
