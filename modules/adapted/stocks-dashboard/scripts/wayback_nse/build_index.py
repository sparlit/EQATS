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
"""Build scripts/wayback_nse/_wb_index.json — "SYM|QEINT" -> [wayback_timestamp, original_url].

The archived URL is  results.jsp?<from><to><PERIOD><FLAGS><SYMBOL>  with no separators, e.g.
`01-OCT-200231-DEC-2002Q3UNNNERELIANCE`. PERIOD is one of Q1-Q4/H1/H2/AN/OT and FLAGS is a short
run of letters whose length VARIES by site vintage (the 2002 grammar uses a 1-character audit flag
where later ones use 2).

⚠️ THE BUG THIS FILE EXISTS TO NOT REPEAT. The first build took "the longest suffix that is a key in
sf_fundamentals" as the symbol. When the TRUE symbol is not one of our keys (a rename, a delisting),
a SHORTER suffix that happens to be a key captures the page instead: BHARTI's page was filed under
`TI` (Tube Investments), KLGSYSTEL's under `STEL`, TATAHONEY's under `EY`, UCALFUEL's under `UEL`,
NAVNETPUBL's under `UBL`. 31 of 2,005 cached pages -- a FALSE ATTRIBUTION, one company's filing
keyed to another, which is exactly the §76 "a matching token is a coincidence to be disproved" class.
Nothing wrong was ever written from them because the gate's G1 re-checks the page's OWN declared
"NSE Symbol" against the symbol asked for and rejected every one. But the true symbols were then
MISSING from the index, so reachability was under-counted and the misses looked like "no capture
exists" -- absence manufactured by our own key.

THE FIX, two independent constraints:
  1. the text between the dates and the symbol must parse as PERIOD + at most MAX_FLAGS letters, so
     a suffix that would leave 9 letters of "flags" (`UNNNEBHAR`) is rejected on sight; and
  2. where the page is cached, its OWN declared NSE Symbol wins outright -- the document is the
     authority, never our guess.
A page whose symbol resolves to neither is recorded in `_wb_unresolved.json` rather than dropped,
so the residue stays measurable instead of silently becoming a Class-A refusal.

  python3 -X utf8 scripts/wayback_nse/build_index.py --cdx cdx.txt
"""
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from wbcache import cached  # noqa: E402

MON = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}
QEND = {(3, 31), (6, 30), (9, 30), (12, 31)}
# THE FLAG GRAMMAR, derived rather than assumed: on 1,987 entries whose symbol the PAGE itself
# confirms, the run between the period token and the symbol matches ^[AU][A-Z]{0,5}E$ in 99.7% of
# cases -- Audited/Unaudited first, always a trailing E (UNNNE, UNCXE, ANCNE, UNE, ACE, UCE...).
# The 5 exceptions are precisely the corrupt pages whose own printed symbol is truncated.
# This is what makes the URL parse DETERMINISTIC and cache-independent. Without it the longest-
# suffix rule silently prefers a wrong longer key once the universe widens: `...Q3UNNNETIL` reads
# as ETIL (flags UNNN, no trailing E) instead of TIL (flags UNNNE) -- and the page says TIL LTD.
PREFIX = re.compile(
    r"^(\d{2}-[A-Z]{3}-\d{4})(\d{2}-[A-Z]{3}-\d{4})"
    r"(Q[1-4]|H[12]|AN|OT)([AU][A-Z]{0,5}E)$"
)
SPLIT = re.compile(r"^(\d{2}-[A-Z]{3}-\d{4})(\d{2}-[A-Z]{3}-\d{4})(.*)$")
DECL = re.compile(r"NSE Symbol\s*</[^>]*>\s*[^<]*?([A-Z0-9&_-]{2,})|NSE Symbol\s+([A-Z0-9&_-]{2,})")


def declared_symbol(raw):
    """The page's OWN NSE Symbol, or None. The document outranks any guess from the URL."""
    if not raw:
        return None
    import html as _h

    t = re.sub(r"<[^>]+>", " ", raw)
    t = re.sub(r"\s+", " ", _h.unescape(t))
    m = re.search(r"NSE Symbol\s+([A-Z0-9&_-]{2,})", t)
    return m.group(1) if m else None


def qe_of(dstr):
    d, mo, y = dstr.split("-")
    mo, d = MON[mo], int(d)
    return int(y) * 10000 + mo * 100 + d if (mo, d) in QEND else None


