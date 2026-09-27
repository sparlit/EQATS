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
Generic: one sheet of NSE's IndexInclExcl.xls register -> scripts/_<slug>_inclexcl_events.json

Run: python3 scripts/_staleness_fix/gen_register_events.py "Nifty IT" _niftyit_inclexcl_events.json
     python3 scripts/_staleness_fix/gen_register_events.py --all       # every sheet in SHEETS below

Name -> symbol precedence (nothing guessed; runbook section 141c):
  1. register_manual_names.json - hand-verified {register name: bin key}, each with the tape span
     that covers its event dates (the 34 Nifty 50 spellings live in gen_nifty50_inclexcl_events.py).
  2. the Nifty 500 ledger's era map (per-event-date symbol, NSE-document bound) for dates before
     2015-03-23, then its exact name map.
  3. EXACT normalised-name match against the sf bin's own meta names, accepted only when the
     normalised name has >= 2 tokens (or one token of >= 4 letters: "Cyient", "Sobha"), matches
     exactly one key, and that key's tape covers at least one of the name's event dates (+-120 d).
     Every such pair is written to the output for audit.
  4. Unmapped names are RECORDED with their events, never emitted.
Both legs of a company must land on one key or the backward walk fabricates a member; the manual map
is where that is enforced. No seam-twin mirroring (it doubled Essar in the Nifty 50 walk, 141b).
"""
import collections
import datetime
import json
import os
import re
import sys

import xlrd

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
XLS = os.path.join(HERE, "IndexInclExcl.xls")
N500 = os.path.join(SCRIPTS, "_n500_inclexcl_events.json")
MANUAL_FILE = os.path.join(HERE, "register_manual_names.json")
ERA_CUTOFF = "2015-03-23"
# sheet name in the xls -> ledger file (the index's SLUGS name in build_membership_v2 is the key there)
SHEETS = {
    "Nifty Next 50": "_niftynext50_inclexcl_events.json",
    "Nifty 100": "_nifty100_inclexcl_events.json",
    "Nifty 200": "_nifty200_inclexcl_events.json",
    "Nifty Midcap 50": "_niftymidcap50_inclexcl_events.json",
    "Nifty Midcap 100": "_niftymidcap100_inclexcl_events.json",
    "Nifty Smallcap 50": "_niftysmallcap50_inclexcl_events.json",
    "Nifty Smallcap 100": "_niftysmallcap100_inclexcl_events.json",
    "NIFTY LargeMidcap 250": "_niftylargemidcap250_inclexcl_events.json",
    "Nifty IT": "_niftyit_inclexcl_events.json",
    "Nifty Pharma": "_niftypharma_inclexcl_events.json",
    "Nifty Auto": "_niftyauto_inclexcl_events.json",
    "Nifty FMCG": "_niftyfmcg_inclexcl_events.json",
    "Nifty Metal": "_niftymetal_inclexcl_events.json",
    "Nifty Energy": "_niftyenergy_inclexcl_events.json",
    "Nifty Realty": "_niftyrealty_inclexcl_events.json",
    "Nifty Media": "_niftymedia_inclexcl_events.json",
    "Nifty PSU Bank": "_niftypsubank_inclexcl_events.json",
    "Nifty MNC": "_niftymnc_inclexcl_events.json",
}
STOP = {"ltd", "limited", "the", "company", "co", "corporation", "corp", "india", "of", "and", "inc"}


def norm(x):
    x = re.sub(r"\(.*?\)", " ", x.lower())
    return [t for t in re.split(r"[^a-z0-9]+", x) if t and t not in STOP]


def strict_name(x):
    """exact-name key for the same-name lookup: only punctuation, 'ltd/limited' and 'the' are dropped —
    norm() also drops 'india'/'corporation', which made "Welspun India" (WELSPUNLIV, textiles) equal
    "Welspun Corp" (WELCORP, pipes)."""
    x = re.sub(r"\(.*?\)", " ", x.lower().replace("&", " and "))
    return "".join(t for t in re.split(r"[^a-z0-9]+", x) if t and t not in {"ltd", "limited", "the"})


def to_iso(v):
    if isinstance(v, float):
        return (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(v))).isoformat()
    s = str(v).strip()
    if len(s) == 10 and s[2] == "-" and s[5] == "-":
        return s[6:] + "-" + s[3:5] + "-" + s[:2]
    msg = f"unparsed date {v!r}"
    raise SystemExit(msg)


def load_bin_names():
    import gzip

    p = os.environ.get("SF_BIN") or os.path.join(ROOT, "docs", "sf_stock_data.bin")
    D = json.loads(gzip.decompress(open(p, "rb").read()))
    by = collections.defaultdict(list)
    span = {}
    for k, m in D["meta"].items():
        e = D["data"].get(k)
        if not e or not e["d"]:
            continue
        span[k] = (str(e["d"][0]), str(e["d"][-1]))
        nm = m.get("name") or k
        by["".join(norm(nm))].append(k)
        by["STRICT:" + strict_name(nm)].append(k)
    return by, span


def load_renames():
    """RENAME (price-build fold, old -> current key) and REN (NSE symchg: old -> (new, iso date))."""
    import csv

    rename = json.load(open(os.path.join(SCRIPTS, "_rename_map.json")))
    ren = {}
    mon = {
        m: i
        for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)
    }
    for r in csv.reader(open(os.path.join(SCRIPTS, "symchg.csv"), encoding="utf-8", errors="replace")):
        if len(r) >= 4 and r[1].strip() and r[2].strip():
            m = re.match(r"(\d{1,2})-([A-Z]{3})-(\d{4})", r[3].strip().upper())
            d = (
                f"{int(m.group(3)):04d}-{mon[m.group(2)]:02d}-{int(m.group(1)):02d}"
                if m and m.group(2) in mon
                else None
            )
            ren[r[1].strip().upper()] = (r[2].strip().upper(), d)
    return rename, ren


def covers(span, key, d, pad=120):
    if key not in span:
        return False
    lo = (datetime.date.fromisoformat(d) - datetime.timedelta(days=pad)).strftime("%Y%m%d")
    hi = (datetime.date.fromisoformat(d) + datetime.timedelta(days=pad)).strftime("%Y%m%d")
    a, b = span[key]
    return a <= hi and b >= lo


def gen(sheet, out_name, wb, n500, manual, binby, span):
    sh = wb.sheet_by_name(sheet)
    raw = []
    for r in range(1, sh.nrows):
        vals = sh.row_values(r)
        if len(vals) < 4 or not str(vals[2]).strip():
            continue
        _, dv, name, desc = vals[:4]
        kind = "inc" if "inclusion" in desc.lower() else "exc" if "exclusion" in desc.lower() else None
        if not kind:
            msg = f"{sheet}: unknown description {desc!r}"
            raise SystemExit(msg)
        raw.append((to_iso(dv), name.strip(), kind))
    name_map, era_map = n500.get("name_map", {}), n500.get("era_map", {})
    dates_of = collections.defaultdict(list)
    for d, n, k in raw:
        dates_of[n].append(d)

    def to_current(x):
        seen = set()
        while x in RENAME and x not in seen:
            seen.add(x)
            x = RENAME[x]
        return x

    folded_from = collections.defaultdict(set)
    for o in RENAME:
        folded_from[to_current(o)].add(o)

    def canon_ren(x):
        seen = set()
        while x in REN and x not in seen:
            seen.add(x)
            x = REN[x][0]
        return x

    def tape(x, d):
        """does x trade around d, as itself or under its NSE symbol-change successor? (the builder does
        its set arithmetic in that canon() space — a price-build fold like GESHIPPING -> GESHIP that NSE's
        symchg does not carry would split one member into two keys)"""
        return any(covers(span, k, d) for k in {x, canon_ren(x)})

    def renamed_before(x, d):
        r = REN.get(x)
        return bool(r and r[1] and r[1] <= d)

    def same_name_keys(n, d):
        """bin keys whose own meta name is this register name and whose OWN tape covers d"""
        key = strict_name(n)
        return [k for k in binby.get("STRICT:" + key, []) if covers(span, k, d)] if key else []

    def binexact(n):
        toks = norm(n)
        if len(toks) < 2 and (not toks or len(toks[0]) < 4):  # one short token ("ABB") is not a name
            return None
        keys = binby.get("".join(toks), [])
        if len(keys) != 1:
            return None
        return keys[0] if any(covers(span, keys[0], d) for d in dates_of[n]) else None

    def sym_for(n, d):
        if n in manual:
            return manual[n]["sym"] if isinstance(manual[n], dict) else manual[n], "manual"
        # DATE-AWARE resolution (2026-09-23, runbook §141e): the Nifty 500 name_map gives the ticker that
        # holds the name TODAY — "Max India Ltd." -> MAXIND (listed 2020), "KPIT Technologies" -> KPITTECH
        # (the 2019 demerged entity), "Gujarat Fluorochemicals" -> FLUOROCHEM (listed 2019), "Dalmia
        # Bharat" -> DALBHARAT (2019) — wrong for 2015-2020 register rows. Order: the per-date era ticker
        # unless it had been renamed away by d; then any bin key that carries this exact name with a tape
        # on d; then the name_map ticker when it trades on d; else the era ticker.
        segs = era_map.get(n)
        e = None
        if segs:
            for f, sym in segs:
                if f <= d:
                    e = sym
            e = e or segs[0][1]
            if d < ERA_CUTOFF or (not renamed_before(e, d) and tape(e, d)):
                return e, "era"
        sk = same_name_keys(n, d)
        if len(sk) == 1:
            return sk[0], "binname"
        if n in name_map and tape(name_map[n], d):
            return name_map[n], "n500"
        if e and tape(e, d):
            return e, "era"
        if n in name_map:
            return name_map[n], "n500"
        b = binexact(n)
        if b:
            return b, "binexact"
        return None, "unmapped"

    events, used, unmapped, out_map, audit = [], collections.Counter(), collections.OrderedDict(), {}, {}
    for d, n, k in raw:
        sym, how = sym_for(n, d)
        used[how] += 1
        if sym is None:
            unmapped.setdefault(n, []).append([d, k])
            continue
        if how == "binexact":
            audit[n] = sym
        out_map[n] = sym
        events.append([d, sym, k])
    events.sort()
    bad = [g for g, c in collections.Counter((d, s) for d, s, _ in events).items() if c > 1]
    for d, s in bad:
        ks = {k for dd, ss, k in events if dd == d and ss == s}
        if len(ks) > 1:
            print(f"  {sheet} CONFLICT same-day inc+exc: {s} {d} - dropping both")
            events = [e for e in events if not (e[0] == d and e[1] == s)]
    out = {
        "sheet": sheet,
        "events": events,
        "name_map": out_map,
        "binexact_audit": audit,
        "unmapped": dict(unmapped.items()),
        "source": "IndexInclExcl.xls sheet %r (%d rows %s..%s); precedence manual(%d) > N500 era(%d) > N500 name(%d) > bin exact(%d); unmapped %d; gen_register_events.py 2026-09-21"
        % (
            sheet,
            len(raw),
            min(x[0] for x in raw),
            max(x[0] for x in raw),
            used["manual"],
            used["era"],
            used["n500"],
            used["binexact"],
            used["unmapped"],
        ),
    }
    json.dump(out, open(os.path.join(SCRIPTS, out_name), "w", encoding="utf-8"), indent=0)
    print(
        "%-24s %4d events -> %s | %s | unmapped %d %s"
        % (sheet, len(events), out_name, dict(used), len(unmapped), list(unmapped)[:4])
    )
    return out


def main(argv):
    wb = xlrd.open_workbook(XLS)
    n500 = json.load(open(N500, encoding="utf-8"))
    manual = json.load(open(MANUAL_FILE, encoding="utf-8")) if os.path.exists(MANUAL_FILE) else {}
    binby, span = load_bin_names()
    global RENAME, REN
    RENAME, REN = load_renames()
    if argv[1:] == ["--all"]:
        for sheet, out in SHEETS.items():
            gen(sheet, out, wb, n500, manual, binby, span)
    elif len(argv) == 3:
        gen(argv[1], argv[2], wb, n500, manual, binby, span)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