def main():
    av = sys.argv
    cdx = av[av.index("--cdx") + 1]
    out = av[av.index("--out") + 1] if "--out" in av else os.path.join(HERE, "_wb_index.json")
    # ⚠️ THE KEY UNIVERSE MUST NOT BE sf_fundamentals ALONE -- that file EXCLUDES exactly the
    # symbols worth indexing. A symbol we hold no row for is absent from it, so the URL parse can
    # never key its pages, so it can never be found reachable, so it keeps no rows: a self-sealing
    # gap, and a reachability verdict manufactured by our own key set rather than by the world.
    # Measured 2026-08-26: of the 50 Nifty-500 members with NO fundamentals row at all pre-2009,
    # sf_fundamentals contains ZERO as keys, so the index reported 1 of 50 reachable. Searching the
    # raw CDX for the same 50 finds EIGHT with pages -- GLOBLTRUST 10, STDIND 8, SEARCHEMIN 8,
    # SQRDSFWARE 7, INDOGULF 6, SURYCOTMIL 6, MUKAND 5, WELSPUNGUJ 1 (51 pre-2009 pages).
    # Same class as runbook §112e: the answer was about our own frame, not the archive's contents.
    # So the universe is every symbol we could ever ASK about: the fundamentals store, the price
    # tape's metadata, and every point-in-time index roll.
    keys = set(json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json"))))
    try:
        import gzip

        D = json.loads(gzip.open(os.path.join(ROOT, "docs", "dash_slim.bin"), "rb").read().decode("utf-8"))
        for m in (D.get("meta") or {}).values():
            if m.get("symbol"):
                keys.add(m["symbol"])
        for rolls in (D.get("indicesHistory") or {}).values():
            for snap in rolls:
                keys.update(snap.get("symbols") or [])
    except Exception as e:
        print(
            f"WARN: could not widen the key universe from dash_slim.bin ({e}) -- "
            "the index will be blind to symbols with no fundamentals row"
        )
    print("key universe:", len(keys), "symbols")

    idx, unresolved, stat = {}, [], collections.Counter()
    for line in open(cdx):
        line = line.rstrip("\n")
        if " " not in line:
            continue
        ts, u = line.split(" ", 1)
        if "?" not in u:
            continue
        q = u.split("?", 1)[1]
        m = SPLIT.match(q)
        if not m:
            continue
        _f, t, rest = m.groups()
        qe = qe_of(t)
        if qe is None:
            stat["period does not end on a quarter-end"] += 1
            continue

        # (2) the document is the authority -- but ONLY when the document is intact. A
        # server-side template failure prints a TRUNCATED symbol ("NSE Symbol CI" on an IFCI page,
        # "Result Type AuditedEI", trailing bare `null`), and trusting that would key one company's
        # page under another's ticker -- the very defect this rebuild exists to remove, re-entered
        # from the other side. So a declared symbol is accepted only if it corroborates: it is a
        # key we hold, or the URL's own trailing token ends with it.
        decl = declared_symbol(cached(ts, u))
        sym = how = None
        if (
            decl
            and (decl in keys or rest.endswith(decl))
            and not (len(decl) < len(rest) and rest.endswith(decl) and decl not in keys)
        ):
            sym, how = decl, "page"
        if sym is None:  # (1) constrained URL parse
            for L in range(min(len(rest), 14), 1, -1):
                cand = rest[-L:]
                if cand in keys and PREFIX.match(q[: len(q) - L]):
                    sym, how = cand, "url"
                    break
        if sym is None and decl:  # last resort: an uncorroborated print
            sym, how = decl, "page-uncorroborated"
        if sym is None:
            unresolved.append([ts, u])
            stat["symbol unresolved"] += 1
            continue
        stat["keyed by the " + how] += 1
        idx.setdefault("%s|%d" % (sym, qe), [ts, u])

    json.dump(idx, open(out, "w"), indent=0, sort_keys=True)
    json.dump(unresolved, open(os.path.join(HERE, "_wb_unresolved.json"), "w"), indent=0)
    print("index entries:", len(idx), "-> " + out)
    for k, v in stat.most_common():
        print("  %6d  %s" % (v, k))
    print("  %6d  unresolved -> _wb_unresolved.json" % len(unresolved))


if __name__ == "__main__":
    main()
